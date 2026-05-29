import json
import os
import stat
import base64
import time

import httpx
import pytest

from app.config import Config
from app.kimi.protocol import KimiAPIError


def test_legacy_token_file_migrates_to_private_account_pool(tmp_data_dir, config_override):
    from app.core.kimi_account_store import load_kimi_accounts
    from app.core.kimi_token_store import save_kimi_token

    config_override(KIMI_TOKEN="env-token")
    save_kimi_token("saved-refresh-token")

    accounts = load_kimi_accounts()

    assert len(accounts) == 1
    assert accounts[0].name == "Kimi 1"
    assert accounts[0].raw_token == "saved-refresh-token"
    assert accounts[0].enabled is True
    assert accounts[0].max_concurrency == Config.KIMI_MAX_CONCURRENCY
    assert accounts[0].min_interval_seconds == Config.KIMI_MIN_REQUEST_INTERVAL
    assert accounts[0].device_id.isdigit()

    pool_file = tmp_data_dir / "kimi_accounts.json"
    mode = stat.S_IMODE(os.stat(pool_file).st_mode)
    assert mode == 0o600
    data = json.loads(pool_file.read_text())
    assert data["accounts"][0]["raw_token"] == "saved-refresh-token"


def test_env_token_imports_when_no_saved_account_pool(tmp_data_dir, config_override):
    from app.core.kimi_account_store import load_kimi_accounts

    config_override(KIMI_TOKEN="env-refresh-token")

    accounts = load_kimi_accounts()

    assert len(accounts) == 1
    assert accounts[0].name == "Kimi 1"
    assert accounts[0].raw_token == "env-refresh-token"
    assert (tmp_data_dir / "kimi_accounts.json").exists()


def test_account_access_token_cache_persists_in_private_account_file(
    tmp_data_dir,
    config_override,
):
    from app.core.kimi_account_store import (
        load_kimi_accounts,
        new_kimi_account,
        save_kimi_accounts,
        update_kimi_account_access_cache,
    )

    account = new_kimi_account(
        "refresh-token",
        name="Cached",
        now=1,
    )
    save_kimi_accounts([account])

    cached_access = _jwt_access_token()
    assert update_kimi_account_access_cache(
        account.id,
        cached_access,
        int(time.time()) + 3600,
        expected_raw_token="refresh-token",
    ) is True

    accounts = load_kimi_accounts()
    assert accounts[0].cached_access_token == cached_access
    assert accounts[0].cached_access_expires_at > time.time()
    assert accounts[0].cached_access_updated_at > 0

    pool_file = tmp_data_dir / "kimi_accounts.json"
    mode = stat.S_IMODE(os.stat(pool_file).st_mode)
    assert mode == 0o600


