"""Weighted, health-aware scheduling policy for the Kimi account pool.

This module holds the *pure* scheduling math so it can be reasoned about and
unit-tested without pulling in HTTP/runtime dependencies. The account pool wires
this policy onto live :class:`KimiAccountRuntime` objects.

Risk-reduction strategy (all aimed at lowering upstream rate-control pressure)
------------------------------------------------------------------------------
* **Weighted-random selection** - each account carries a ``weight`` in
  ``[WEIGHT_MIN, WEIGHT_MAX]`` reflecting recent health. Selection is weighted
  random (not strict round-robin), and a per-account ``call_count`` gap cap
  (``MAX_CALL_GAP``) keeps traffic spread without being perfectly balanced.
* **Health weighting** - a success nudges weight up; a failure pushes it down
  (rate-limit failures hit hardest). At/under ``WEIGHT_COOLDOWN_THRESHOLD`` the
  account is paused; after the cooldown it recovers to ``WEIGHT_RECOVERY_VALUE``
  (partial, not full).
* **Sliding-window quota** - optional per-minute / per-hour request caps. An
  account that reached its quota is skipped *before* being called.
* **Interval jitter** - the per-account minimum request spacing gets a random
  ``[0, jitter)`` add-on so the cadence looks less mechanical.
* **Exponential 429 back-off** - consecutive rate-limit hits lengthen the
  cooldown (``base * 2**(n-1)``, capped), instead of a flat delay.
* **Soft cooldown** - after a burst of rapid successes an account gets a short
  rest so it is never hammered flat-out.
* **Auto-probe recovery** - accounts knocked out by auth errors become eligible
  for an automatic liveness probe after a quiet period.
"""

import random
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Optional, Sequence

# --- Weight bounds. ---
WEIGHT_MAX = 100.0
WEIGHT_MIN = 0.0
WEIGHT_INITIAL = 100.0

# --- Per-event weight deltas. ---
WEIGHT_SUCCESS_STEP = 5.0
WEIGHT_TRANSIENT_FAILURE_STEP = 20.0
WEIGHT_RATE_LIMIT_FAILURE_STEP = 50.0

# Weight at/under which the account is put to sleep, and the level it recovers
# to once the cooldown elapses.
WEIGHT_COOLDOWN_THRESHOLD = 20.0
WEIGHT_RECOVERY_VALUE = 50.0

# Maximum allowed gap between the busiest and least-busy selectable account.
MAX_CALL_GAP = 8

# --- Exponential back-off for repeated rate limiting. ---
RATE_LIMIT_BACKOFF_BASE_SECONDS = 60.0
RATE_LIMIT_BACKOFF_MAX_SECONDS = 1800.0

# --- Soft cooldown after a burst of rapid successes. ---
# If SOFT_COOLDOWN_BURST successes happen within SOFT_COOLDOWN_WINDOW_SECONDS,
# rest the account for SOFT_COOLDOWN_REST_SECONDS.
SOFT_COOLDOWN_BURST = 30
SOFT_COOLDOWN_WINDOW_SECONDS = 60.0
SOFT_COOLDOWN_REST_SECONDS = 5.0

# --- Auto-probe of unhealthy (auth-failed) accounts. ---
AUTO_PROBE_INTERVAL_SECONDS = 300.0


@dataclass
class Candidate:
    """A lightweight view of a selectable account used for picking."""

    key: Any
    weight: float
    call_count: int


# ---------------------------------------------------------------------------
# Weight transitions
# ---------------------------------------------------------------------------

def increase_weight(weight: float) -> float:
    """Bump weight after a success, capped at :data:`WEIGHT_MAX`."""
    return min(weight + WEIGHT_SUCCESS_STEP, WEIGHT_MAX)


def decrease_weight(weight: float, step: float) -> float:
    """Reduce weight after a failure, floored at :data:`WEIGHT_MIN`."""
    return max(weight - step, WEIGHT_MIN)


def should_cooldown(weight: float) -> bool:
    """Whether the (already de-weighted) account should be paused."""
    return weight <= WEIGHT_COOLDOWN_THRESHOLD


def recovered_weight(weight: float) -> float:
    """Weight to restore once a cooldown elapses (a partial recovery)."""
    return weight if weight >= WEIGHT_RECOVERY_VALUE else WEIGHT_RECOVERY_VALUE


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def eligible_candidates(candidates: Sequence[Candidate]) -> list:
    """Filter out accounts that are already ``MAX_CALL_GAP`` calls (or more)
    ahead of the least-used selectable account.

    This keeps the spread between the busiest and least-used selectable account
    at no more than :data:`MAX_CALL_GAP`.
    """
    if not candidates:
        return []
    min_calls = min(candidate.call_count for candidate in candidates)
    limit = min_calls + MAX_CALL_GAP
    return [candidate for candidate in candidates if candidate.call_count < limit]


def choose(
    candidates: Sequence[Candidate],
    *,
    rng: Optional[random.Random] = None,
) -> Any:
    """Pick a candidate's ``key`` via gap-bounded weighted-random selection.

    Returns ``None`` when there are no candidates.
    """
    pool = eligible_candidates(candidates)
    if not pool:
        return None

    chooser = rng or random
    weights = [candidate.weight if candidate.weight > 0 else 0.0 for candidate in pool]
    if sum(weights) <= 0:
        return chooser.choice(pool).key
    return chooser.choices(pool, weights=weights, k=1)[0].key


