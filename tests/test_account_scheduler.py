import random

from app.core import account_scheduler as scheduler


# ---------------------------------------------------------------------------
# Weight transitions
# ---------------------------------------------------------------------------

def test_increase_weight_caps_at_max():
    assert scheduler.increase_weight(50) == 50 + scheduler.WEIGHT_SUCCESS_STEP
    assert scheduler.increase_weight(scheduler.WEIGHT_MAX) == scheduler.WEIGHT_MAX


def test_decrease_weight_floors_at_min():
    assert scheduler.decrease_weight(100, scheduler.WEIGHT_TRANSIENT_FAILURE_STEP) == 80
    assert scheduler.decrease_weight(10, 50) == scheduler.WEIGHT_MIN


def test_should_cooldown_and_recovery():
    assert scheduler.should_cooldown(scheduler.WEIGHT_COOLDOWN_THRESHOLD) is True
    assert scheduler.should_cooldown(scheduler.WEIGHT_COOLDOWN_THRESHOLD + 1) is False
    assert scheduler.recovered_weight(0) == scheduler.WEIGHT_RECOVERY_VALUE
    assert scheduler.recovered_weight(80) == 80


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def test_choose_returns_none_when_empty():
    assert scheduler.choose([]) is None


def test_eligible_candidates_bounds_call_gap():
    cands = [
        scheduler.Candidate(key="a", weight=100, call_count=0),
        scheduler.Candidate(key="b", weight=100, call_count=scheduler.MAX_CALL_GAP),
    ]
    eligible = scheduler.eligible_candidates(cands)
    assert [c.key for c in eligible] == ["a"]


def test_choose_favours_heavier_weight():
    rng = random.Random(123)
    counts = {"a": 0, "b": 0}
    cands = [
        scheduler.Candidate(key="a", weight=90, call_count=0),
        scheduler.Candidate(key="b", weight=10, call_count=0),
    ]
    for _ in range(2000):
        counts[scheduler.choose(cands, rng=rng)] += 1
    assert counts["a"] > counts["b"] * 2


def test_choose_falls_back_to_uniform_when_zero_weight():
    rng = random.Random(1)
    cands = [
        scheduler.Candidate(key="a", weight=0, call_count=0),
        scheduler.Candidate(key="b", weight=0, call_count=0),
    ]
    picked = {scheduler.choose(cands, rng=rng) for _ in range(50)}
    assert picked == {"a", "b"}


# ---------------------------------------------------------------------------
# Interval jitter
# ---------------------------------------------------------------------------

def test_jittered_interval_without_jitter_is_base():
    assert scheduler.jittered_interval(0.5, 0.0) == 0.5


def test_jittered_interval_stays_within_bounds():
    rng = random.Random(7)
    for _ in range(200):
        value = scheduler.jittered_interval(0.5, 0.5, rng=rng)
        assert 0.5 <= value < 1.0


# ---------------------------------------------------------------------------
# Exponential 429 back-off
# ---------------------------------------------------------------------------

def test_rate_limit_cooldown_grows_exponentially():
    base = scheduler.RATE_LIMIT_BACKOFF_BASE_SECONDS
    assert scheduler.rate_limit_cooldown(1) == base
    assert scheduler.rate_limit_cooldown(2) == base * 2
    assert scheduler.rate_limit_cooldown(3) == base * 4


def test_rate_limit_cooldown_is_capped():
    assert scheduler.rate_limit_cooldown(50) == scheduler.RATE_LIMIT_BACKOFF_MAX_SECONDS


def test_rate_limit_cooldown_honours_retry_after_as_lower_bound():
    assert scheduler.rate_limit_cooldown(1, retry_after=100) == 100
    # retry_after below the computed back-off does not shorten it
    assert scheduler.rate_limit_cooldown(3, retry_after=10) == scheduler.RATE_LIMIT_BACKOFF_BASE_SECONDS * 4


# ---------------------------------------------------------------------------
# Sliding-window quota
# ---------------------------------------------------------------------------

def test_quota_disabled_when_no_limits():
    quota = scheduler.SlidingWindowQuota()
    assert quota.enabled is False
    assert quota.is_exhausted(1000) is False


def test_per_minute_quota_exhausts_and_recovers():
    quota = scheduler.SlidingWindowQuota(per_minute=3)
    now = 1000.0
    for _ in range(3):
        assert quota.is_exhausted(now) is False
        quota.record(now)
    assert quota.is_exhausted(now) is True
    assert quota.is_exhausted(now + 61) is False


def test_per_hour_quota_exhausts_and_recovers():
    quota = scheduler.SlidingWindowQuota(per_hour=2)
    now = 1000.0
    quota.record(now)
    quota.record(now)
    assert quota.is_exhausted(now) is True
    assert quota.is_exhausted(now + 3601) is False


def test_quota_retry_at_is_within_window():
    quota = scheduler.SlidingWindowQuota(per_minute=2)
    now = 1000.0
    quota.record(now)
    quota.record(now)
    retry = quota.retry_at(now)
    assert now < retry <= now + 60


# ---------------------------------------------------------------------------
# Soft cooldown (burst)
# ---------------------------------------------------------------------------

def test_burst_triggers_rest_after_threshold():
    tracker = scheduler.BurstTracker(burst=5, window_seconds=60.0, rest_seconds=5.0)
    now = 1000.0
    for _ in range(4):
        assert tracker.record_success(now) == 0.0
    assert tracker.record_success(now) == now + 5.0
    # window is cleared after triggering
    assert tracker.record_success(now) == 0.0


def test_burst_does_not_trigger_for_slow_successes():
    tracker = scheduler.BurstTracker(burst=3, window_seconds=10.0, rest_seconds=5.0)
    assert tracker.record_success(0) == 0.0
    assert tracker.record_success(100) == 0.0
    assert tracker.record_success(200) == 0.0


def test_burst_disabled_when_zero():
    tracker = scheduler.BurstTracker(burst=0)
    assert tracker.enabled is False
    assert tracker.record_success(1000) == 0.0


# ---------------------------------------------------------------------------
# Auto-probe timing
# ---------------------------------------------------------------------------

def test_should_auto_probe_respects_interval():
    assert scheduler.should_auto_probe(0, 300, interval=300) is True
    assert scheduler.should_auto_probe(0, 299, interval=300) is False
    assert scheduler.should_auto_probe(0, 10_000, interval=0) is False
