# Admin AI Settings & Telemetry + Caching Fix — Phase C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the LiteLLM cache actually work (fix the Phase A no-op), then expose admin-editable AI settings with hot-apply and cache/usage telemetry (backend endpoints + `AiSettingsPage`).

**Architecture:** Fix `NativeCache.request_kwargs` to opt in (`cache={"use-cache": True, ...}`) and stop passing cache-control kwargs to the LLM call so only validated payloads are written; add `status()`/`clear()`; add `AiService.apply_settings(row)` (validate-then-assign hot-apply); add `GET/PUT /admin/ai/settings`, usage summary/timeseries, cache status/stats/clear; build the frontend Settings section.

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.0 async, PostgreSQL, `litellm==1.101.0`, `instructor==1.17.0`, `redis==8.1.0`, `diskcache==5.6.3`; React 19 + Mantine + TanStack Query.

**Status:** Phase C of `docs/superpowers/specs/2026-09-16-litellm-instructor-ai-core-design.md` (A merged `bef098d`, B merged `5d4d28f`); complete 2026-09-16 on branch `ai-settings-phase-c`. Execution notes: the health probe initially polluted the entries count, so `_healthy` now clears its `__health__` namespace in a `finally`; `parse_redis_url`'s return shape was left unchanged so Phase A's exact-dict tests stay valid (`rediss://` TLS is derived in `_build`). The UsagePage KPI row from the spec's frontend list was not implemented (no code was specified for it; the `/admin/ai/usage/summary` endpoint it would consume is live). Gates at close: backend 1314 passed, ruff 490/490 (zero new), mypy exit-0; frontend 541 passed + typecheck clean.

## Global Constraints

- Run backend commands from `backend/`; export `DATABASE_URL` from the repo `.env` (local Postgres on port **5434**):
  ```bash
  export DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2- | sed 's#^postgresql://#postgresql+asyncpg://#')"
  ```
  `uv run pytest` needs `TEST_DATABASE_URL` and `DATABASE_URL` unset: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest`.
- Gates each task: `uv run ruff check .` must stay at **490** (zero new), `uv run mypy .` exit 0, `uv run pytest`.
- Frontend commands from `frontend/`: `npm run test`, `npm run typecheck`.
- Verified LiteLLM facts (do not re-derive):
  - Manual cache ops require `cache={"use-cache": True, "namespace": <ns>, "ttl": <s>}`; otherwise `should_use_cache` returns False and the call no-ops.
  - `async_get_cache(**kwargs)` returns exactly the object passed to `async_add_cache(result, **kwargs)`.
  - Cache keys are `"{namespace}:{sha256}"`; `Cache(type="local").cache.cache_dict` is the in-memory dict; `Cache(type="disk").cache.disk_cache` is a `diskcache.Cache` (`iterkeys`, `delete`); `Cache(type="redis").cache.init_async_client()` returns an async redis client (`scan_iter`, `delete`).
  - `Cache(type="redis")` writes directly by default (`redis_flush_size` defaults to `None` — no buffering); do **not** set it to an int, or writes buffer until that many entries.
  - `Cache.ping()` raises on the local backend — health must be a set/get probe, not `ping`.
  - The docs' completion-level `caching=True` (Router `cache_responses`) is *not* used: it would auto-cache raw completions before validation. Validated-only caching uses the manual get/store path with `use-cache`.
  - Redis config: `REDIS_URL` is parsed into host/port/password (+ `ssl` for `rediss://`); discrete `REDIS_HOST`/`REDIS_PORT`/`REDIS_PASSWORD`/`REDIS_SSL` are honored when `REDIS_URL` is unset (the docs' suggested mechanism). `REDIS_URL` wins if both are present.
