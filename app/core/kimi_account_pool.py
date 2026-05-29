import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Set

from ..config import Config
from ..kimi.protocol import KimiAPIError
from ..kimi.transport import KimiRateLimiter, KimiTransport, process_session_id
from . import account_scheduler as scheduler
from .kimi_account_store import (
    KimiAccountConfig,
    load_kimi_accounts,
    update_kimi_account_access_cache,
)
from .token_display import token_preview, token_type_label
from .token_manager import TokenManager

DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 60.0
DEFAULT_TRANSIENT_COOLDOWN_SECONDS = 30.0


@dataclass
class KimiAccountRuntime:
    account: KimiAccountConfig
    token_manager: TokenManager
    transport: KimiTransport
    session_id: str
    in_flight: int = 0
    cooldown_until: float = 0.0
    unhealthy_error: str = ""
    weight: float = scheduler.WEIGHT_INITIAL
    call_count: int = 0
    rate_limit_strikes: int = 0
    last_probe_at: float = 0.0
    quota: scheduler.SlidingWindowQuota = field(default_factory=scheduler.SlidingWindowQuota)
    burst: scheduler.BurstTracker = field(default_factory=scheduler.BurstTracker)

    @property
    def account_id(self) -> str:
        return self.account.id

    @property
    def account_name(self) -> str:
        return self.account.name

    @property
    def enabled(self) -> bool:
        return self.account.enabled

    def is_cooling_down(self, now: Optional[float] = None) -> bool:
        return self.cooldown_until > (now if now is not None else time.time())

    def is_quota_exhausted(self, now: Optional[float] = None) -> bool:
        return self.quota.is_exhausted(now if now is not None else time.time())

    def has_capacity(self) -> bool:
        return self.in_flight < self.account.max_concurrency

    def is_selectable(self, now: Optional[float] = None) -> bool:
        current = now if now is not None else time.time()
        return (
            self.enabled
            and not self.unhealthy_error
            and not self.is_cooling_down(current)
            and not self.is_quota_exhausted(current)
            and self.has_capacity()
        )

    async def close(self) -> None:
        await self.transport.close()