# ---------------------------------------------------------------------------
# Interval jitter
# ---------------------------------------------------------------------------

def jittered_interval(
    base_seconds: float,
    jitter_seconds: float,
    *,
    rng: Optional[random.Random] = None,
) -> float:
    """Return ``base + random(0, jitter)`` so request cadence looks less robotic."""
    base = max(base_seconds, 0.0)
    jitter = max(jitter_seconds, 0.0)
    if jitter <= 0:
        return base
    chooser = rng or random
    return base + chooser.uniform(0.0, jitter)


# ---------------------------------------------------------------------------
# Exponential 429 back-off
# ---------------------------------------------------------------------------

def rate_limit_cooldown(
    consecutive_hits: int,
    *,
    retry_after: Optional[float] = None,
    base_seconds: float = RATE_LIMIT_BACKOFF_BASE_SECONDS,
    max_seconds: float = RATE_LIMIT_BACKOFF_MAX_SECONDS,
) -> float:
    """Cooldown for a 429, growing exponentially with consecutive hits.

    ``consecutive_hits`` is 1-based for the first hit. An upstream
    ``Retry-After`` is always honoured as a lower bound.
    """
    exponent = max(consecutive_hits - 1, 0)
    backoff = base_seconds * (2 ** exponent)
    backoff = min(backoff, max_seconds)
    if retry_after is not None and retry_after > 0:
        return min(max(retry_after, backoff), max_seconds)
    return backoff


# ---------------------------------------------------------------------------
# Sliding-window quota
# ---------------------------------------------------------------------------

@dataclass
class SlidingWindowQuota:
    """Tracks request timestamps to enforce per-minute / per-hour caps.

    A limit of ``0`` means "no cap" for that window.
    """

    per_minute: int = 0
    per_hour: int = 0
    _events: Deque[float] = field(default_factory=deque, repr=False)

    @property
    def enabled(self) -> bool:
        return self.per_minute > 0 or self.per_hour > 0

    def _evict(self, now: float) -> None:
        horizon = 3600.0 if self.per_hour > 0 else 60.0
        cutoff = now - horizon
        while self._events and self._events[0] < cutoff:
            self._events.popleft()

    def _count_within(self, now: float, window: float) -> int:
        cutoff = now - window
        return sum(1 for ts in self._events if ts >= cutoff)

    def is_exhausted(self, now: float) -> bool:
        """Whether either configured window is currently at its cap."""
        if not self.enabled:
            return False
        self._evict(now)
        if self.per_minute > 0 and self._count_within(now, 60.0) >= self.per_minute:
            return True
        if self.per_hour > 0 and self._count_within(now, 3600.0) >= self.per_hour:
            return True
        return False

    def record(self, now: float) -> None:
        """Record a consumed request."""
        if not self.enabled:
            return
        self._events.append(now)
        self._evict(now)

    def retry_at(self, now: float) -> float:
        """Earliest time the account leaves the exhausted state (0 if free)."""
        if not self.enabled or not self._events:
            return 0.0
        self._evict(now)
        candidates = []
        if self.per_minute > 0 and self._count_within(now, 60.0) >= self.per_minute:
            kept = sorted(ts for ts in self._events if ts >= now - 60.0)
            if len(kept) >= self.per_minute:
                candidates.append(kept[-self.per_minute] + 60.0)
        if self.per_hour > 0 and self._count_within(now, 3600.0) >= self.per_hour:
            kept = sorted(ts for ts in self._events if ts >= now - 3600.0)
            if len(kept) >= self.per_hour:
                candidates.append(kept[-self.per_hour] + 3600.0)
        return max(candidates) if candidates else 0.0


# ---------------------------------------------------------------------------
# Soft cooldown (rest after a burst of rapid successes)
# ---------------------------------------------------------------------------

@dataclass
class BurstTracker:
    """Detects bursts of rapid successes to trigger a short rest."""

    burst: int = SOFT_COOLDOWN_BURST
    window_seconds: float = SOFT_COOLDOWN_WINDOW_SECONDS
    rest_seconds: float = SOFT_COOLDOWN_REST_SECONDS
    _events: Deque[float] = field(default_factory=deque, repr=False)

    @property
    def enabled(self) -> bool:
        return self.burst > 0 and self.rest_seconds > 0

    def record_success(self, now: float) -> float:
        """Record a success; return a rest-until timestamp (0 if no rest).

        When ``burst`` successes occur within ``window_seconds`` the window is
        cleared and a ``rest_seconds`` rest is suggested.
        """
        if not self.enabled:
            return 0.0
        cutoff = now - self.window_seconds
        while self._events and self._events[0] < cutoff:
            self._events.popleft()
        self._events.append(now)
        if len(self._events) >= self.burst:
            self._events.clear()
            return now + self.rest_seconds
        return 0.0


# ---------------------------------------------------------------------------
# Auto-probe of unhealthy accounts
# ---------------------------------------------------------------------------

def should_auto_probe(
    last_probe_at: float,
    now: float,
    *,
    interval: float = AUTO_PROBE_INTERVAL_SECONDS,
) -> bool:
    """Whether an unhealthy account is due for an automatic liveness probe."""
    if interval <= 0:
        return False
    return (now - last_probe_at) >= interval