- `.env` holds only `REDIS_URL` and `AI_CACHE_DIR`; all other AI knobs are DB-backed and admin-editable.
- No secrets in responses: the settings endpoints never return `REDIS_URL`.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/ai/cache_config.py` | edit — opt-in request kwargs, `status()`, `clear()` |
| `app/ai/service.py` | edit — split cache kwargs from the LLM call; `apply_settings(file)`; `cache_status()`, `clear_cache()` |
| `app/ai/usage.py` | edit — `summarize_usage(...)` |
| `app/schemas/ai_admin.py` | edit — `AiSettingsOut`, `AiSettingsUpdate` |
| `app/routes/ai_admin.py` | edit — settings + usage summary/timeseries + cache endpoints |
| `app/config.py`, `.env.example`, `docker-compose.yml` | edit — env wiring + opt-in redis service |
| `frontend/src/features/admin/ai/AiSettingsPage.tsx` | new — cache + router settings UI |
| `frontend/src/features/admin/ai/AiAdminPage.tsx`, `UsagePage.tsx`, `api/*`, i18n | edit — settings tab, KPI row, hooks/types |
| `tests/test_ai_cache.py`, `tests/test_ai_admin_api.py`, `tests/test_ai_settings_api.py`, `frontend/.../*.test.tsx` | tests |

---

### Task 1: Make validated-only caching actually work

**Files:**
- Modify: `app/ai/cache_config.py`, `app/ai/service.py`
- Test: `tests/test_ai_cache.py`, `tests/test_ai_service.py`

**Interfaces:**
- Consumes: `Cache`, `CacheMode`, `LiteLLMCacheType`.
- Produces: `NativeCache.request_kwargs(task_type) -> {"cache": {"use-cache": True, "namespace": str, "ttl": int}}`; `AiService.run_task` passes only `model`/`messages` to the LLM call.

- [ ] **Step 1: Add a real round-trip test (no mock)**

Append to `tests/test_ai_cache.py`:
```python
@pytest.mark.asyncio
async def test_local_round_trip_with_use_cache_flag() -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=60,
        ttl_content_s=60, redis_url=None, disk_dir="/tmp/ai-cache-test",
    )
    kwargs = cache.request_kwargs("title_optimization")
    assert kwargs["cache"]["use-cache"] is True
    request = {"model": "bulk", "messages": [{"role": "user", "content": "hi"}], **kwargs}
    await cache.store({"title": "Hello"}, **request)
    assert await cache.lookup(**request) == {"title": "Hello"}


def test_effective_backend_uses_discrete_redis_vars() -> None:
    cfg = cache_config.CacheSettings(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=1, ttl_content_s=1,
        redis_url=None, disk_dir="/tmp/x", redis_host="redis-host",
    )
    assert cache_config.effective_backend(cfg) == "redis"


def test_redis_params_url_takes_precedence_over_discrete_vars() -> None:
    cfg = cache_config.CacheSettings(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=1, ttl_content_s=1,
        redis_url="rediss://:pw@urlhost:6380/0", disk_dir="/tmp/x",
        redis_host="otherhost",
    )
    assert cache_config.redis_params(cfg) == {
        "host": "urlhost", "port": 6380, "password": "pw", "ssl": True,
    }


@pytest.mark.asyncio
async def test_lookup_miss_returns_none_when_not_stored() -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=60,
        ttl_content_s=60, redis_url=None, disk_dir="/tmp/ai-cache-test",
    )
    kwargs = cache.request_kwargs("title_optimization")
    assert await cache.lookup(
        model="bulk", messages=[{"role": "user", "content": "never"}], **kwargs
    ) is None
```

Append to `tests/test_ai_service.py`:
```python
@pytest.mark.asyncio
async def test_llm_call_does_not_receive_cache_control(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_resolve_template", AsyncMock(
        return_value=ai_service_module.ResolvedTemplate("sys", "user", "v1")
    ))
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))
    completion = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1), model="m"
    )
    instructor_client = MagicMock()
    instructor_client.create_with_completion = AsyncMock(
        return_value=(_FakeModel(value="ok"), completion)
    )
    monkeypatch.setattr(service, "_instructor", lambda: instructor_client)

    await service.run_task("title_optimization", {"title": "t"})
    call_kwargs = instructor_client.create_with_completion.await_args.kwargs
    assert "cache" not in call_kwargs
```

- [ ] **Step 2: Run to verify the failures**

Run: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest tests/test_ai_cache.py tests/test_ai_service.py -q`
Expected: FAIL — `use-cache` missing from `request_kwargs`; `cache` present on the LLM call.

- [ ] **Step 3: Implement**

In `app/ai/cache_config.py`, replace `request_kwargs`:
```python
    def request_kwargs(self, task_type: str) -> dict[str, Any]:
        ttl = (
            self._cfg.ttl_taxonomy_s
            if task_type in TAXONOMY_TASKS
            else self._cfg.ttl_content_s
        )
        return {
            "cache": {
                "use-cache": True,
                "namespace": f"{self._cfg.namespace}:{task_type}",
                "ttl": ttl,
            }
        }
```

Then update the Redis resolution to support both env styles. In `app/ai/cache_config.py`:

```python
@dataclass(frozen=True)
class CacheSettings:
    cache_type: str
    namespace: str
    ttl_taxonomy_s: int
    ttl_content_s: int
    redis_url: str | None
    disk_dir: str
    redis_host: str | None = None
    redis_port: int = 6379
    redis_password: str | None = None
    redis_ssl: bool = False


def effective_backend(cfg: CacheSettings) -> str:
    if cfg.redis_url or cfg.redis_host:
        return "redis"
    return cfg.cache_type if cfg.cache_type in ("local", "disk") else "local"


def redis_params(cfg: CacheSettings) -> dict[str, Any]:
    if cfg.redis_url:
        params = parse_redis_url(cfg.redis_url)
        params["ssl"] = cfg.redis_url.startswith("rediss://")
        return params
    return {
        "host": cfg.redis_host or "localhost",
        "port": cfg.redis_port,
        "password": cfg.redis_password,
        "ssl": cfg.redis_ssl,
    }
```
`NativeCache.__init__` gains `redis_host=None, redis_port=6379, redis_password=None, redis_ssl=False` (stored into `_cfg`), and `_build` uses them instead of a raw `redis_url.startswith(...)`:
```python
            if backend == "redis":
                params = redis_params(self._cfg)
                built = Cache(
                    type=LiteLLMCacheType.REDIS,
                    mode=CacheMode.default_off,
                    host=params["host"],
                    port=params["port"],
                    password=params["password"],
                    ssl=params["ssl"],
                )
```
`load_cache_settings` passes the new Settings fields through; `status()`'s `redis_from_env` becomes `bool(self._cfg.redis_url or self._cfg.redis_host)`.

In `app/config.py`, add the discrete fields to `Settings`:
```python
    redis_host: str | None = None
    redis_port: int = 6379
    redis_password: str | None = None
    redis_ssl: bool = False
```

In `app/ai/service.py` `run_task`, change the call so cache-control kwargs go only to lookup/store:
```python
        response_model = TASK_SPECS[task_type].response_model
        cache_kwargs = self._cache.request_kwargs(task_type)
        cache_request = {"model": TIER_BULK, "messages": messages, **cache_kwargs}

        cached = await self._cache.lookup(**cache_request)
        ...
        try:
            value, completion = await self._instructor().create_with_completion(
                response_model=response_model,
                messages=messages,
                model=TIER_BULK,
                max_retries=cfg.instructor_max_retries,
            )
        ...
        await self._cache.store(value.model_dump(), **cache_request)
```
(Delete the now-unused `cache_kwargs`/`cache_request` passed into `create_with_completion`.)

- [ ] **Step 4: Run to verify it passes**

Run: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest tests/test_ai_cache.py tests/test_ai_service.py -q`
Expected: PASS.

- [ ] **Step 5: Pin the new deps and commit**

Edit `pyproject.toml`: `"redis==8.1.0"`, `"diskcache==5.6.3"`. Add `redis.*`, `diskcache.*` to the existing `litellm` mypy overrides if mypy reports missing stubs.
```bash
git add backend/app/ai/cache_config.py backend/app/ai/service.py backend/tests/test_ai_cache.py backend/tests/test_ai_service.py backend/pyproject.toml backend/uv.lock
git commit -m "fix(ai): opt into litellm cache for validated-only reads/writes"
```

---

### Task 2: Cache status and namespace clear

**Files:**
- Modify: `app/ai/cache_config.py`
- Test: `tests/test_ai_cache.py`

**Interfaces:**
- Produces: `async NativeCache.status() -> dict` (`effective_backend`, `redis_from_env`, `healthy`, `namespace`, `entries`); `async NativeCache.clear(namespace: str | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_status_reports_local_backend_healthy() -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=60,
        ttl_content_s=60, redis_url=None, disk_dir="/tmp/ai-cache-test",
    )
    status = await cache.status()
    assert status["effective_backend"] == "local"
    assert status["redis_from_env"] is False
    assert status["healthy"] is True
    assert status["namespace"] == "gmc-ai"
    assert status["entries"] == 0


@pytest.mark.asyncio
async def test_clear_scoped_to_namespace() -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=60,
        ttl_content_s=60, redis_url=None, disk_dir="/tmp/ai-cache-test",
    )
    title = cache.request_kwargs("title_optimization")
    attrs = cache.request_kwargs("attribute_enrichment")
    await cache.store({"t": 1}, model="bulk", messages=[{"role": "user", "content": "a"}], **title)
    await cache.store({"a": 1}, model="bulk", messages=[{"role": "user", "content": "b"}], **attrs)
    removed = await cache.clear("title_optimization")
    assert removed == 1
    assert await cache.lookup(model="bulk", messages=[{"role": "user", "content": "a"}], **title) is None
    assert await cache.lookup(model="bulk", messages=[{"role": "user", "content": "b"}], **attrs) == {"a": 1}


@pytest.mark.asyncio
async def test_clear_all_namespaces() -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=60,
        ttl_content_s=60, redis_url=None, disk_dir="/tmp/ai-cache-test",
    )
    title = cache.request_kwargs("title_optimization")
    await cache.store({"t": 1}, model="bulk", messages=[{"role": "user", "content": "a"}], **title)
    assert await cache.clear() == 1
    assert (await cache.status())["entries"] == 0


@pytest.mark.asyncio
async def test_status_unhealthy_when_backend_errors() -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=60,
        ttl_content_s=60, redis_url=None, disk_dir="/tmp/ai-cache-test",
    )

    class Boom:
        cache_dict = {}

        async def async_set_cache(self, *args, **kwargs):
            raise RuntimeError("down")

        async def async_get_cache(self, *args, **kwargs):
            raise RuntimeError("down")

    cache._cache.cache = Boom()  # type: ignore[assignment]
    assert (await cache.status())["healthy"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest tests/test_ai_cache.py -q`
Expected: FAIL — `NativeCache` has no attribute `status`.

- [ ] **Step 3: Implement**

Add to `NativeCache`:
```python
    def _namespace_prefix(self, namespace: str | None) -> str:
        base = self._cfg.namespace
        return f"{base}:{namespace}:" if namespace else f"{base}:"

    async def _healthy(self) -> bool:
        if self._cache is None:
            return False
        control = {"use-cache": True, "namespace": f"{self._cfg.namespace}:__health__", "ttl": 5}
        try:
            await self._cache.async_add_cache(
                {"ok": True}, model="__health__",
                messages=[{"role": "user", "content": "ping"}], cache=control,
            )
            probe = await self._cache.async_get_cache(
                model="__health__",
                messages=[{"role": "user", "content": "ping"}], cache=control,
            )
            return bool(probe)
        except Exception:
            logger.warning("ai cache: health probe failed", exc_info=True)
            return False

    def _entries(self) -> int | None:
        if self._cache is None:
            return None
        backend = self._cache.cache
        try:
            in_memory = getattr(backend, "cache_dict", None)
            if isinstance(in_memory, dict):
                return len(in_memory)
            on_disk = getattr(backend, "disk_cache", None)
            if on_disk is not None:
                return sum(1 for _ in on_disk.iterkeys())
        except Exception:
            logger.warning("ai cache: entry count failed", exc_info=True)
        return None  # redis: an entry count needs a SCAN; reported as unknown

    async def status(self) -> dict[str, Any]:
        return {
            "effective_backend": effective_backend(self._cfg),
            "redis_from_env": bool(self._cfg.redis_url),
            "healthy": await self._healthy(),
            "namespace": self._cfg.namespace,
            "entries": self._entries(),
        }

    async def clear(self, namespace: str | None = None) -> int:
        if self._cache is None:
            return 0
        prefix = self._namespace_prefix(namespace)
        backend = self._cache.cache
        try:
            in_memory = getattr(backend, "cache_dict", None)
            if isinstance(in_memory, dict):
                keys = [k for k in list(in_memory) if str(k).startswith(prefix)]
                for key in keys:
                    in_memory.pop(key, None)
                ttl_dict = getattr(backend, "ttl_dict", None)
                if isinstance(ttl_dict, dict):
                    for key in keys:
                        ttl_dict.pop(key, None)
                return len(keys)
            on_disk = getattr(backend, "disk_cache", None)
            if on_disk is not None:
                keys = [k for k in list(on_disk.iterkeys()) if str(k).startswith(prefix)]
                for key in keys:
                    on_disk.delete(key)
                return len(keys)
            client = backend.init_async_client()
            removed = 0
            async for key in client.scan_iter(match=f"{prefix}*"):
                await client.delete(key)
                removed += 1
            return removed
        except Exception:
            logger.warning("ai cache: clear failed", exc_info=True)
            return 0
```

- [ ] **Step 4: Run to verify it passes**

Run: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest tests/test_ai_cache.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/cache_config.py backend/tests/test_ai_cache.py
git commit -m "feat(ai): cache status and namespace-scoped clear"
```

---

### Task 3: Hot-applied AI settings

**Files:**
- Modify: `app/ai/service.py`, `app/schemas/ai_admin.py`, `app/routes/ai_admin.py`
- Test: `tests/test_ai_settings_api.py` (new)

**Interfaces:**
- Consumes: `GlobalSetting` AI columns, `NativeCache`, `build_router`, `build_instructor`, `RouterSettings`.
- Produces: `AiService.apply_settings(row: GlobalSetting) -> None` (builds cache+router, raises on failure, assigns only on success); `async AiService.cache_status() -> dict`; `async AiService.clear_cache(namespace) -> int`; `AiSettingsOut`, `AiSettingsUpdate`; `GET/PUT /admin/ai/settings`.

- [ ] **Step 1: Write the failing API test**

```python
# backend/tests/test_ai_settings_api.py
"""AI settings endpoints: seed, persist, hot-apply, validation, RBAC."""
from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.global_setting import GlobalSetting
from app.models.user import User
from app.persistence.users import seed_initial_user


@pytest_asyncio.fixture
async def settings_app(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await session.execute(delete(GlobalSetting))
        await session.execute(delete(User))
    await seed_initial_user(None, factory)
    settings = Settings(
        session_secret="x" * 32, initial_username="operator",
        initial_password="admin-pass", session_idle_minutes=30,
        session_absolute_hours=12,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    async with app.router.lifespan_context(app):
        yield app, factory
    await engine.dispose()


@pytest_asyncio.fixture
async def admin_http(settings_app):
    app, _ = settings_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/auth/login", json={"username": "operator", "password": "admin-pass"})
        yield client


DEFAULTS = {
    "ai_cache_type": "local",
    "ai_cache_namespace": "gmc-ai",
    "ai_cache_ttl_taxonomy_s": 2592000,
    "ai_cache_ttl_content_s": 604800,
    "ai_router_timeout_s": 30,
    "ai_router_num_retries": 2,
    "ai_router_allowed_fails": 3,
    "ai_router_cooldown_s": 30,
    "ai_instructor_max_retries": 2,
    "ai_usage_retention_days": 90,
}


@pytest.mark.asyncio
async def test_get_ai_settings_seeds_defaults(admin_http) -> None:
    response = await admin_http.get("/admin/ai/settings")
    assert response.status_code == 200
    body = response.json()
    for key, value in DEFAULTS.items():
        assert body[key] == value
    assert body["redis_from_env"] is False
    assert body["effective_cache_backend"] == "local"


@pytest.mark.asyncio
async def test_put_ai_settings_persists_and_hot_applies(admin_http, settings_app) -> None:
    app, _ = settings_app
    response = await admin_http.put("/admin/ai/settings", json={
        **DEFAULTS, "ai_cache_namespace": "tenant-x", "ai_router_num_retries": 5,
    })
    assert response.status_code == 200
    assert response.json()["ai_cache_namespace"] == "tenant-x"

    follow = await admin_http.get("/admin/ai/settings")
    assert follow.json()["ai_router_num_retries"] == 5

    service = app.state.ai_service
    assert service._cache is not None
    assert service._router_settings is not None
    assert service._router_settings.num_retries == 5


@pytest.mark.asyncio
async def test_put_ai_settings_rejects_invalid_value(admin_http) -> None:
    response = await admin_http.put("/admin/ai/settings", json={
        **DEFAULTS, "ai_router_timeout_s": 0,
    })
    assert response.status_code == 422
```

> Rollback-on-rebuild-failure is covered deterministically by the `apply_settings` unit test added in Step 3, not through the API (forcing a real backend build failure over HTTP is fragile).

- [ ] **Step 2: Run to verify it fails**

Run: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest tests/test_ai_settings_api.py -q`
Expected: FAIL — 404 on `/admin/ai/settings`.

- [ ] **Step 3: Implement**

`app/schemas/ai_admin.py` — add:
```python
class AiSettingsOut(BaseModel):
    ai_cache_type: Literal["local", "disk"]
    ai_cache_namespace: str
    ai_cache_ttl_taxonomy_s: int
    ai_cache_ttl_content_s: int
    ai_router_timeout_s: int
    ai_router_num_retries: int
    ai_router_allowed_fails: int
    ai_router_cooldown_s: int
    ai_instructor_max_retries: int
    ai_usage_retention_days: int
    redis_from_env: bool
    effective_cache_backend: str


class AiSettingsUpdate(BaseModel):
    ai_cache_type: Literal["local", "disk"] = "local"
    ai_cache_namespace: str = Field(min_length=1, max_length=64)
    ai_cache_ttl_taxonomy_s: int = Field(ge=1)
    ai_cache_ttl_content_s: int = Field(ge=1)
    ai_router_timeout_s: int = Field(ge=1, le=600)
    ai_router_num_retries: int = Field(ge=0, le=10)
    ai_router_allowed_fails: int = Field(ge=0, le=100)
    ai_router_cooldown_s: int = Field(ge=0, le=3600)
    ai_instructor_max_retries: int = Field(ge=0, le=10)
    ai_usage_retention_days: int = Field(ge=1)
```

`app/ai/service.py` — add to `AiService`:
```python
    async def apply_settings(self, row: GlobalSetting) -> None:
        cfg = RouterSettings(
            timeout_s=row.ai_router_timeout_s,
            num_retries=row.ai_router_num_retries,
            allowed_fails=row.ai_router_allowed_fails,
            cooldown_s=row.ai_router_cooldown_s,
            instructor_max_retries=row.ai_instructor_max_retries,
        )
        rows = await self._load_deployments()
        router = build_router(rows, cfg)
        instructor_client = build_instructor(router)
        cache = NativeCache(
            cache_type=row.ai_cache_type,
            namespace=row.ai_cache_namespace,
            ttl_taxonomy_s=row.ai_cache_ttl_taxonomy_s,
            ttl_content_s=row.ai_cache_ttl_content_s,
            redis_url=self._settings.redis_url,
            disk_dir=self._settings.ai_cache_dir,
            redis_host=self._settings.redis_host,
            redis_port=self._settings.redis_port,
            redis_password=self._settings.redis_password,
            redis_ssl=self._settings.redis_ssl,
        )
        if not cache.enabled:
            raise ValueError("configured cache backend is unavailable")
        self._router = router
        self._instructor_client = instructor_client
        self._router_settings = cfg
        self._cache = cache

    async def cache_status(self) -> dict[str, Any]:
        await self._ensure_cache()
        return await self._cache.status()

    async def clear_cache(self, namespace: str | None = None) -> int:
        await self._ensure_cache()
        return await self._cache.clear(namespace)
```
Add `from ..models.global_setting import GlobalSetting` to the imports.

`app/routes/ai_admin.py` — add imports (`AiSettingsOut`, `AiSettingsUpdate`, `GlobalSetting`, `effective_backend`/`CacheSettings` not needed), a seed helper, and the endpoints:
```python
def _seed_settings(*, namespace: str = "gmc-ai") -> GlobalSetting:
    return GlobalSetting(
        id=1,
        staging_removal_retention_days=90,
        staging_history_retention_days=90,
        ingestion_run_retention_days=90,
        ai_usage_retention_days=90,
        ai_cache_retention_days=90,
        ai_cache_type="local",
        ai_cache_namespace=namespace,
        ai_cache_ttl_taxonomy_s=2592000,
        ai_cache_ttl_content_s=604800,
        ai_router_timeout_s=30,
        ai_router_num_retries=2,
        ai_router_allowed_fails=3,
        ai_router_cooldown_s=30,
        ai_instructor_max_retries=2,
    )


def _settings_out(row: GlobalSetting, redis_from_env: bool) -> AiSettingsOut:
    backend = "redis" if redis_from_env else row.ai_cache_type
    return AiSettingsOut(
        ai_cache_type=row.ai_cache_type,
        ai_cache_namespace=row.ai_cache_namespace,
        ai_cache_ttl_taxonomy_s=row.ai_cache_ttl_taxonomy_s,
        ai_cache_ttl_content_s=row.ai_cache_ttl_content_s,
        ai_router_timeout_s=row.ai_router_timeout_s,
        ai_router_num_retries=row.ai_router_num_retries,
        ai_router_allowed_fails=row.ai_router_allowed_fails,
        ai_router_cooldown_s=row.ai_router_cooldown_s,
        ai_instructor_max_retries=row.ai_instructor_max_retries,
        ai_usage_retention_days=row.ai_usage_retention_days,
        redis_from_env=redis_from_env,
        effective_cache_backend=backend,
    )


@router.get("/admin/ai/settings", response_model=AiSettingsOut)
async def get_ai_settings(
    request: Request,
    _admin: AdminUser,
    db_session: DbSession,
) -> AiSettingsOut:
    session = _require_db(db_session)
    async with session.begin():
        row = await session.get(GlobalSetting, 1)
        if row is None:
            row = _seed_settings()
            session.add(row)
    return _settings_out(row, bool(get_settings().redis_url))


@router.put("/admin/ai/settings", response_model=AiSettingsOut)
async def put_ai_settings(
    payload: AiSettingsUpdate,
    request: Request,
    _admin: AdminUser,
    db_session: DbSession,
) -> AiSettingsOut:
    session = _require_db(db_session)
    service = getattr(request.app.state, "ai_service", None)
    async with session.begin():
        row = await session.get(GlobalSetting, 1)
        if row is None:
            row = _seed_settings()
            session.add(row)
        for field, value in payload.model_dump().items():
            setattr(row, field, value)
        await session.flush()
        if service is not None:
            try:
                await service.apply_settings(row)
            except Exception as exc:  # rollback keeps the previous config active
                raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _settings_out(row, bool(get_settings().redis_url))
```
Add `from ..config import get_settings` and `from ..models.global_setting import GlobalSetting` to `routes/ai_admin.py` imports.

Add the `apply_settings` failure unit test to `tests/test_ai_service.py`:
```python
@pytest.mark.asyncio
async def test_apply_settings_keeps_previous_on_cache_failure(service, monkeypatch) -> None:
    from types import SimpleNamespace

    from app.ai import service as svc_mod

    before = service._cache
    monkeypatch.setattr(svc_mod, "build_router", lambda rows, cfg: object())
    monkeypatch.setattr(svc_mod, "build_instructor", lambda router: object())
    monkeypatch.setattr(
        svc_mod, "NativeCache",
        lambda **kwargs: SimpleNamespace(enabled=False),
    )
    row = SimpleNamespace(
        ai_router_timeout_s=30, ai_router_num_retries=2, ai_router_allowed_fails=3,
        ai_router_cooldown_s=30, ai_instructor_max_retries=2, ai_cache_type="disk",
        ai_cache_namespace="x", ai_cache_ttl_taxonomy_s=1, ai_cache_ttl_content_s=1,
    )
    with pytest.raises(ValueError):
        await service.apply_settings(row)
    assert service._cache is before
```

- [ ] **Step 4: Run to verify it passes**

Run: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest tests/test_ai_settings_api.py tests/test_ai_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/service.py backend/app/schemas/ai_admin.py backend/app/routes/ai_admin.py backend/tests/test_ai_settings_api.py backend/tests/test_ai_service.py
git commit -m "feat(ai): admin-editable hot-applied AI settings"
```

---

### Task 4: Usage and cache telemetry endpoints

**Files:**
- Modify: `app/ai/usage.py`, `app/routes/ai_admin.py`, `app/config.py`, `.env.example`, `docker-compose.yml`
- Test: `tests/test_ai_admin_api.py`, `tests/test_ai_cache_usage.py`

**Interfaces:**
- Produces: `summarize_usage(session, *, client_id=None, feed_source_id=None, task_type=None, from_dt=None, to_dt=None) -> dict`; `GET /admin/ai/usage/summary`, `GET /admin/ai/usage/timeseries`, `GET /admin/ai/cache`, `GET /admin/ai/cache/stats`, `POST /admin/ai/cache/clear`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ai_cache_usage.py`:
```python
@pytest.mark.asyncio
async def test_summarize_usage_totals_and_savings(session):
    from app.ai.usage import summarize_usage

    async with session.begin():
        session.add(AiUsageLog(
            client_id=None, feed_source_id=None, task_type="title_optimization",
            provider_config_id=None, model="bulk", provider="openai", tier="bulk",
            fallback_used=False, cache_hit=False, prompt_tokens=100,
            completion_tokens=20, cost_usd=Decimal("0.0010"), latency_ms=10, error_code=None,
        ))
        session.add(AiUsageLog(
            client_id=None, feed_source_id=None, task_type="title_optimization",
            provider_config_id=None, model="bulk", provider="openai", tier="bulk",
            fallback_used=False, cache_hit=True, prompt_tokens=100,
            completion_tokens=20, cost_usd=Decimal("0.0010"), latency_ms=0, error_code=None,
        ))
    summary = await summarize_usage(session)
    assert summary["calls"] == 2
    assert summary["cache_hits"] == 1
    assert summary["hit_ratio"] == 0.5
    assert summary["cost_saved_usd"] == Decimal("0.0010")
    assert summary["saved_prompt_tokens"] == 100
```
(Add `from decimal import Decimal` and `from app.models.ai import AiUsageLog` if not already imported in that test module.)

- [ ] **Step 2: Run to verify it fails**

Run: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest tests/test_ai_cache_usage.py -q`
Expected: FAIL — no `summarize_usage`.

- [ ] **Step 3: Implement `summarize_usage` in `app/ai/usage.py`**

```python
async def summarize_usage(
    session: AsyncSession,
    *,
    client_id: int | None = None,
    feed_source_id: int | None = None,
    task_type: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
) -> dict[str, Any]:
    statement = select(
        func.count().label("calls"),
        func.coalesce(func.sum(case((AiUsageLog.cache_hit.is_(True), 1), else_=0)), 0).label("cache_hits"),
        func.coalesce(func.sum(AiUsageLog.prompt_tokens), 0).label("prompt_tokens"),
        func.coalesce(func.sum(AiUsageLog.completion_tokens), 0).label("completion_tokens"),
        func.coalesce(func.sum(AiUsageLog.cost_usd), 0).label("cost_usd"),
        func.coalesce(
            func.sum(case((AiUsageLog.cache_hit.is_(True), AiUsageLog.prompt_tokens), else_=0)), 0
        ).label("saved_prompt_tokens"),
        func.coalesce(
            func.sum(case((AiUsageLog.cache_hit.is_(True), AiUsageLog.completion_tokens), else_=0)), 0
        ).label("saved_completion_tokens"),
        func.coalesce(
            func.sum(case((AiUsageLog.cache_hit.is_(True), AiUsageLog.cost_usd), else_=0)), 0
        ).label("cost_saved_usd"),
    )
    if client_id is not None:
        statement = statement.where(AiUsageLog.client_id == client_id)
    if feed_source_id is not None:
        statement = statement.where(AiUsageLog.feed_source_id == feed_source_id)
    if task_type is not None:
        statement = statement.where(AiUsageLog.task_type == task_type)
    if from_dt is not None:
        statement = statement.where(AiUsageLog.created_at >= from_dt)
    if to_dt is not None:
        statement = statement.where(AiUsageLog.created_at < to_dt)
    row = (await session.execute(statement)).one()._mapping
    result = dict(row)
    calls = result["calls"] or 0
    result["hit_ratio"] = (result["cache_hits"] / calls) if calls else 0.0
    return result
```

In `app/routes/ai_admin.py` add:
```python
@router.get("/admin/ai/usage/summary")
async def usage_summary(
    _admin: AdminUser,
    db_session: DbSession,
    client_id: int | None = None,
    feed_source_id: int | None = None,
    task_type: str | None = None,
    from_dt: UsageFrom = None,
    to_dt: UsageTo = None,
) -> dict[str, Any]:
    session = _require_db(db_session)
    return await summarize_usage(
        session, client_id=client_id, feed_source_id=feed_source_id,
        task_type=task_type, from_dt=from_dt, to_dt=to_dt,
    )


@router.get("/admin/ai/usage/timeseries")
async def usage_timeseries(
    _admin: AdminUser,
    db_session: DbSession,
    from_dt: UsageFrom = None,
    to_dt: UsageTo = None,
) -> dict[str, Any]:
    session = _require_db(db_session)
    rows = await aggregate_usage(session, from_dt=from_dt, to_dt=to_dt, group_by="day")
    return {"rows": rows}


@router.get("/admin/ai/cache")
async def cache_status(request: Request, _admin: AdminUser) -> dict[str, Any]:
    service = _ai_service(request)
    return await service.cache_status()


@router.get("/admin/ai/cache/stats")
async def cache_stats(
    _admin: AdminUser,
    db_session: DbSession,
    from_dt: UsageFrom = None,
    to_dt: UsageTo = None,
) -> dict[str, Any]:
    session = _require_db(db_session)
    return await summarize_usage(session, from_dt=from_dt, to_dt=to_dt)


@router.post("/admin/ai/cache/clear")
async def cache_clear(
    payload: CacheClearRequest,
    request: Request,
    _admin: AdminUser,
) -> dict[str, int]:
    service = _ai_service(request)
    removed = await service.clear_cache(payload.namespace)
    return {"removed": removed}
```
Add `CacheClearRequest` to `schemas/ai_admin.py`:
```python
class CacheClearRequest(BaseModel):
    namespace: str | None = Field(default=None, max_length=100)
```
and import `summarize_usage` alongside `aggregate_usage`.

Root `.env.example` (repo root, not `backend/`) — add:
```
# Optional: enable the redis AI cache backend (leave unset for local/disk).
# Either a single REDIS_URL, or the discrete REDIS_* vars (REDIS_URL wins).
# REDIS_URL=redis://localhost:6379/0
# REDIS_HOST=localhost
# REDIS_PORT=6379
# REDIS_PASSWORD=
# REDIS_SSL=false
AI_CACHE_DIR=
```
`app/config.py` already has `redis_url`/`ai_cache_dir`, so no change is needed there. Root `docker-compose.yml` — add an opt-in service:
```yaml
  redis:
    image: redis:7-alpine
    profiles: ["ai-cache"]
    ports:
      - "6379:6379"
```

Add endpoint tests to `tests/test_ai_admin_api.py`:
```python
@pytest.mark.asyncio
async def test_ai_cache_and_usage_endpoints(admin_http) -> None:
    assert (await admin_http.get("/admin/ai/cache")).status_code == 200
    assert (await admin_http.get("/admin/ai/cache/stats")).status_code == 200
    assert (await admin_http.get("/admin/ai/usage/summary")).status_code == 200
    assert (await admin_http.get("/admin/ai/usage/timeseries")).status_code == 200
    cleared = await admin_http.post("/admin/ai/cache/clear", json={})
    assert cleared.status_code == 200
    assert "removed" in cleared.json()
```

- [ ] **Step 4: Run to verify it passes**

Run: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest tests/test_ai_cache_usage.py tests/test_ai_admin_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/usage.py backend/app/routes/ai_admin.py backend/app/schemas/ai_admin.py backend/tests/test_ai_cache_usage.py backend/tests/test_ai_admin_api.py ../.env.example ../docker-compose.yml
git commit -m "feat(ai): usage summary/timeseries and cache status/stats/clear endpoints"
```

---

### Task 5: Frontend AI settings section

**Files:**
- Create: `frontend/src/features/admin/ai/AiSettingsPage.tsx`, `frontend/src/features/admin/ai/AiSettingsPage.test.tsx`
- Modify: `frontend/src/features/admin/ai/AiAdminPage.tsx`, `frontend/src/features/admin/ai/UsagePage.tsx`, `frontend/src/api/hooks.ts`, `frontend/src/api/types.ts`, `frontend/public/locales/{en,de}/admin.json`

**Interfaces:**
- Consumes: `GET/PUT /admin/ai/settings`, `GET /admin/ai/cache`, `GET /admin/ai/cache/stats`, `POST /admin/ai/cache/clear`, `GET /admin/ai/usage/summary`.
- Produces: `useAiSettings`, `useUpdateAiSettings`, `useAiCacheStatus`, `useAiCacheStats`, `useClearAiCache`, `useAiUsageSummary` hooks; `AiSettings` type; the `settings` tab.

- [ ] **Step 1: Add types and hooks**

`frontend/src/api/types.ts`:
```typescript
export type AiSettings = {
  ai_cache_type: 'local' | 'disk';
  ai_cache_namespace: string;
  ai_cache_ttl_taxonomy_s: number;
  ai_cache_ttl_content_s: number;
  ai_router_timeout_s: number;
  ai_router_num_retries: number;
  ai_router_allowed_fails: number;
  ai_router_cooldown_s: number;
  ai_instructor_max_retries: number;
  ai_usage_retention_days: number;
  redis_from_env: boolean;
  effective_cache_backend: string;
};

export type AiCacheStatus = {
  effective_backend: string;
  redis_from_env: boolean;
  healthy: boolean;
  namespace: string;
  entries: number | null;
};

export type AiUsageSummary = {
  calls: number;
  cache_hits: number;
  hit_ratio: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: string | number;
  saved_prompt_tokens: number;
  saved_completion_tokens: number;
  cost_saved_usd: string | number;
};
```

`frontend/src/api/hooks.ts` (follow the existing `useAiProviders`/`useAiUsage` pattern in that file):
```typescript
export function useAiSettings() {
  return useQuery({
    queryKey: ['ai', 'settings'],
    queryFn: () => apiGet<AiSettings>('/admin/ai/settings'),
  });
}

export function useUpdateAiSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: AiSettings) =>
      apiPut<AiSettings>('/admin/ai/settings', payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['ai', 'settings'] });
      void queryClient.invalidateQueries({ queryKey: ['ai', 'cache'] });
    },
  });
}

export function useAiCacheStatus() {
  return useQuery({
    queryKey: ['ai', 'cache'],
    queryFn: () => apiGet<AiCacheStatus>('/admin/ai/cache'),
  });
}

export function useAiCacheStats() {
  return useQuery({
    queryKey: ['ai', 'cache', 'stats'],
    queryFn: () => apiGet<AiUsageSummary>('/admin/ai/cache/stats'),
  });
}

export function useClearAiCache() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (namespace?: string) =>
      apiPost<{ removed: number }>('/admin/ai/cache/clear', { namespace: namespace ?? null }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['ai', 'cache'] });
    },
  });
}
```
(Use the file's existing `apiPut` import; add it if absent. Keep the exact hook style already in `hooks.ts`.)

- [ ] **Step 2: Write the failing test**

```tsx
// frontend/src/features/admin/ai/AiSettingsPage.test.tsx
import { beforeAll, describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import { AiSettingsPage } from './AiSettingsPage';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const settings = {
  ai_cache_type: 'local', ai_cache_namespace: 'gmc-ai',
  ai_cache_ttl_taxonomy_s: 2592000, ai_cache_ttl_content_s: 604800,
  ai_router_timeout_s: 30, ai_router_num_retries: 2, ai_router_allowed_fails: 3,
  ai_router_cooldown_s: 30, ai_instructor_max_retries: 2, ai_usage_retention_days: 90,
  redis_from_env: false, effective_cache_backend: 'local',
};
const status = {
  effective_backend: 'local', redis_from_env: false, healthy: true,
  namespace: 'gmc-ai', entries: 3,
};
const stats = {
  calls: 10, cache_hits: 4, hit_ratio: 0.4, prompt_tokens: 100,
  completion_tokens: 20, cost_usd: '0.01', saved_prompt_tokens: 40,
  saved_completion_tokens: 8, cost_saved_usd: '0.004',
};

beforeAll(async () => {
  await i18n.loadNamespaces('admin');
});

describe('AiSettingsPage', () => {
  it('renders settings, cache status and stats', async () => {
    stubFetch((url) => {
      if (url === '/admin/ai/settings') return jsonResponse(settings);
      if (url === '/admin/ai/cache') return jsonResponse(status);
      if (url === '/admin/ai/cache/stats') return jsonResponse(stats);
      return jsonResponse({});
    });
    render(<AiSettingsPage />);
    await waitFor(() => expect(screen.getByTestId('ai-settings-form')).toBeInTheDocument());
    expect(screen.getByTestId('ai-cache-backend')).toHaveTextContent('local');
    expect(screen.getByTestId('ai-cache-entries')).toHaveTextContent('3');
    expect(screen.getByTestId('ai-cache-hit-ratio')).toHaveTextContent('40');
  });

  it('saves settings via PUT', async () => {
    const puts: unknown[] = [];
    stubFetch((url, init) => {
      if (url === '/admin/ai/settings' && init?.method === 'PUT') {
        puts.push(JSON.parse(String(init.body)));
        return jsonResponse({ ...settings, ai_router_num_retries: 7 });
      }
      if (url === '/admin/ai/settings') return jsonResponse(settings);
      if (url === '/admin/ai/cache') return jsonResponse(status);
      if (url === '/admin/ai/cache/stats') return jsonResponse(stats);
      return jsonResponse({});
    });
    render(<AiSettingsPage />);
    await waitFor(() => expect(screen.getByTestId('ai-settings-form')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('ai-num-retries'), { target: { value: '7' } });
    fireEvent.click(screen.getByTestId('ai-settings-save'));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toMatchObject({ ai_router_num_retries: 7 });
  });

  it('shows the redis override and disables the backend selector', async () => {
    stubFetch((url) => {
      if (url === '/admin/ai/settings') {
        return jsonResponse({ ...settings, redis_from_env: true, effective_cache_backend: 'redis' });
      }
      if (url === '/admin/ai/cache') {
        return jsonResponse({ ...status, redis_from_env: true, effective_backend: 'redis' });
      }
      if (url === '/admin/ai/cache/stats') return jsonResponse(stats);
      return jsonResponse({});
    });
    render(<AiSettingsPage />);
    await waitFor(() => expect(screen.getByTestId('ai-settings-form')).toBeInTheDocument());
    expect(screen.getByTestId('ai-cache-backend')).toHaveTextContent('redis');
    expect(screen.getByTestId('ai-cache-backend-select')).toBeDisabled();
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npm run test -- AiSettingsPage`
Expected: FAIL — module `./AiSettingsPage` not found.

- [ ] **Step 4: Implement `AiSettingsPage.tsx`**

```tsx
import { useEffect, useState } from 'react';
import {
  Alert, Badge, Button, Card, Group, NumberInput, Select, Stack, Text, TextInput, Title,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import {
  useAiCacheStats, useAiCacheStatus, useAiSettings, useClearAiCache, useUpdateAiSettings,
} from '../../../api/hooks';
import { notifyMutationError, notifySuccess } from '../../../app/notifications';
import { ErrorState, LoadingState } from '../../../components/StateViews';
import type { AiSettings } from '../../../api/types';

export function AiSettingsPage() {
  const { t } = useTranslation('admin');
  const settingsQuery = useAiSettings();
  const statusQuery = useAiCacheStatus();
  const statsQuery = useAiCacheStats();
  const updateSettings = useUpdateAiSettings();
  const clearCache = useClearAiCache();
  const [draft, setDraft] = useState<AiSettings | null>(null);

  useEffect(() => {
    if (settingsQuery.data) setDraft(settingsQuery.data);
  }, [settingsQuery.data]);

  if (settingsQuery.isPending) return <LoadingState />;
  if (settingsQuery.isError) {
    return <ErrorState onRetry={() => void settingsQuery.refetch()} />;
  }
  if (!draft) return null;

  const patch = (patchValue: Partial<AiSettings>) => setDraft({ ...draft, ...patchValue });
  const redisOverride = draft.redis_from_env;
  const status = statusQuery.data;
  const stats = statsQuery.data;

  return (
    <Stack data-testid="ai-settings-form">
      <Card withBorder>
        <Title order={4}>{t('ai.settings.cacheTitle')}</Title>
        <Stack mt="sm">
          {redisOverride ? (
            <Alert color="blue" data-testid="ai-cache-redis-note">
              {t('ai.settings.redisOverride')}
            </Alert>
          ) : null}
          <Select
            label={t('ai.settings.cacheType')}
            data-testid="ai-cache-backend-select"
            disabled={redisOverride}
            value={draft.ai_cache_type}
            onChange={(value) => patch({ ai_cache_type: (value ?? 'local') as AiSettings['ai_cache_type'] })}
            data={[
              { value: 'local', label: t('ai.settings.cacheTypeOptions.local') },
              { value: 'disk', label: t('ai.settings.cacheTypeOptions.disk') },
            ]}
          />
          <TextInput
            label={t('ai.settings.namespace')}
            value={draft.ai_cache_namespace}
            onChange={(event) => patch({ ai_cache_namespace: event.currentTarget.value })}
          />
          <Group grow>
            <NumberInput
              label={t('ai.settings.ttlTaxonomy')}
              value={draft.ai_cache_ttl_taxonomy_s}
              min={1}
              onChange={(value) => patch({ ai_cache_ttl_taxonomy_s: Number(value) || 1 })}
            />
            <NumberInput
              label={t('ai.settings.ttlContent')}
              value={draft.ai_cache_ttl_content_s}
              min={1}
              onChange={(value) => patch({ ai_cache_ttl_content_s: Number(value) || 1 })}
            />
          </Group>
          <Group>
            <Text data-testid="ai-cache-backend">
              {t('ai.settings.backend')}: {status?.effective_backend ?? draft.effective_cache_backend}
            </Text>
            <Badge color={status?.healthy ? 'green' : 'red'}>
              {status?.healthy ? t('ai.settings.healthy') : t('ai.settings.unhealthy')}
            </Badge>
            <Text data-testid="ai-cache-entries">
              {t('ai.settings.entries')}: {status?.entries ?? '—'}
            </Text>
            <Text data-testid="ai-cache-hit-ratio">
              {t('ai.settings.hitRatio')}: {Math.round((stats?.hit_ratio ?? 0) * 100)}%
            </Text>
            <Text>{t('ai.settings.costSaved')}: {String(stats?.cost_saved_usd ?? 0)}</Text>
          </Group>
          <Group>
            <Button
              variant="light"
              color="red"
              onClick={() => clearCache.mutate(undefined, {
                onSuccess: () => notifySuccess(t('ai.settings.cacheCleared')),
                onError: (error) => notifyMutationError(error, t('ai.settings.saveFailed')),
              })}
            >
              {t('ai.settings.clearCache')}
            </Button>
          </Group>
        </Stack>
      </Card>
      <Card withBorder>
        <Title order={4}>{t('ai.settings.routerTitle')}</Title>
        <Stack mt="sm">
          <Group grow>
            <NumberInput label={t('ai.settings.timeout')} value={draft.ai_router_timeout_s}
              min={1} max={600} onChange={(v) => patch({ ai_router_timeout_s: Number(v) || 1 })} />
            <NumberInput label={t('ai.settings.numRetries')} data-testid="ai-num-retries"
              value={draft.ai_router_num_retries} min={0} max={10}
              onChange={(v) => patch({ ai_router_num_retries: Number(v) || 0 })} />
          </Group>
          <Group grow>
            <NumberInput label={t('ai.settings.allowedFails')} value={draft.ai_router_allowed_fails}
              min={0} max={100} onChange={(v) => patch({ ai_router_allowed_fails: Number(v) || 0 })} />
            <NumberInput label={t('ai.settings.cooldown')} value={draft.ai_router_cooldown_s}
              min={0} max={3600} onChange={(v) => patch({ ai_router_cooldown_s: Number(v) || 0 })} />
          </Group>
          <Group grow>
            <NumberInput label={t('ai.settings.instructorRetries')} value={draft.ai_instructor_max_retries}
              min={0} max={10} onChange={(v) => patch({ ai_instructor_max_retries: Number(v) || 0 })} />
            <NumberInput label={t('ai.settings.usageRetention')} value={draft.ai_usage_retention_days}
              min={1} onChange={(v) => patch({ ai_usage_retention_days: Number(v) || 1 })} />
          </Group>
          <Button
            data-testid="ai-settings-save"
            onClick={() => updateSettings.mutate(draft, {
              onSuccess: () => notifySuccess(t('ai.saved')),
              onError: (error) => notifyMutationError(error, t('ai.settings.saveFailed')),
            })}
          >
            {t('ai.save')}
          </Button>
        </Stack>
      </Card>
    </Stack>
  );
}
```

`AiAdminPage.tsx` — add the section:
```tsx
import { AiSettingsPage } from './AiSettingsPage';
// data:
{ value: 'settings', label: t('ai.section.settings') },
// render branch:
) : section === 'settings' ? (
  <AiSettingsPage />
) : (
```
and add `settings: 'Settings'` to `ai.section` in en + de.

i18n keys to add under `ai.settings` (en + de): `cacheTitle`, `routerTitle`, `cacheType`, `cacheTypeOptions.local`, `cacheTypeOptions.disk`, `namespace`, `ttlTaxonomy`, `ttlContent`, `backend`, `healthy`, `unhealthy`, `entries`, `hitRatio`, `costSaved`, `clearCache`, `cacheCleared`, `redisOverride`, `timeout`, `numRetries`, `allowedFails`, `cooldown`, `instructorRetries`, `usageRetention`, `saveFailed`; plus `ai.section.settings`.

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npm run test -- AiSettingsPage && npm run typecheck`
Expected: PASS; no type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api frontend/src/features/admin/ai frontend/public/locales
git commit -m "feat(ai): admin AI settings page with cache status and stats"
```

---

### Task 6: Docs and final gates

**Files:**
- Modify: `backend/docs/api.md`, `backend/docs/data-model.md`, `backend/docs/architecture.md`, `TODO.md`, `docs/superpowers/specs/2026-09-16-litellm-instructor-ai-core-design.md`, `docs/superpowers/plans/2026-09-16-ai-enrichment-step-phase-b.md` (status), `frontend/docs/architecture.md`

- [ ] **Step 1: Document the new endpoints and settings**

`backend/docs/api.md` — add the five new admin endpoints (`GET/PUT /admin/ai/settings`, `GET /admin/ai/usage/summary`, `GET /admin/ai/usage/timeseries`, `GET /admin/ai/cache`, `GET /admin/ai/cache/stats`, `POST /admin/ai/cache/clear`) with shapes; note settings are hot-applied and that 422 keeps the previous config.

`backend/docs/data-model.md` — note the `global_settings` AI columns are now admin-editable and `ai_cache_retention_days` is still present but unused (dropped in phase D).

`backend/docs/architecture.md` — document the caching fix (manual `use-cache` opt-in keeps writes validated-only; completion-level auto-caching is deliberately not used), cache status/clear, and settings hot-apply.

`frontend/docs/architecture.md` — add the AI settings section to the admin-area description.

`TODO.md` — cycle-log entry for phase C.

- [ ] **Step 2: Run the full gate suite**

```bash
uv run ruff check .          # "Found 490 errors"
uv run mypy .                # "Success: no issues found"
env -u DATABASE_URL TEST_DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2- | sed 's#^postgresql://#postgresql+asyncpg://#')" uv run pytest -q
cd ../frontend && npm run test && npm run typecheck
```
Expected: all green; ruff 490 (zero new).

- [ ] **Step 3: Commit**

```bash
git add backend/docs frontend/docs TODO.md docs/superpowers
git commit -m "docs(ai): phase C settings, cache telemetry, and caching fix"
```

---

## Self-Review

**Spec coverage (phase C):**
- `GET/PUT /admin/ai/settings` with hot-apply and 422-keeps-old → Task 3.
- Usage summary/KPI + time-series → Task 4.
- Cache status (backend/enabled/health/entries) + stats (hit ratio/tokens/cost saved) + clear → Tasks 2, 4.
- Frontend `AiSettingsPage` (Cache card + Router & retries card), `AiAdminPage` settings section, redis read-only override → Task 5.
- `redis_url`/`ai_cache_dir` stay env-only; no secret in responses → Task 3/4/5.
- **Discovered defect fixed:** validated-only caching now actually reads/writes (`use-cache` opt-in; cache kwargs no longer sent to the LLM) → Task 1. Redis is unbuffered by default; no change needed there. `rediss://` TLS is honored without changing `parse_redis_url`'s return shape (existing tests stay valid).

**Placeholder scan:** all code steps contain complete code; no TBD/TODO.

**Type consistency:** `NativeCache.request_kwargs` shape (`{"cache": {"use-cache", "namespace", "ttl"}}`) is used by Tasks 1–2 tests and `service.run_task`; `apply_settings(row) -> None` matches the route call in Task 3; `summarize_usage(...)` return keys match the `AiUsageSummary` type and the frontend test in Task 5; `status()` keys match `AiCacheStatus`; endpoint paths are identical across backend and frontend tasks.

**Deferred to phase D (not in this plan):** deleting `openai_compat.py`/`cache.py`/`resilience.py`/`AIProvider`, dropping `is_default`, `ai_result_cache`, and `ai_cache_retention_days`.