class KimiAccountPool:
    def __init__(
        self,
        accounts: List[KimiAccountConfig],
        *,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: int = 3,
    ):
        self._base_url = (base_url or Config.KIMI_API_BASE).rstrip("/")
        self._timeout = timeout or Config.TIMEOUT
        self._max_retries = max(int(max_retries), 1)
        self._selection_lock = asyncio.Lock()
        self._runtimes: List[KimiAccountRuntime] = [
            self._build_runtime(account)
            for account in accounts
        ]

    def _build_runtime(self, account: KimiAccountConfig) -> KimiAccountRuntime:
        rate_limiter = KimiRateLimiter(
            max_concurrency=account.max_concurrency,
            min_interval_seconds=account.min_interval_seconds,
            jitter_seconds=max(float(getattr(Config, "KIMI_REQUEST_INTERVAL_JITTER", 0.0)), 0.0),
        )
        transport = KimiTransport(
            base_url=self._base_url,
            timeout=self._timeout,
            max_retries=self._max_retries,
            rate_limiter=rate_limiter,
        )
        token_manager = TokenManager(
            account.raw_token,
            base_url=self._base_url,
            cached_access_token=account.cached_access_token,
            cached_access_expires_at=account.cached_access_expires_at,
            device_id=account.device_id,
            session_id=process_session_id(),
            transport=transport,
            on_token_refreshed=lambda state, account=account: update_kimi_account_access_cache(
                account.id,
                state.access_token,
                state.expires_at,
                expected_raw_token=account.raw_token,
            ),
        )
        return KimiAccountRuntime(
            account=account,
            token_manager=token_manager,
            transport=transport,
            session_id=process_session_id(),
            quota=scheduler.SlidingWindowQuota(
                per_minute=max(int(getattr(Config, "KIMI_MAX_REQUESTS_PER_MINUTE", 0)), 0),
                per_hour=max(int(getattr(Config, "KIMI_MAX_REQUESTS_PER_HOUR", 0)), 0),
            ),
            burst=scheduler.BurstTracker(),
        )

    @property
    def configured(self) -> bool:
        return bool(self._runtimes)

    def account_count(self) -> int:
        return len(self._runtimes)

    def _runtime_by_id(self, account_id: str) -> Optional[KimiAccountRuntime]:
        return next((runtime for runtime in self._runtimes if runtime.account_id == account_id), None)

    def _min_active_call_count(
        self,
        *,
        exclude_id: str,
        now: float,
    ) -> Optional[int]:
        counts = [
            runtime.call_count
            for runtime in self._runtimes
            if runtime.account_id != exclude_id
            and runtime.enabled
            and not runtime.unhealthy_error
            and not runtime.is_cooling_down(now)
        ]
        return min(counts) if counts else None

    def _apply_cooldown_recovery(self, runtime: KimiAccountRuntime, now: float) -> None:
        """Restore weight (and re-join the pack) once a cooldown has elapsed."""
        if not runtime.cooldown_until or now < runtime.cooldown_until:
            return
        runtime.cooldown_until = 0.0
        runtime.weight = scheduler.recovered_weight(runtime.weight)
        # Snap up to the least-used active account so the just-recovered account
        # is not flooded with the backlog it missed while paused.
        active_min = self._min_active_call_count(exclude_id=runtime.account_id, now=now)
        if active_min is not None and runtime.call_count < active_min:
            runtime.call_count = active_min

    def _available_runtimes(
        self,
        *,
        exclude: Optional[Set[str]] = None,
        now: Optional[float] = None,
    ) -> List[KimiAccountRuntime]:
        excluded = exclude or set()
        current = time.time() if now is None else now
        available: List[KimiAccountRuntime] = []
        for runtime in self._runtimes:
            self._apply_cooldown_recovery(runtime, current)
            if runtime.account_id not in excluded and runtime.is_selectable(current):
                available.append(runtime)
        return available

    async def _select_runtime(
        self,
        *,
        account_id: Optional[str] = None,
        exclude: Optional[Set[str]] = None,
        require_selectable: bool = True,
    ) -> KimiAccountRuntime:
        async with self._selection_lock:
            if account_id:
                runtime = self._runtime_by_id(account_id)
                if runtime is None:
                    raise KimiAPIError(
                        f"Kimi account `{account_id}` was not found",
                        upstream_error_type="no_available_account",
                    )
                if require_selectable and not runtime.is_selectable():
                    raise KimiAPIError(
                        f"Kimi account `{runtime.account_name}` is not available",
                        upstream_error_type="no_available_account",
                    )
                runtime.in_flight += 1
                runtime.call_count += 1
                runtime.quota.record(time.time())
                return runtime

            candidates = self._available_runtimes(exclude=exclude)
            if not candidates:
                raise KimiAPIError(
                    "No available Kimi accounts",
                    upstream_error_type="no_available_account",
                )

            selected = scheduler.choose(
                [
                    scheduler.Candidate(
                        key=runtime,
                        weight=runtime.weight,
                        call_count=runtime.call_count,
                    )
                    for runtime in candidates
                ]
            )
            if selected is None:
                raise KimiAPIError(
                    "No available Kimi accounts",
                    upstream_error_type="no_available_account",
                )
            selected.in_flight += 1
            selected.call_count += 1
            selected.quota.record(time.time())
            return selected

    @asynccontextmanager
    async def acquire(
        self,
        *,
        account_id: Optional[str] = None,
        exclude: Optional[Set[str]] = None,
        require_selectable: bool = True,
    ) -> AsyncIterator[KimiAccountRuntime]:
        runtime = await self._select_runtime(
            account_id=account_id,
            exclude=exclude,
            require_selectable=require_selectable,
        )
        try:
            yield runtime
        finally:
            async with self._selection_lock:
                runtime.in_flight = max(runtime.in_flight - 1, 0)

    def record_success(self, runtime: KimiAccountRuntime) -> None:
        now = time.time()
        runtime.unhealthy_error = ""
        runtime.rate_limit_strikes = 0
        runtime.weight = scheduler.increase_weight(runtime.weight)
        # Soft cooldown: after a burst of rapid successes, rest the account
        # briefly so it is never driven flat-out. Never shorten an existing
        # (harder) cooldown.
        rest_until = runtime.burst.record_success(now)
        if rest_until > runtime.cooldown_until:
            runtime.cooldown_until = rest_until
        elif not runtime.is_cooling_down(now):
            runtime.cooldown_until = 0.0

    def record_failure(self, runtime: KimiAccountRuntime, exc: Exception) -> None:
        now = time.time()
        error_type = ""
        status_code = 0
        retry_after: Optional[float] = None
        if isinstance(exc, KimiAPIError):
            error_type = exc.upstream_error_type
            status_code = int(exc.upstream_status_code or 0)
            retry_after = exc.retry_after

        # Auth / refresh problems need manual intervention: take the account out
        # of rotation until an admin refreshes or validates it (or an automatic
        # probe recovers it). Weight is left untouched so it resumes at full
        # strength once fixed.
        if error_type == "token_refresh_failed" or status_code in {401, 403}:
            runtime.unhealthy_error = str(exc)
            runtime.cooldown_until = 0.0
            return

        # Rate limiting is the strongest risk-control signal: drop weight hard
        # and back off exponentially on consecutive hits, always honouring the
        # upstream Retry-After as a lower bound.
        if status_code == 429 or error_type == "rate_limited":
            runtime.rate_limit_strikes += 1
            runtime.weight = scheduler.decrease_weight(
                runtime.weight, scheduler.WEIGHT_RATE_LIMIT_FAILURE_STEP
            )
            runtime.cooldown_until = now + scheduler.rate_limit_cooldown(
                runtime.rate_limit_strikes,
                retry_after=retry_after,
            )
            return

        # Transient failures (5xx / network / stream interruption / other): lower
        # the weight and only pause once it reaches the floor.
        runtime.weight = scheduler.decrease_weight(
            runtime.weight, scheduler.WEIGHT_TRANSIENT_FAILURE_STEP
        )
        if scheduler.should_cooldown(runtime.weight):
            runtime.cooldown_until = now + DEFAULT_TRANSIENT_COOLDOWN_SECONDS

    def account_infos(self) -> List[Dict[str, Any]]:
        now = time.time()
        for runtime in self._runtimes:
            self._apply_cooldown_recovery(runtime, now)
        return [_account_info(runtime) for runtime in self._runtimes]

    def summary(self) -> Dict[str, int]:
        infos = self.account_infos()
        return {
            "total": len(infos),
            "enabled": sum(1 for item in infos if item["enabled"]),
            "healthy": sum(1 for item in infos if item["token_healthy"]),
            "unhealthy": sum(1 for item in infos if not item["token_healthy"]),
            "in_flight": sum(int(item["in_flight"]) for item in infos),
        }

    def _unhealthy_runtimes_due_for_probe(self, now: float) -> List[KimiAccountRuntime]:
        interval = max(float(getattr(Config, "KIMI_AUTO_PROBE_INTERVAL", 0.0)), 0.0)
        if interval <= 0:
            return []
        return [
            runtime
            for runtime in self._runtimes
            if runtime.enabled
            and runtime.unhealthy_error
            and scheduler.should_auto_probe(runtime.last_probe_at, now, interval=interval)
        ]

    async def auto_probe_unhealthy(self) -> List[Dict[str, str]]:
        """Probe auth-failed accounts that have been quiet long enough.

        For each due account a token refresh is attempted; success clears the
        unhealthy flag and returns the account to rotation. Returns a list of
        ``{"id", "name", "result"}`` records for observability/logging.
        """
        now = time.time()
        due = self._unhealthy_runtimes_due_for_probe(now)
        results: List[Dict[str, str]] = []
        for runtime in due:
            runtime.last_probe_at = now
            state = runtime.token_manager.get_state()
            if state.refresh_token is None:
                # Access-token-only accounts cannot self-heal; skip silently.
                results.append(
                    {"id": runtime.account_id, "name": runtime.account_name, "result": "skipped"}
                )
                continue
            try:
                await runtime.token_manager.invalidate_and_retry()
                self.record_success(runtime)
                results.append(
                    {"id": runtime.account_id, "name": runtime.account_name, "result": "recovered"}
                )
            except Exception as exc:  # noqa: BLE001 - probe must never raise
                self.record_failure(runtime, exc)
                results.append(
                    {"id": runtime.account_id, "name": runtime.account_name, "result": "failed"}
                )
        return results

    async def close(self) -> None:
        for runtime in self._runtimes:
            await runtime.close()