def _b64_json(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _jwt_access_token() -> str:
    return ".".join([
        _b64_json({"alg": "none", "typ": "JWT"}),
        _b64_json({
            "app_id": "kimi",
            "typ": "access",
            "exp": int(time.time()) + 30 * 24 * 60 * 60,
        }),
        "signature",
    ])


def test_dashboard_stats_reports_unconfigured_when_account_pool_is_empty(
    token_manager_store,
):
    from app.core.kimi_account_pool import init_account_pool
    from app.core.token_manager import TokenManager
    from app.dashboard.view_models import dashboard_stats, token_info

    token_manager_store.set(TokenManager(_jwt_access_token()))
    init_account_pool([])

    info = token_info()
    stats = dashboard_stats()

    assert info["token_status"] == "未配置"
    assert info["token_type"] == "未配置"
    assert info["token_healthy"] is False
    assert stats["account_total"] == 0
    assert stats["token_status"] == "未配置"
    assert stats["token_healthy"] is False


def test_initialize_runtime_respects_empty_saved_account_pool(
    tmp_data_dir,
    config_override,
    token_manager_store,
):
    from app.bootstrap import initialize_runtime
    from app.core.kimi_account_pool import get_account_pool
    from app.core.kimi_account_store import save_kimi_accounts
    from app.core.kimi_token_store import save_kimi_token
    from app.core.token_manager import get_token_manager

    config_override(KIMI_TOKEN="")
    save_kimi_accounts([])
    save_kimi_token(_jwt_access_token())

    initialize_runtime()

    pool = get_account_pool(required=False)
    assert pool is not None
    assert pool.account_count() == 0
    with pytest.raises(RuntimeError):
        get_token_manager()


@pytest.mark.asyncio
async def test_client_treats_empty_account_pool_as_unconfigured(
    token_manager_store,
):
    from app.core.kimi_account_pool import init_account_pool
    from app.core.token_manager import TokenManager
    from app.kimi import KimiAPIError
    from app.kimi.client import Kimi2API

    token_manager_store.set(TokenManager(_jwt_access_token()))
    init_account_pool([])

    client = Kimi2API()
    with pytest.raises(KimiAPIError, match="Kimi token is not configured"):
        async with client._acquire_runtime():
            pass


@pytest.mark.asyncio
async def test_pool_uses_all_accounts_and_bounds_call_gap(tmp_data_dir):
    from app.core.account_scheduler import MAX_CALL_GAP
    from app.core.kimi_account_pool import KimiAccountPool
    from app.core.kimi_account_store import KimiAccountConfig

    accounts = [
        KimiAccountConfig(
            id="acc-a",
            name="A",
            raw_token="token-a",
            enabled=True,
            max_concurrency=1,
            min_interval_seconds=0,
            device_id="1111111111111111111",
            created_at=1,
            updated_at=1,
        ),
        KimiAccountConfig(
            id="acc-b",
            name="B",
            raw_token="token-b",
            enabled=True,
            max_concurrency=1,
            min_interval_seconds=0,
            device_id="2222222222222222222",
            created_at=1,
            updated_at=1,
        ),
    ]
    pool = KimiAccountPool(accounts, base_url="https://kimi.example.test")

    try:
        # max_concurrency=1 forces two concurrent acquisitions onto distinct accounts.
        async with pool.acquire() as first:
            async with pool.acquire() as second:
                assert {first.account_id, second.account_id} == {"acc-a", "acc-b"}

        # Selection is random (not strict round-robin), but over many sequential
        # calls both accounts get used and the call-count gap stays bounded.
        for _ in range(200):
            async with pool.acquire():
                pass

        counts = {info["id"]: info["call_count"] for info in pool.account_infos()}
        assert all(count > 0 for count in counts.values())
        assert abs(counts["acc-a"] - counts["acc-b"]) <= MAX_CALL_GAP
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_pool_transient_failures_lower_weight_until_cooldown(tmp_data_dir):
    from app.core import account_scheduler as scheduler
    from app.core.kimi_account_pool import KimiAccountPool
    from app.core.kimi_account_store import KimiAccountConfig

    account = KimiAccountConfig(
        id="acc-weight",
        name="Weight",
        raw_token="token-a",
        enabled=True,
        max_concurrency=1,
        min_interval_seconds=0,
        device_id="1111111111111111111",
        created_at=1,
        updated_at=1,
    )
    pool = KimiAccountPool([account], base_url="https://kimi.example.test")
    runtime = pool._runtimes[0]

    try:
        assert runtime.weight == scheduler.WEIGHT_INITIAL

        # One transient failure lowers the weight but does not pause the account.
        async with pool.acquire() as acquired:
            pool.record_failure(
                acquired,
                KimiAPIError("network", upstream_error_type="network_error"),
            )
        assert runtime.weight == scheduler.WEIGHT_INITIAL - scheduler.WEIGHT_TRANSIENT_FAILURE_STEP
        assert not runtime.is_cooling_down()

        # Keep failing until the weight hits the floor and the account is paused.
        failures = 1
        while not runtime.is_cooling_down() and failures < 20:
            async with pool.acquire(require_selectable=False) as acquired:
                pool.record_failure(
                    acquired,
                    KimiAPIError("network", upstream_error_type="network_error"),
                )
            failures += 1

        assert runtime.is_cooling_down()
        assert runtime.weight <= scheduler.WEIGHT_COOLDOWN_THRESHOLD
        # 100 -> 80 -> 60 -> 40 -> 20 == 4 transient failures.
        assert failures == 4
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_pool_restores_partial_weight_after_cooldown(tmp_data_dir):
    from app.core import account_scheduler as scheduler
    from app.core.kimi_account_pool import KimiAccountPool
    from app.core.kimi_account_store import KimiAccountConfig

    account = KimiAccountConfig(
        id="acc-recover",
        name="Recover",
        raw_token="token-a",
        enabled=True,
        max_concurrency=1,
        min_interval_seconds=0,
        device_id="1111111111111111111",
        created_at=1,
        updated_at=1,
    )
    pool = KimiAccountPool([account], base_url="https://kimi.example.test")
    runtime = pool._runtimes[0]

    try:
        for _ in range(4):
            async with pool.acquire(require_selectable=False) as acquired:
                pool.record_failure(
                    acquired,
                    KimiAPIError("network", upstream_error_type="network_error"),
                )

        assert runtime.is_cooling_down()
        assert runtime.weight == scheduler.WEIGHT_COOLDOWN_THRESHOLD

        # Simulate the cooldown window elapsing.
        runtime.cooldown_until = time.time() - 1
        infos = pool.account_infos()

        assert runtime.cooldown_until == 0.0
        assert runtime.weight == scheduler.WEIGHT_RECOVERY_VALUE
        assert infos[0]["token_healthy"] is True
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_pool_success_increases_weight_capped(tmp_data_dir):
    from app.core import account_scheduler as scheduler
    from app.core.kimi_account_pool import KimiAccountPool
    from app.core.kimi_account_store import KimiAccountConfig

    account = KimiAccountConfig(
        id="acc-success",
        name="Success",
        raw_token="token-a",
        enabled=True,
        max_concurrency=1,
        min_interval_seconds=0,
        device_id="1111111111111111111",
        created_at=1,
        updated_at=1,
    )
    pool = KimiAccountPool([account], base_url="https://kimi.example.test")
    runtime = pool._runtimes[0]

    try:
        runtime.weight = 50.0
        async with pool.acquire() as acquired:
            pool.record_success(acquired)
        assert runtime.weight == 50.0 + scheduler.WEIGHT_SUCCESS_STEP

        runtime.weight = scheduler.WEIGHT_MAX
        pool.record_success(runtime)
        assert runtime.weight == scheduler.WEIGHT_MAX
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_pool_persists_access_token_cache_after_refresh(
    tmp_data_dir,
    monkeypatch,
):
    from app.core.kimi_account_pool import KimiAccountPool
    from app.core.kimi_account_store import (
        load_kimi_accounts,
        new_kimi_account,
        save_kimi_accounts,
    )

    refreshed_access = _jwt_access_token()
    refresh_calls = []

    class RefreshTransport:
        def __init__(self, *, base_url=None, **_kwargs):
            self.base_url = (base_url or "https://kimi.example.test").rstrip("/")

        async def request(self, method, path_or_url, **_kwargs):
            refresh_calls.append((method, path_or_url))
            return httpx.Response(200, json={"access_token": refreshed_access})

        async def close(self):
            return None

    monkeypatch.setattr(
        "app.core.kimi_account_pool.KimiTransport",
        RefreshTransport,
    )
    account = new_kimi_account(
        "refresh-token",
        name="Cached",
        now=1,
    )
    save_kimi_accounts([account])
    pool = KimiAccountPool(load_kimi_accounts(), base_url="https://kimi.example.test")

    try:
        async with pool.acquire(account_id=account.id) as runtime:
            token = await runtime.token_manager.get_access_token()
    finally:
        await pool.close()

    assert token == refreshed_access
    assert refresh_calls == [("GET", "/api/auth/token/refresh")]
    cached = load_kimi_accounts()[0]
    assert cached.cached_access_token == refreshed_access
    assert cached.cached_access_expires_at == pytest.approx(
        runtime.token_manager.get_state().expires_at,
    )


@pytest.mark.asyncio
async def test_pool_cools_down_failed_account_and_reports_no_available(tmp_data_dir):
    from app.core.kimi_account_pool import KimiAccountPool
    from app.core.kimi_account_store import KimiAccountConfig

    account = KimiAccountConfig(
        id="acc-rate-limited",
        name="Rate Limited",
        raw_token="token-a",
        enabled=True,
        max_concurrency=1,
        min_interval_seconds=0,
        device_id="1111111111111111111",
        created_at=1,
        updated_at=1,
    )
    pool = KimiAccountPool([account], base_url="https://kimi.example.test")

    try:
        async with pool.acquire() as runtime:
            pool.record_failure(
                runtime,
                KimiAPIError(
                    "rate limited",
                    upstream_status_code=429,
                    upstream_error_type="rate_limited",
                    retry_after=60,
                ),
            )

        with pytest.raises(KimiAPIError) as exc_info:
            async with pool.acquire():
                pass

        assert "No available Kimi accounts" in str(exc_info.value)
        info = pool.account_infos()[0]
        assert info["token_healthy"] is False
        assert "冷却" in info["token_status"]
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_pool_can_acquire_unavailable_account_for_admin_recovery(tmp_data_dir):
    from app.core.kimi_account_pool import KimiAccountPool
    from app.core.kimi_account_store import KimiAccountConfig

    account = KimiAccountConfig(
        id="acc-unhealthy",
        name="Unhealthy",
        raw_token="token-a",
        enabled=True,
        max_concurrency=1,
        min_interval_seconds=0,
        device_id="1111111111111111111",
        created_at=1,
        updated_at=1,
    )
    pool = KimiAccountPool([account], base_url="https://kimi.example.test")

    try:
        async with pool.acquire() as runtime:
            pool.record_failure(
                runtime,
                KimiAPIError(
                    "refresh failed",
                    upstream_error_type="token_refresh_failed",
                ),
            )

        with pytest.raises(KimiAPIError):
            async with pool.acquire(account_id="acc-unhealthy"):
                pass

        async with pool.acquire(
            account_id="acc-unhealthy",
            require_selectable=False,
        ) as runtime:
            assert runtime.account_id == "acc-unhealthy"
            pool.record_success(runtime)

        assert pool.account_infos()[0]["token_healthy"] is True
    finally:
        await pool.close()


def test_admin_tokens_api_does_not_leak_full_token(
    authenticated_admin_client,
    tmp_data_dir,
):
    session = authenticated_admin_client.get("/admin/api/session")
    csrf = session.json()["csrf_token"]

    created = authenticated_admin_client.post(
        "/admin/api/tokens",
        json={
            "name": "Work",
            "raw_token": "work-refresh-token-secret",
            "max_concurrency": 3,
            "min_interval_seconds": 0.2,
            "enabled": True,
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert created.status_code == 200
    body = created.json()
    assert body["success"] is True
    account = body["account"]
    assert account["name"] == "Work"
    assert account["max_concurrency"] == 3
    assert account["min_interval_seconds"] == 0.2
    assert "work-refresh-token-secret" not in json.dumps(body)
    assert account["token_preview"] == "wor****ret"
    assert account["token_type"] == "refresh token"

    listing = authenticated_admin_client.get("/admin/api/tokens")
    assert listing.status_code == 200
    data = listing.json()
    assert data["summary"]["total"] == 1
    assert data["summary"]["enabled"] == 1
    assert data["accounts"][0]["name"] == "Work"


def test_admin_tokens_can_update_disable_and_delete(authenticated_admin_client):
    session = authenticated_admin_client.get("/admin/api/session")
    csrf = session.json()["csrf_token"]

    created = authenticated_admin_client.post(
        "/admin/api/tokens",
        json={"name": "Temporary", "raw_token": "temp-token"},
        headers={"X-CSRF-Token": csrf},
    ).json()
    account_id = created["account"]["id"]

    updated = authenticated_admin_client.patch(
        f"/admin/api/tokens/{account_id}",
        json={"name": "Disabled", "enabled": False, "max_concurrency": 4},
        headers={"X-CSRF-Token": csrf},
    )

    assert updated.status_code == 200
    assert updated.json()["account"]["name"] == "Disabled"
    assert updated.json()["account"]["enabled"] is False
    assert updated.json()["account"]["max_concurrency"] == 4

    deleted = authenticated_admin_client.delete(
        f"/admin/api/tokens/{account_id}",
        headers={"X-CSRF-Token": csrf},
    )

    assert deleted.status_code == 200
    assert deleted.json()["success"] is True
    assert deleted.json()["summary"]["total"] == 0


def test_admin_refresh_jwt_account_does_not_mark_account_unhealthy(
    authenticated_admin_client,
):
    session = authenticated_admin_client.get("/admin/api/session")
    csrf = session.json()["csrf_token"]

    created = authenticated_admin_client.post(
        "/admin/api/tokens",
        json={"name": "Access Only", "raw_token": _jwt_access_token()},
        headers={"X-CSRF-Token": csrf},
    ).json()
    account_id = created["account"]["id"]

    response = authenticated_admin_client.post(
        f"/admin/api/tokens/{account_id}/refresh",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert "refresh token" in body["error"]
    assert body["account"]["name"] == "Access Only"
    assert body["account"]["token_type"] == "access token"
    assert body["account"]["token_healthy"] is True
    assert body["summary"]["healthy"] == 1

    listing = authenticated_admin_client.get("/admin/api/tokens").json()
    assert listing["accounts"][0]["token_healthy"] is True


def test_admin_validate_marks_rejected_access_token_unhealthy(
    authenticated_admin_client,
    monkeypatch,
):
    class RejectingTransport:
        def __init__(self, *, base_url=None, **_kwargs):
            self.base_url = (base_url or "https://kimi.example.test").rstrip("/")

        async def request(self, method, path_or_url, **_kwargs):
            return httpx.Response(401, json={"error": "invalid token"})

        async def close(self):
            return None

    monkeypatch.setattr(
        "app.core.kimi_account_pool.KimiTransport",
        RejectingTransport,
    )

    session = authenticated_admin_client.get("/admin/api/session")
    csrf = session.json()["csrf_token"]

    created = authenticated_admin_client.post(
        "/admin/api/tokens",
        json={"name": "Expired Upstream", "raw_token": _jwt_access_token()},
        headers={"X-CSRF-Token": csrf},
    ).json()
    account_id = created["account"]["id"]

    response = authenticated_admin_client.get(f"/admin/api/tokens/{account_id}/validate")

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["subscription"]["status_code"] == 401
    assert body["account"]["token_healthy"] is False
    assert body["account"]["token_status"] == "异常，需刷新或验证"

    listing = authenticated_admin_client.get("/admin/api/tokens").json()
    assert listing["summary"]["healthy"] == 0
    assert listing["summary"]["unhealthy"] == 1



@pytest.mark.asyncio
async def test_pool_quota_blocks_account_when_per_minute_cap_reached(
    tmp_data_dir,
    config_override,
):
    from app.core.kimi_account_pool import KimiAccountPool
    from app.core.kimi_account_store import KimiAccountConfig

    config_override(KIMI_MAX_REQUESTS_PER_MINUTE=3)

    account = KimiAccountConfig(
        id="acc-quota",
        name="Quota",
        raw_token="token-a",
        enabled=True,
        max_concurrency=1,
        min_interval_seconds=0,
        device_id="1111111111111111111",
        created_at=1,
        updated_at=1,
    )
    pool = KimiAccountPool([account], base_url="https://kimi.example.test")

    try:
        assert pool._runtimes[0].quota.per_minute == 3
        for _ in range(3):
            async with pool.acquire():
                pass

        with pytest.raises(KimiAPIError) as exc_info:
            async with pool.acquire():
                pass
        assert "No available Kimi accounts" in str(exc_info.value)

        info = pool.account_infos()[0]
        assert info["quota_exhausted"] is True
        assert info["token_status"] == "已达用量上限"
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_pool_rate_limit_cooldown_grows_with_consecutive_hits(tmp_data_dir):
    from app.core import account_scheduler as scheduler
    from app.core.kimi_account_pool import KimiAccountPool
    from app.core.kimi_account_store import KimiAccountConfig

    account = KimiAccountConfig(
        id="acc-429",
        name="RateLimited",
        raw_token="token-a",
        enabled=True,
        max_concurrency=1,
        min_interval_seconds=0,
        device_id="1111111111111111111",
        created_at=1,
        updated_at=1,
    )
    pool = KimiAccountPool([account], base_url="https://kimi.example.test")
    runtime = pool._runtimes[0]

    def hit_429():
        return KimiAPIError(
            "rate limited",
            upstream_status_code=429,
            upstream_error_type="rate_limited",
        )

    try:
        start = time.time()
        async with pool.acquire() as acquired:
            pool.record_failure(acquired, hit_429())
        first = runtime.cooldown_until - start
        assert runtime.rate_limit_strikes == 1
        assert abs(first - scheduler.RATE_LIMIT_BACKOFF_BASE_SECONDS) < 5

        runtime.cooldown_until = 0.0  # pretend the first window elapsed
        start = time.time()
        async with pool.acquire(account_id="acc-429", require_selectable=False) as acquired:
            pool.record_failure(acquired, hit_429())
        second = runtime.cooldown_until - start
        assert runtime.rate_limit_strikes == 2
        assert abs(second - scheduler.RATE_LIMIT_BACKOFF_BASE_SECONDS * 2) < 5

        # A success clears the strike counter.
        runtime.cooldown_until = 0.0
        pool.record_success(runtime)
        assert runtime.rate_limit_strikes == 0
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_pool_auto_probe_recovers_unhealthy_account(tmp_data_dir, config_override):
    from app.core.kimi_account_pool import KimiAccountPool
    from app.core.kimi_account_store import KimiAccountConfig

    config_override(KIMI_AUTO_PROBE_INTERVAL=300)

    account = KimiAccountConfig(
        id="acc-probe",
        name="Probe",
        raw_token="refresh-token",
        enabled=True,
        max_concurrency=1,
        min_interval_seconds=0,
        device_id="1111111111111111111",
        created_at=1,
        updated_at=1,
    )
    pool = KimiAccountPool([account], base_url="https://kimi.example.test")
    runtime = pool._runtimes[0]

    refreshed = {"count": 0}

    async def fake_refresh():
        refreshed["count"] += 1
        return "new-access-token"

    runtime.token_manager.invalidate_and_retry = fake_refresh  # type: ignore[assignment]

    try:
        async with pool.acquire(account_id="acc-probe", require_selectable=False) as acquired:
            pool.record_failure(
                acquired,
                KimiAPIError("unauth", upstream_status_code=401, upstream_error_type="unauthorized"),
            )
        assert runtime.unhealthy_error

        # Not due yet: mark it as just-probed so the quiet window has not elapsed.
        runtime.last_probe_at = time.time()
        assert await pool.auto_probe_unhealthy() == []
        assert refreshed["count"] == 0

        # Once the quiet window has elapsed the probe refreshes and recovers it.
        runtime.last_probe_at = time.time() - 400
        results = await pool.auto_probe_unhealthy()
        assert results and results[0]["result"] == "recovered"
        assert refreshed["count"] == 1
        assert not runtime.unhealthy_error
        assert pool.account_infos()[0]["token_healthy"] is True
    finally:
        await pool.close()