def _account_info(runtime: KimiAccountRuntime) -> Dict[str, Any]:
    state = runtime.token_manager.get_state()
    now = time.time()
    healthy = runtime.enabled and not runtime.unhealthy_error

    if runtime.is_cooling_down(now):
        remaining = max(runtime.cooldown_until - now, 0.0)
        token_status = f"冷却中 {int(remaining)}s"
        healthy = False
    elif runtime.unhealthy_error:
        token_status = "异常，需刷新或验证"
        healthy = False
    elif not runtime.enabled:
        token_status = "已禁用"
        healthy = False
    elif runtime.is_quota_exhausted(now):
        token_status = "已达用量上限"
    elif state.expires_at > 0:
        remaining = state.expires_at - now
        healthy = healthy and remaining > 300
        if remaining > 86400:
            token_status = f"{int(remaining // 86400)}天后过期"
        elif remaining > 3600:
            token_status = f"{int(remaining // 3600)}小时后过期"
        elif remaining > 0:
            token_status = f"{int(remaining // 60)}分钟后过期"
        else:
            token_status = "已过期"
            healthy = False
    else:
        token_status = "有效"

    token_expires = "未知"
    if state.expires_at > 0:
        from ..dashboard.view_models import fmt_time

        token_expires = fmt_time(state.expires_at)

    return {
        "id": runtime.account_id,
        "name": runtime.account_name,
        "enabled": runtime.enabled,
        "token_type": token_type_label(state.token_type),
        "token_expires": token_expires,
        "token_preview": token_preview(runtime.account.raw_token),
        "token_healthy": healthy,
        "token_status": token_status,
        "in_flight": runtime.in_flight,
        "max_concurrency": runtime.account.max_concurrency,
        "min_interval_seconds": runtime.account.min_interval_seconds,
        "weight": round(runtime.weight, 1),
        "call_count": runtime.call_count,
        "rate_limit_strikes": runtime.rate_limit_strikes,
        "quota_exhausted": runtime.is_quota_exhausted(now),
    }


_pool: Optional[KimiAccountPool] = None


def init_account_pool(
    accounts: Optional[List[KimiAccountConfig]] = None,
    *,
    base_url: Optional[str] = None,
) -> KimiAccountPool:
    global _pool
    _pool = KimiAccountPool(
        load_kimi_accounts() if accounts is None else accounts,
        base_url=base_url,
    )
    return _pool


async def replace_account_pool(
    accounts: Optional[List[KimiAccountConfig]] = None,
    *,
    base_url: Optional[str] = None,
) -> KimiAccountPool:
    global _pool
    old_pool = _pool
    _pool = KimiAccountPool(
        load_kimi_accounts() if accounts is None else accounts,
        base_url=base_url,
    )
    if old_pool is not None:
        await old_pool.close()
    return _pool


async def close_account_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_account_pool(*, required: bool = True) -> Optional[KimiAccountPool]:
    if _pool is None and required:
        raise RuntimeError("Kimi account pool is not initialized")
    return _pool


_auto_probe_task: "Optional[asyncio.Task[None]]" = None


async def _auto_probe_loop(interval: float) -> None:
    # Wake up frequently enough to honour the configured probe interval without
    # busy-looping; each runtime is only actually probed once per `interval`.
    tick = max(min(interval, 60.0), 5.0)
    while True:
        try:
            await asyncio.sleep(tick)
            pool = get_account_pool(required=False)
            if pool is not None:
                await pool.auto_probe_unhealthy()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - background task must stay alive
            continue


def start_auto_probe() -> None:
    """Start the background auto-probe loop if enabled and not already running."""
    global _auto_probe_task
    interval = max(float(getattr(Config, "KIMI_AUTO_PROBE_INTERVAL", 0.0)), 0.0)
    if interval <= 0:
        return
    if _auto_probe_task is not None and not _auto_probe_task.done():
        return
    _auto_probe_task = asyncio.create_task(_auto_probe_loop(interval))


async def stop_auto_probe() -> None:
    global _auto_probe_task
    if _auto_probe_task is None:
        return
    _auto_probe_task.cancel()
    try:
        await _auto_probe_task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    _auto_probe_task = None
