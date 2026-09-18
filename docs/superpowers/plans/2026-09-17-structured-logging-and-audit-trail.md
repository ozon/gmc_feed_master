# Structured Logging and Audit Trail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured, correlated logging to the backend, a durable unified event/audit store with an admin viewer, and frontend error capture that ships to the backend.

**Architecture:** `structlog` is bridged through the stdlib `logging` module so the existing module-level loggers keep working unchanged. Request/actor/pipeline context travels in `structlog` contextvars and is merged into every log line. Audit and shipped frontend errors are written to one append-only Postgres `event_log` table, read by an admin-only `/logs/entries` endpoint and a `/logs` admin page.

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy 2.0, Alembic, structlog, pytest; React 19, TypeScript, Vite, Mantine, TanStack Query, vitest.

## Global Constraints

- Backend gates after every phase, run from `backend/`: `uv run ruff check . ../plugins`, `uv run mypy .`, `uv run alembic check`, `uv run pytest --report-log=.report.jsonl`. Frontend gates from `frontend/`: `npm run typecheck`, `npm run test`, `npm run build`.
- New backend dependency: `structlog` (range in `pyproject.toml`). No new frontend dependency.
- Logging calls use lazy `%s` interpolation, never f-strings (`backend/AGENTS.md`).
- `event_log.client_id` / `feed_source_id` are plain nullable integers, **not** foreign keys — matching the `ai_usage_logs` telemetry precedent.
- Backend routes are full paths (no router prefix) and must live under a Caddy-proxied prefix. Bare `/logs` is the SPA route, so backend paths are `/logs/entries` and `/logs/client`.
- Redaction in this plan is a backstop, not a license to log secrets. Never log request/response bodies for `/auth/*` or ingest credentials.
- Existing migration head is `1a5ebca06d61`; the new migration is `20260917_0001` with `down_revision = '1a5ebca06d61'`.
- Frontend tests use `src/test/render.tsx` helpers; server state lives only in TanStack Query.

---

## File Structure

Created:
- `backend/app/logging_setup.py` — structlog configuration + redaction processor.
- `backend/app/middleware/__init__.py`, `backend/app/middleware/request_context.py` — request id + contextvar binding + server-error persistence.
- `backend/app/models/event_log.py` — `EventLog` model.
- `backend/app/event_log/__init__.py`, `backend/app/event_log/service.py` — record/audit/purge service.
- `backend/app/schemas/logs.py` — API schemas.
- `backend/app/routes/logs.py` — `/logs/entries` + `/logs/client`.
- `backend/alembic/versions/20260917_0001_m18_event_log.py` — migration.
- `frontend/src/logging/logger.ts`, `frontend/src/logging/logger.test.ts` — frontend logger.
- `frontend/src/app/AppErrorBoundary.tsx` — top-level boundary.

Modified:
- `backend/pyproject.toml`, `backend/app/config.py`, `.env.example`
- `backend/app/main.py`, `backend/app/access.py`, `backend/app/pipeline/runner.py`
- `backend/app/models/__init__.py`, `backend/app/models/global_setting.py`
- `backend/app/schemas/admin.py`, `backend/app/routes/admin.py`
- Audit call sites (Task 9)
- `Caddyfile`, `Caddyfile.dev`
- `frontend/src/api/client.ts`, `frontend/src/api/hooks.ts`, `frontend/src/api/queryKeys.ts`, `frontend/src/api/types.ts`, `frontend/src/main.tsx`
- `frontend/src/features/systemLogs/SystemLogsPage.tsx`, `frontend/src/app/router.tsx`, `frontend/src/app/AppShell.tsx`, `frontend/src/features/admin/AdminSettingsPage.tsx`
- `frontend/public/locales/en/systemLogs.json`, `frontend/public/locales/de/systemLogs.json`
- Docs (Task 12)

---

# Part 1 — Backend logging core

### Task 1: structlog dependency and settings

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Test: `backend/tests/test_config_logging.py`

**Interfaces:**
- Produces: `Settings.log_level: str`, `Settings.log_format: Literal["json", "console"]`, `Settings.event_log_retention_days: int`.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_config_logging.py
from app.config import Settings


def test_logging_settings_defaults():
    settings = Settings(
        _env_file=None,
        session_secret="s",
        initial_username="u",
        initial_password="p",
    )
    assert settings.log_level == "INFO"
    assert settings.log_format == "json"
    assert settings.event_log_retention_days == 180


def test_logging_settings_env_override(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LOG_FORMAT", "console")
    monkeypatch.setenv("EVENT_LOG_RETENTION_DAYS", "30")
    settings = Settings(
        _env_file=None,
        session_secret="s",
        initial_username="u",
        initial_password="p",
    )
    assert settings.log_level == "DEBUG"
    assert settings.log_format == "console"
    assert settings.event_log_retention_days == 30
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config_logging.py -v`
Expected: FAIL — `Settings` has no attribute `log_level`.

- [x] **Step 3: Add the dependency and settings**

In `backend/pyproject.toml`, add to `dependencies` (keep alphabetical position near `sqlalchemy`):

```toml
  "structlog>=25.1,<27",
```

In `backend/app/config.py`, add `Literal` to the imports and the fields to `Settings`:

```python
from typing import Literal
```

```python
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    event_log_retention_days: int = Field(default=180, gt=0)
```

In `.env.example`, append:

```
# Logging: LOG_LEVEL is a stdlib level name; LOG_FORMAT is "json" (prod) or "console" (dev).
LOG_LEVEL=INFO
LOG_FORMAT=json
# Audit/error event retention window, also editable in admin settings.
EVENT_LOG_RETENTION_DAYS=180
```

- [x] **Step 4: Sync dependencies and run the test**

Run: `uv sync && uv run pytest tests/test_config_logging.py -v`
Expected: PASS (2 tests).

- [x] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/config.py .env.example backend/tests/test_config_logging.py
git commit -m "feat(logging): add structlog dependency and logging settings"
```

---

### Task 2: structlog configuration and redaction processor

**Files:**
- Create: `backend/app/logging_setup.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_logging_setup.py`

**Interfaces:**
- Produces: `configure_logging(settings: Settings | None) -> None`; `redact_sensitive(logger, method_name, event_dict) -> dict`; `SENSITIVE_KEYS`; `MAX_VALUE_LEN`.
- Consumes: `Settings.log_level`, `Settings.log_format` (Task 1).

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_logging_setup.py
import io
import json
import logging

import structlog

from app.config import Settings
from app.logging_setup import redact_sensitive


def _test_settings() -> Settings:
    return Settings(
        _env_file=None,
        session_secret="s",
        initial_username="u",
        initial_password="p",
        log_format="json",
        log_level="INFO",
    )


def test_redact_sensitive_keys_and_nesting():
    event = {
        "event": "login",
        "password": "hunter2",
        "nested": {"access_token": "abc", "keep": "value"},
        "items": [{"api_key": "k"}],
    }
    out = redact_sensitive(None, "info", event)
    assert out["password"] == "[REDACTED]"
    assert out["nested"]["access_token"] == "[REDACTED]"
    assert out["nested"]["keep"] == "value"
    assert out["items"][0]["api_key"] == "[REDACTED]"


def test_redact_sensitive_truncates_long_strings():
    long_value = "x" * 5000
    out = redact_sensitive(None, "info", {"event": "e", "body": long_value})
    assert out["body"].startswith("x" * 2048)
    assert out["body"].endswith("…[truncated]")
    assert len(out["body"]) < 5000


def test_stdlib_records_render_json_with_contextvars(monkeypatch):
    from app import logging_setup

    monkeypatch.setattr(logging_setup, "_configured", False)
    stream = io.StringIO()
    monkeypatch.setattr(logging_setup.sys, "stdout", stream)
    logging_setup.configure_logging(_test_settings())

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="req-123")
    logging.getLogger("app.demo").info("hello %s", "world")

    payload = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert payload["event"] == "hello world"
    assert payload["request_id"] == "req-123"
    assert payload["logger"] == "app.demo"
    assert payload["level"] == "info"
    structlog.contextvars.clear_contextvars()
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_logging_setup.py -v`
Expected: FAIL — module `app.logging_setup` does not exist.

- [x] **Step 3: Write the implementation**

```python
# backend/app/logging_setup.py
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from .config import Settings

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "token",
        "secret",
        "cookie",
        "authorization",
        "api_key",
        "apikey",
        "session",
        "credential",
        "private_key",
        "access_key",
        "refresh_token",
    }
)
_REDACTED = "[REDACTED]"
MAX_VALUE_LEN = 2048
_MAX_DEPTH = 3

_configured = False


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_KEYS)


def _truncate(value: str) -> str:
    if len(value) <= MAX_VALUE_LEN:
        return value
    return value[:MAX_VALUE_LEN] + "…[truncated]"


def _redact(value: Any, depth: int) -> Any:
    if depth >= _MAX_DEPTH:
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive(str(key)):
                out[key] = _REDACTED
            else:
                out[key] = _redact(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(item, depth + 1) for item in value]
    if isinstance(value, str):
        return _truncate(value)
    return value


def redact_sensitive(logger: Any, method_name: str, event_dict: dict) -> dict:
    # ponytail: depth-3 recursion cap, raise if nested payloads appear.
    return _redact(event_dict, 0)


def configure_logging(settings: Settings | None) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    level = (getattr(settings, "log_level", None) or "INFO").upper()
    log_format = (getattr(settings, "log_format", None) or "json").lower()
    renderer: Any = (
        structlog.dev.ConsoleRenderer()
        if log_format == "console"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_sensitive,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_sensitive,
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
```

In `backend/app/main.py`, import and call it first inside `create_app` (`from .logging_setup import configure_logging`), as the first statement of the function body:

```python
def create_app(
    settings: Settings | None = None,
    ...
) -> FastAPI:
    configure_logging(settings)
    if settings is None and session_store is None and db_session_factory is None:
        settings = _configured_settings()
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_logging_setup.py -v`
Expected: PASS (3 tests).

- [x] **Step 5: Commit**

```bash
git add backend/app/logging_setup.py backend/app/main.py backend/tests/test_logging_setup.py
git commit -m "feat(logging): structlog configuration and redaction processor"
```

---

### Task 3: Request context middleware

**Files:**
- Create: `backend/app/middleware/__init__.py`
- Create: `backend/app/middleware/request_context.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_request_context.py`

**Interfaces:**
- Produces: `RequestContextMiddleware`, `_resolve_request_id(raw: str | None) -> str`, `_REQUEST_ID_RE`.
- Consumes: `app.state.db_session_factory` (for server-error persistence).

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_request_context.py
import re

from app.middleware.request_context import _resolve_request_id

_UUID_RE = re.compile(r"^[0-9a-f-]{36}$")


def test_resolve_request_id_generates_when_absent():
    assert _UUID_RE.match(_resolve_request_id(None))


def test_resolve_request_id_accepts_valid():
    assert _resolve_request_id("abc12345") == "abc12345"
    assert _resolve_request_id("req-1_2.3") == "req-1_2.3"


def test_resolve_request_id_rejects_invalid():
    assert _resolve_request_id("bad id!") != "bad id!"
    assert _resolve_request_id("short") != "short"
    assert _resolve_request_id("x" * 100) != "x" * 100


def test_middleware_echoes_and_generates(client):
    generated = client.get("/health")
    assert _UUID_RE.match(generated.headers["x-request-id"])

    echoed = client.get("/health", headers={"X-Request-ID": "abc12345"})
    assert echoed.headers["x-request-id"] == "abc12345"

    replaced = client.get("/health", headers={"X-Request-ID": "bad id!"})
    assert replaced.headers["x-request-id"] != "bad id!"
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_request_context.py -v`
Expected: FAIL — module `app.middleware.request_context` does not exist.

- [x] **Step 3: Write the implementation**

```python
# backend/app/middleware/__init__.py
from .request_context import RequestContextMiddleware

__all__ = ["RequestContextMiddleware"]
```

```python
# backend/app/middleware/request_context.py
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger(__name__)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def _resolve_request_id(raw: str | None) -> str:
    if raw is not None and _REQUEST_ID_RE.match(raw):
        return raw
    return str(uuid.uuid4())


async def _persist_server_error(scope: Scope, exc: Exception, request_id: str) -> None:
    app = scope.get("app")
    factory = getattr(getattr(app, "state", None), "db_session_factory", None)
    if factory is None:
        return
    try:
        from ..event_log import record_server_error

        async with factory() as session, session.begin():
            await record_server_error(
                session,
                message=str(exc)[:4000],
                request_id=request_id,
                logger="app.middleware",
            )
    except Exception:
        logging.getLogger("app.middleware").warning(
            "failed to persist server error event", exc_info=True
        )


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = _resolve_request_id(headers.get("x-request-id"))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=scope["method"],
            path=scope["path"],
        )

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            logger.exception("unhandled error")
            await _persist_server_error(scope, exc, request_id)
            raise
        finally:
            structlog.contextvars.clear_contextvars()
```

Note: the `from ..event_log import ...` import lands only after Task 5 creates that package. If executing tasks strictly in order, this import is inside the function body and only resolves at runtime; until Task 5 exists, tests here never raise, so nothing imports it. Keep as written.

In `backend/app/main.py`, import `from .middleware import RequestContextMiddleware` and add it right after `app = FastAPI(lifespan=lifespan)`:

```python
    app = FastAPI(lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_request_context.py -v`
Expected: PASS (4 tests).

- [x] **Step 5: Commit**

```bash
git add backend/app/middleware backend/app/main.py backend/tests/test_request_context.py
git commit -m "feat(logging): request context middleware with request id"
```

---

### Task 4: Actor and pipeline-run context binding

**Files:**
- Modify: `backend/app/access.py:64-73`
- Modify: `backend/app/pipeline/runner.py:51-104`
- Test: `backend/tests/test_pipeline_run_logging.py`

**Interfaces:**
- Consumes: `structlog`.
- Produces: contextvars `actor`, `actor_role` bound during authenticated requests; `run_id`, `feed_source_id`, `client_id` bound during a pipeline run.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_pipeline_run_logging.py
import structlog
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Client, FeedSource
from app.pipeline import LockRegistry, StepResult
from app.pipeline.runner import PipelineRunner

pytestmark = pytest.mark.asyncio


class ContextCapturingStep:
    name = "capture"

    def __init__(self):
        self.contexts = []

    async def execute(self, ctx):
        self.contexts.append(dict(structlog.contextvars.get_contextvars()))
        return StepResult(0, 0, {})


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def feed_source_id(session_factory):
    async with session_factory() as session, session.begin():
        client = Client(name="Acme")
        session.add(client)
        await session.flush()
        feed_source = FeedSource(
            client_id=client.id,
            name="Main feed",
            source_format="xml",
            source_url="https://example.com/feed.xml",
        )
        session.add(feed_source)
        await session.flush()
        return feed_source.id


async def test_pipeline_run_binds_contextvars(session_factory, feed_source_id):
    step = ContextCapturingStep()
    runner = PipelineRunner(LockRegistry(), session_factory, [step])
    run_id = await runner.execute(feed_source_id)

    assert step.contexts, "step did not execute"
    context = step.contexts[0]
    assert context["feed_source_id"] == feed_source_id
    assert context["run_id"] == run_id
    assert context["client_id"] > 0

    assert "run_id" not in structlog.contextvars.get_contextvars()
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_run_logging.py -v`
Expected: FAIL — `KeyError: 'feed_source_id'`.

- [x] **Step 3: Bind contextvars**

In `backend/app/access.py`, add `import structlog` to the imports and bind after the user is resolved in `get_current_user`:

```python
async def get_current_user(
    request_user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> CurrentUser:
    user = await _load_user(db_session, request_user)
    structlog.contextvars.bind_contextvars(actor=user.username, actor_role=user.role)
    if db_session is not None:
        await db_session.rollback()
    return user
```

In `backend/app/pipeline/runner.py`, add `import structlog` to the imports, then bind and unbind around the steps loop. Replace the block from `run_id = await self._start(...)` through the end of the `try/finally` so it reads:

```python
            run_id = await self._start(feed_source_id, run_id)
            structlog.contextvars.bind_contextvars(
                run_id=run_id,
                feed_source_id=feed_source_id,
                client_id=feed_source.client_id,
            )
            processed_count = 0
            failed_count = 0
            statistics: dict = {}
            run_state = RunState()
            try:
                for step in self._steps:
                    ctx = StepContext(
                        feed_source_id=feed_source_id,
                        session_factory=self._session_factory,
                        logger=logger,
                        run_state=run_state,
                        ingestion_run_id=run_id,
                        trigger=trigger,
                    )
                    result: StepResult = await step.execute(ctx)
                    processed_count += result.processed_count
                    failed_count += result.failed_count
                    statistics.update(result.statistics)
            except Exception as exc:
                logger.exception("pipeline run %s failed for feed source %s", run_id, feed_source_id)
                return await self._finish(
                    feed_source_id,
                    run_id,
                    "error",
                    processed_count=processed_count,
                    failed_count=failed_count,
                    statistics=statistics,
                    error_message=str(exc)[:4000],
                    error_stack_trace=traceback.format_exc()[:20000],
                )
            return await self._finish(
                feed_source_id,
                run_id,
                "success",
                processed_count=processed_count,
                failed_count=failed_count,
                statistics=statistics,
            )
        finally:
            structlog.contextvars.unbind_contextvars(
                "run_id", "feed_source_id", "client_id"
            )
            lock.release()
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline_run_logging.py -v`
Expected: PASS.

- [x] **Step 5: Run the backend gate**

Run: `uv run ruff check . ../plugins && uv run mypy . && uv run pytest tests/test_pipeline_runner.py tests/test_request_context.py tests/test_logging_setup.py -q`
Expected: exit 0.

- [x] **Step 6: Commit**

```bash
git add backend/app/access.py backend/app/pipeline/runner.py backend/tests/test_pipeline_run_logging.py
git commit -m "feat(logging): bind actor and run context to log contextvars"
```

---

# Part 2 — Unified event store

### Task 5: EventLog model and migration

**Files:**
- Create: `backend/app/models/event_log.py`
- Create: `backend/alembic/versions/20260917_0001_m18_event_log.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_event_log_model.py`

**Interfaces:**
- Produces: `EventLog` with fields `id, created_at, category, level, source, logger, actor, actor_role, client_id, feed_source_id, request_id, run_id, message, context`.
- Consumes: migration head `1a5ebca06d61`.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_event_log_model.py
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.event_log import EventLog

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    f = async_sessionmaker(engine, expire_on_commit=False)
    yield f
    await engine.dispose()


async def test_event_log_roundtrip_defaults(factory):
    async with factory() as session, session.begin():
        session.add(EventLog(category="audit", level="info", source="backend", message="hello"))
    async with factory() as session:
        row = (await session.execute(select(EventLog))).scalar_one()
        assert row.id > 0
        assert row.context == {}
        assert row.created_at is not None
        assert row.actor is None
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_event_log_model.py -v`
Expected: FAIL — module `app.models.event_log` does not exist.

- [x] **Step 3: Write the model, migration, and registry**

```python
# backend/app/models/event_log.py
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class EventLog(Base):
    __tablename__ = "event_log"
    __table_args__ = (
        Index("ix_event_log_created_at", "created_at"),
        Index("ix_event_log_category_created_at", "category", "created_at"),
        Index("ix_event_log_request_id", "request_id"),
        Index("ix_event_log_feed_source_id", "feed_source_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    logger: Mapped[str | None] = mapped_column(String(120), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    client_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feed_source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
```

Verify the `Base` import path by checking an existing model, e.g. `backend/app/models/ai.py`; use whichever module defines `Base` (likely `app.db.base`). If it is `app.db.engine`, import `from ..db.engine import Base` instead. Do not guess — match `ai.py`.

Register in `backend/app/models/__init__.py`:

```python
from .event_log import EventLog
```

and add `"EventLog"` to `__all__`.

```python
# backend/alembic/versions/20260917_0001_m18_event_log.py
"""m18 event log and retention

Revision ID: 20260917_0001
Revises: 1a5ebca06d61
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260917_0001"
down_revision: str | Sequence[str] | None = "1a5ebca06d61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("logger", sa.String(length=120), nullable=True),
        sa.Column("actor", sa.String(length=120), nullable=True),
        sa.Column("actor_role", sa.String(length=20), nullable=True),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("feed_source_id", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index("ix_event_log_created_at", "event_log", ["created_at"])
    op.create_index(
        "ix_event_log_category_created_at", "event_log", ["category", "created_at"]
    )
    op.create_index("ix_event_log_request_id", "event_log", ["request_id"])
    op.create_index("ix_event_log_feed_source_id", "event_log", ["feed_source_id"])


def downgrade() -> None:
    op.drop_index("ix_event_log_feed_source_id", table_name="event_log")
    op.drop_index("ix_event_log_request_id", table_name="event_log")
    op.drop_index("ix_event_log_category_created_at", table_name="event_log")
    op.drop_index("ix_event_log_created_at", table_name="event_log")
    op.drop_table("event_log")
```

- [x] **Step 4: Apply the migration and run the test**

Run:
```bash
uv run alembic upgrade head
uv run alembic check
uv run pytest tests/test_event_log_model.py -v
```
Expected: `alembic check` reports no new upgrade operations; test PASSes.

- [x] **Step 5: Commit**

```bash
git add backend/app/models/event_log.py backend/app/models/__init__.py backend/alembic/versions/20260917_0001_m18_event_log.py backend/tests/test_event_log_model.py
git commit -m "feat(logging): event_log model and migration"
```

---

### Task 6: Event store service and retention setting

**Files:**
- Create: `backend/app/event_log/__init__.py`
- Create: `backend/app/event_log/service.py`
- Create: `backend/alembic/versions/20260917_0002_m18_event_log_retention.py`
- Modify: `backend/app/models/global_setting.py`
- Modify: `backend/app/schemas/admin.py`
- Modify: `backend/app/routes/admin.py:111-153`
- Test: `backend/tests/test_event_log_service.py`

**Interfaces:**
- Produces:
  - `record_event(session, *, category, level, source, message, context=None, logger=None, actor=None, actor_role=None, client_id=None, feed_source_id=None, request_id=None, run_id=None) -> None`
  - `audit(session, action, *, target_type=None, target_id=None, detail=None, level="info") -> None`
  - `record_client_error(session, *, message, level="error", context=None, request_id=None, route=None, actor=None) -> None`
  - `record_server_error(session, *, message, context=None, request_id=None, logger=None) -> None`
  - `DEFAULT_EVENT_LOG_RETENTION_DAYS`, `EventLogPurgeCounts`, `purge_expired_events` (Task 7 uses the last one).
- Consumes: `EventLog` (Task 5), `GlobalSetting`.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_event_log_service.py
import pytest
import pytest_asyncio
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.event_log import audit, record_event
from app.models.event_log import EventLog

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    f = async_sessionmaker(engine, expire_on_commit=False)
    yield f
    await engine.dispose()


async def test_record_event_inserts_row(factory):
    async with factory() as session, session.begin():
        await record_event(
            session,
            category="client_error",
            level="error",
            source="frontend",
            message="boom",
            context={"route": "/logs"},
            request_id="req-1",
        )
    async with factory() as session:
        row = (await session.execute(select(EventLog))).scalar_one()
        assert row.category == "client_error"
        assert row.context == {"route": "/logs"}
        assert row.request_id == "req-1"


async def test_audit_pulls_actor_from_contextvars(factory):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        actor="operator", actor_role="admin", request_id="req-9", run_id=7
    )
    async with factory() as session, session.begin():
        await audit(session, "login success", target_type="user", target_id="operator")
    structlog.contextvars.clear_contextvars()

    async with factory() as session:
        row = (await session.execute(select(EventLog))).scalar_one()
        assert row.category == "audit"
        assert row.actor == "operator"
        assert row.actor_role == "admin"
        assert row.request_id == "req-9"
        assert row.run_id == 7
        assert row.context["target_type"] == "user"
        assert row.context["target_id"] == "operator"
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_event_log_service.py -v`
Expected: FAIL — `app.event_log` does not exist.

- [x] **Step 3: Write the service and retention plumbing**

Add to `backend/app/models/global_setting.py`:

```python
    event_log_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=180, server_default="180"
    )
```

Add `backend/alembic/versions/20260917_0002_m18_event_log_retention.py`:

```python
"""m18 event log retention setting

Revision ID: 20260917_0002
Revises: 20260917_0001
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260917_0002"
down_revision: str | Sequence[str] | None = "20260917_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "global_settings",
        sa.Column(
            "event_log_retention_days",
            sa.Integer(),
            nullable=False,
            server_default="180",
        ),
    )


def downgrade() -> None:
    op.drop_column("global_settings", "event_log_retention_days")
```

```python
# backend/app/event_log/__init__.py
from .service import (
    DEFAULT_EVENT_LOG_RETENTION_DAYS,
    EVENT_LOG_PURGE_JOB_ID,
    EventLogPurgeCounts,
    audit,
    purge_expired_events,
    record_client_error,
    record_event,
    record_server_error,
)

__all__ = [
    "DEFAULT_EVENT_LOG_RETENTION_DAYS",
    "EVENT_LOG_PURGE_JOB_ID",
    "EventLogPurgeCounts",
    "audit",
    "purge_expired_events",
    "record_client_error",
    "record_event",
    "record_server_error",
]
```

```python
# backend/app/event_log/service.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.event_log import EventLog
from ..models.global_setting import GlobalSetting

DEFAULT_EVENT_LOG_RETENTION_DAYS = 180
EVENT_LOG_PURGE_JOB_ID = "system-event-log-purge"
_MAX_MESSAGE = 4000


def _bound(name: str) -> Any:
    return structlog.contextvars.get_contextvars().get(name)


async def record_event(
    session: AsyncSession,
    *,
    category: str,
    level: str,
    source: str,
    message: str,
    context: dict[str, Any] | None = None,
    logger: str | None = None,
    actor: str | None = None,
    actor_role: str | None = None,
    client_id: int | None = None,
    feed_source_id: int | None = None,
    request_id: str | None = None,
    run_id: int | None = None,
) -> None:
    session.add(
        EventLog(
            category=category,
            level=level,
            source=source,
            message=message[:_MAX_MESSAGE],
            context=context or {},
            logger=logger,
            actor=actor,
            actor_role=actor_role,
            client_id=client_id,
            feed_source_id=feed_source_id,
            request_id=request_id,
            run_id=run_id,
        )
    )


async def audit(
    session: AsyncSession,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    context: dict[str, Any] = dict(detail or {})
    if target_type is not None:
        context["target_type"] = target_type
    if target_id is not None:
        context["target_id"] = str(target_id)
    await record_event(
        session,
        category="audit",
        level=level,
        source="backend",
        message=action,
        context=context,
        actor=_bound("actor"),
        actor_role=_bound("actor_role"),
        client_id=_bound("client_id"),
        feed_source_id=_bound("feed_source_id"),
        request_id=_bound("request_id"),
        run_id=_bound("run_id"),
    )


async def record_client_error(
    session: AsyncSession,
    *,
    message: str,
    level: str = "error",
    context: dict[str, Any] | None = None,
    request_id: str | None = None,
    route: str | None = None,
    actor: str | None = None,
) -> None:
    ctx: dict[str, Any] = dict(context or {})
    if route:
        ctx.setdefault("route", route)
    await record_event(
        session,
        category="client_error",
        level=level,
        source="frontend",
        message=message,
        context=ctx,
        actor=actor or _bound("actor"),
        actor_role=_bound("actor_role"),
        request_id=request_id or _bound("request_id"),
    )


async def record_server_error(
    session: AsyncSession,
    *,
    message: str,
    context: dict[str, Any] | None = None,
    request_id: str | None = None,
    logger: str | None = None,
) -> None:
    await record_event(
        session,
        category="server_error",
        level="error",
        source="backend",
        message=message,
        context=context or {},
        actor=_bound("actor"),
        actor_role=_bound("actor_role"),
        client_id=_bound("client_id"),
        feed_source_id=_bound("feed_source_id"),
        request_id=request_id or _bound("request_id"),
        run_id=_bound("run_id"),
        logger=logger,
    )
```

Update `backend/app/schemas/admin.py`:

```python
class GlobalSettingsOut(BaseModel):
    staging_removal_retention_days: int = Field(ge=1)
    staging_history_retention_days: int = Field(ge=1)
    ingestion_run_retention_days: int = Field(ge=1)
    ai_usage_retention_days: int = Field(ge=1)
    event_log_retention_days: int = Field(ge=1)
```

In `backend/app/routes/admin.py`, add `event_log_retention_days=180` to both `GlobalSetting(...)` constructions (lines ~120-126 and ~141-147) and add `row.event_log_retention_days = payload.event_log_retention_days` to `put_settings_row` alongside the other assignments.

- [x] **Step 4: Apply the migration and run the test**

Run:
```bash
uv run alembic upgrade head && uv run alembic check
uv run pytest tests/test_event_log_service.py tests/test_ai_admin_api.py -v
```
Expected: `alembic check` clean; tests PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/event_log backend/app/models/global_setting.py backend/app/schemas/admin.py backend/app/routes/admin.py backend/tests/test_event_log_service.py
git commit -m "feat(logging): event store service and retention setting"
```

---

### Task 7: Event log purge job

**Files:**
- Modify: `backend/app/event_log/service.py`
- Modify: `backend/app/main.py` (lifespan)
- Test: `backend/tests/test_event_log_purge.py`

**Interfaces:**
- Consumes: `record_event` (Task 6), `GlobalSetting.event_log_retention_days` (Task 6).
- Produces: `purge_expired_events(session_factory, now) -> EventLogPurgeCounts` with `.rows`.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_event_log_purge.py
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.event_log import purge_expired_events, record_event
from app.models.event_log import EventLog

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    f = async_sessionmaker(engine, expire_on_commit=False)
    yield f
    await engine.dispose()


async def test_purge_removes_rows_older_than_retention(factory):
    now = datetime.now(timezone.utc)
    async with factory() as session, session.begin():
        await record_event(session, category="audit", level="info", source="backend", message="old")
        await record_event(session, category="audit", level="info", source="backend", message="new")
    async with factory() as session, session.begin():
        rows = (await session.execute(select(EventLog).order_by(EventLog.id))).scalars().all()
        rows[0].created_at = now - timedelta(days=400)
        rows[1].created_at = now - timedelta(days=1)

    counts = await purge_expired_events(factory, now)
    assert counts.rows == 1

    async with factory() as session:
        remaining = (await session.execute(select(EventLog))).scalars().all()
        assert [r.message for r in remaining] == ["new"]
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_event_log_purge.py -v`
Expected: FAIL — `cannot import name 'purge_expired_events'`.

- [x] **Step 3: Implement the purge**

Append to `backend/app/event_log/service.py`:

```python
@dataclass(frozen=True)
class EventLogPurgeCounts:
    rows: int


async def _retention_days(session: AsyncSession) -> int:
    row = await session.get(GlobalSetting, 1)
    if row is None:
        return DEFAULT_EVENT_LOG_RETENTION_DAYS
    return row.event_log_retention_days


async def purge_expired_events(
    session_factory: Callable[[], AsyncSession],
    now: datetime,
) -> EventLogPurgeCounts:
    async with session_factory() as session, session.begin():
        days = await _retention_days(session)
        result = await session.execute(
            delete(EventLog).where(EventLog.created_at < now - timedelta(days=days))
        )
        return EventLogPurgeCounts(rows=result.rowcount)
```

In `backend/app/main.py` lifespan, alongside the other purge registrations (after the AI purge block), add:

```python
                from .event_log import EVENT_LOG_PURGE_JOB_ID, purge_expired_events

                async def run_event_log_purge() -> None:
                    counts = await purge_expired_events(
                        application.state.db_session_factory,
                        datetime.now(timezone.utc),
                    )
                    logging.getLogger(__name__).info(
                        "event log purge: %s rows", counts.rows
                    )

                scheduler_service.register_system_job(
                    EVENT_LOG_PURGE_JOB_ID, PURGE_CRON, run_event_log_purge
                )
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_event_log_purge.py -v`
Expected: PASS.

- [x] **Step 5: Run the backend gate**

Run: `uv run ruff check . ../plugins && uv run mypy . && uv run alembic check && uv run pytest tests/test_event_log_purge.py tests/test_event_log_service.py tests/test_migrations.py -q`
Expected: exit 0.

- [x] **Step 6: Commit**

```bash
git add backend/app/event_log/service.py backend/app/main.py backend/tests/test_event_log_purge.py
git commit -m "feat(logging): event log retention purge job"
```

---

# Part 3 — API, audit capture, and admin viewer

### Task 8: Logs API endpoints and Caddy routing

**Files:**
- Create: `backend/app/schemas/logs.py`
- Create: `backend/app/routes/logs.py`
- Modify: `backend/app/routes/__init__.py`
- Modify: `backend/app/main.py` (include router)
- Modify: `Caddyfile`, `Caddyfile.dev`
- Test: `backend/tests/test_logs_api.py`

**Interfaces:**
- Consumes: `require_admin`, `require_user` (`app/access.py`, `app/auth.py`), `record_client_error` (Task 6), `EventLog` (Task 5).
- Produces: `GET /logs/entries` returning `{items, next_cursor}`; `POST /logs/client` returning 204.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_logs_api.py
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.event_log import EventLog
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def settings_app(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(EventLog))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "admin-pass")
        await seed_initial_user(session, "viewer", "user-pass")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="admin-pass",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


async def _login(app, username, password):
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    response = await client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200
    return client


async def test_get_entries_requires_admin(settings_app):
    app, _ = settings_app
    user_client = await _login(app, "viewer", "user-pass")
    response = await user_client.get("/logs/entries")
    assert response.status_code == 403
    await user_client.aclose()


async def test_client_logs_ingested_and_listed(settings_app):
    app, _ = settings_app
    user_client = await _login(app, "viewer", "user-pass")
    ingest = await user_client.post(
        "/logs/client",
        json={
            "entries": [
                {
                    "level": "error",
                    "message": "render failed",
                    "route": "/logs",
                    "request_id": "req-77",
                    "context": {"component": "SystemLogsPage"},
                }
            ]
        },
    )
    assert ingest.status_code == 204
    await user_client.aclose()

    admin_client = await _login(app, "operator", "admin-pass")
    listing = await admin_client.get("/logs/entries?category=client_error")
    assert listing.status_code == 200
    body = listing.json()
    assert body["next_cursor"] is None
    assert body["items"][0]["message"] == "render failed"
    assert body["items"][0]["request_id"] == "req-77"
    assert body["items"][0]["source"] == "frontend"
    await admin_client.aclose()


async def test_client_logs_reject_empty_batch(settings_app):
    app, _ = settings_app
    user_client = await _login(app, "viewer", "user-pass")
    response = await user_client.post("/logs/client", json={"entries": []})
    assert response.status_code == 422
    await user_client.aclose()


async def test_entries_pagination_cursor(settings_app):
    app, factory = settings_app
    from app.event_log import record_event

    async with factory() as session, session.begin():
        for i in range(3):
            await record_event(
                session, category="audit", level="info", source="backend", message=f"m{i}"
            )
    admin_client = await _login(app, "operator", "admin-pass")
    first = (await admin_client.get("/logs/entries?limit=2")).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None
    second = (
        await admin_client.get(f"/logs/entries?limit=2&cursor={first['next_cursor']}")
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    await admin_client.aclose()
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_logs_api.py -v`
Expected: FAIL — 404 on `/logs/entries`.

- [x] **Step 3: Write schemas and router**

```python
# backend/app/schemas/logs.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EventLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    category: str
    level: str
    source: str
    logger: str | None
    actor: str | None
    actor_role: str | None
    client_id: int | None
    feed_source_id: int | None
    request_id: str | None
    run_id: int | None
    message: str
    context: dict[str, Any]


class EventLogPage(BaseModel):
    items: list[EventLogOut]
    next_cursor: int | None


class ClientLogEntry(BaseModel):
    level: Literal["warning", "error", "critical"] = "error"
    message: str = Field(min_length=1, max_length=2000)
    stack: str | None = Field(default=None, max_length=8000)
    route: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=500)
    request_id: str | None = Field(default=None, max_length=64)
    context: dict[str, Any] = Field(default_factory=dict)


class ClientLogBatch(BaseModel):
    entries: list[ClientLogEntry] = Field(min_length=1, max_length=20)
```

```python
# backend/app/routes/logs.py
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..access import CurrentUser, require_admin
from ..auth import require_user
from ..db.engine import get_db_session
from ..event_log import record_client_error
from ..models.event_log import EventLog
from ..schemas.logs import ClientLogBatch, EventLogOut, EventLogPage

router = APIRouter()

_MAX_LIMIT = 500
_CLIENT_LOG_WINDOW_S = 60
_CLIENT_LOG_MAX_PER_WINDOW = 60
_client_log_hits: dict[str, tuple[float, int]] = {}


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _allow_client_log(username: str, now: float) -> bool:
    # ponytail: in-memory fixed window, single worker — move to Redis if workers scale.
    window_start, count = _client_log_hits.get(username, (now, 0))
    if now - window_start >= _CLIENT_LOG_WINDOW_S:
        _client_log_hits[username] = (now, 1)
        return True
    if count >= _CLIENT_LOG_MAX_PER_WINDOW:
        return False
    _client_log_hits[username] = (window_start, count + 1)
    return True


@router.get("/logs/entries", response_model=EventLogPage)
async def list_events(
    category: str | None = None,
    level: str | None = None,
    source: str | None = None,
    logger: str | None = None,
    actor: str | None = None,
    client_id: int | None = None,
    feed_source_id: int | None = None,
    request_id: str | None = None,
    run_id: int | None = None,
    q: str | None = None,
    limit: int = 100,
    cursor: int | None = None,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> EventLogPage:
    session = _require_db(db_session)
    stmt = select(EventLog).order_by(EventLog.id.desc())
    if category:
        stmt = stmt.where(EventLog.category == category)
    if level:
        stmt = stmt.where(EventLog.level == level)
    if source:
        stmt = stmt.where(EventLog.source == source)
    if logger:
        stmt = stmt.where(EventLog.logger == logger)
    if actor:
        stmt = stmt.where(EventLog.actor == actor)
    if client_id is not None:
        stmt = stmt.where(EventLog.client_id == client_id)
    if feed_source_id is not None:
        stmt = stmt.where(EventLog.feed_source_id == feed_source_id)
    if request_id:
        stmt = stmt.where(EventLog.request_id == request_id)
    if run_id is not None:
        stmt = stmt.where(EventLog.run_id == run_id)
    if q:
        stmt = stmt.where(EventLog.message.ilike(f"%{q}%"))
    if cursor is not None:
        stmt = stmt.where(EventLog.id < cursor)
    limit = max(1, min(limit, _MAX_LIMIT))

    async with session.begin():
        rows = (await session.execute(stmt.limit(limit + 1))).scalars().all()
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return EventLogPage(
        items=[EventLogOut.model_validate(row) for row in rows[:limit]],
        next_cursor=next_cursor,
    )


@router.post("/logs/client", status_code=204)
async def ingest_client_logs(
    payload: ClientLogBatch,
    username: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> None:
    session = _require_db(db_session)
    if not _allow_client_log(username, time.monotonic()):
        raise HTTPException(status_code=429, detail="log rate limit exceeded")
    async with session.begin():
        for entry in payload.entries:
            context = dict(entry.context)
            if entry.stack:
                context["stack"] = entry.stack
            if entry.url:
                context["url"] = entry.url
            await record_client_error(
                session,
                message=entry.message,
                level=entry.level,
                context=context,
                request_id=entry.request_id,
                route=entry.route,
                actor=username,
            )
```

Add `logs_router` to `backend/app/routes/__init__.py` (import `from .logs import router as logs_router`, add to `__all__`) and register it in `create_app` without `enforce_scope_access`, next to `admin_router`:

```python
    app.include_router(logs_router)
```

Add the Caddy block to both `Caddyfile` and `Caddyfile.dev`, immediately before the generic `handle`:

```
	handle /logs/* {
		reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
	}
```

`Caddyfile.dev` uses `reverse_proxy http://127.0.0.1:8000` (no variable) to match its other blocks.

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_logs_api.py -v`
Expected: PASS (5 tests).

- [x] **Step 5: Commit**

```bash
git add backend/app/schemas/logs.py backend/app/routes/logs.py backend/app/routes/__init__.py backend/app/main.py Caddyfile Caddyfile.dev backend/tests/test_logs_api.py
git commit -m "feat(logging): logs API with admin listing and client error ingest"
```

---

### Task 9: Audit instrumentation at mutation sites

**Files:**
- Modify: `backend/app/main.py` (auth handlers)
- Modify: `backend/app/routes/admin.py`
- Modify: `backend/app/routes/clients.py`
- Modify: `backend/app/routes/field_mapping.py`
- Modify: `backend/app/routes/plugins.py`
- Modify: `backend/app/routes/pipeline.py`
- Modify: `backend/app/routes/ai_admin.py`
- Modify: `backend/app/routes/export_history.py`
- Test: `backend/tests/test_audit_events.py`

**Interfaces:**
- Consumes: `audit` (Task 6).
- Produces: one `event_log` row with `category="audit"` per in-scope mutation.

All calls use this shape, inside the handler's existing `session.begin()` transaction, after the mutation succeeds:

```python
        await audit(session, "<action>", target_type="<type>", target_id=<id>)
```

Import in each file: `from ..event_log import audit` (routes) / `from .event_log import audit` (`app/main.py`).

Action map — add exactly one call per handler:

| File | Handler | Action string | target_type | target_id |
|------|---------|---------------|-------------|-----------|
| `main.py` | `login` | `auth.login.success` | `user` | `user_id` |
| `main.py` | `login` (bad credentials) | `auth.login.failure` | `user` | `credentials.username` |
| `main.py` | `logout` | `auth.logout` | `user` | `request_user` |
| `main.py` | `password` | `auth.password.change` | `user` | `request_user` |
| `admin.py` | `create_user` | `user.create` | `user` | created id |
| `admin.py` | `update_user` | `user.update` | `user` | `user_id` |
| `admin.py` | `set_password` | `user.password.reset` | `user` | `user_id` |
| `admin.py` | `put_settings_row` | `settings.update` | `global_settings` | `1` |
| `clients.py` | `create_client` | `client.create` | `client` | created id |
| `clients.py` | `update_client` | `client.update` | `client` | `client_id` |
| `clients.py` | `delete_client` | `client.delete` | `client` | `client_id` |
| `clients.py` | `create_feed_source` | `feed_source.create` | `feed_source` | created id |
| `clients.py` | `update_feed_source` | `feed_source.update` | `feed_source` | `feed_source_id` |
| `clients.py` | `delete_feed_source` | `feed_source.delete` | `feed_source` | `feed_source_id` |
| `clients.py` | `rotate_export_token` | `feed_source.export_token.rotate` | `feed_source` | `feed_source_id` |
| `clients.py` | `run_feed_source` | `feed_source.run.trigger` | `feed_source` | `feed_source_id` |
| `field_mapping.py` | `put_field_mapping` | `field_mapping.update` | `feed_source` | `feed_source_id` |
| `field_mapping.py` | `auto_map` | `field_mapping.auto` | `feed_source` | `feed_source_id` |
| `plugins.py` | `put_plugin_enabled` | `plugin.enabled.update` | `plugin` | `plugin_id` |
| `plugins.py` | `put_plugin_config` | `plugin.config.update` | `plugin` | `plugin_id` |
| `plugins.py` | `put_plugin_data` | `plugin.data.update` | `plugin` | `plugin_id` |
| `pipeline.py` | `put_pipeline` | `pipeline.update` | `feed_source` | `feed_source_id` |
| `pipeline.py` | `patch_instance` | `pipeline.instance.update` | `feed_source` | `feed_source_id` |
| `ai_admin.py` | `put_ai_settings` | `ai.settings.update` | `ai_settings` | `1` |
| `ai_admin.py` | provider create/update/delete | `ai.provider.<verb>` | `ai_provider` | id |
| `ai_admin.py` | prompt template create/update/delete | `ai.prompt_template.<verb>` | `ai_prompt_template` | id |
| `export_history.py` | manual export POST | `export.publish` | `feed_source` | `feed_source_id` |

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_audit_events.py
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.event_log import EventLog
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def settings_app(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(EventLog))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "admin-pass")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="admin-pass",
        database_url=isolated_database_url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


async def _audit_messages(factory):
    async with factory() as session:
        rows = (
            await session.execute(
                select(EventLog).where(EventLog.category == "audit").order_by(EventLog.id)
            )
        ).scalars().all()
        return [r.message for r in rows]


async def test_login_success_and_failure_are_audited(settings_app):
    app, factory = settings_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (
        await client.post(
            "/auth/login", json={"username": "operator", "password": "wrong"}
        )
    ).status_code == 401
    assert (
        await client.post(
            "/auth/login", json={"username": "operator", "password": "admin-pass"}
        )
    ).status_code == 200
    await client.aclose()
    messages = await _audit_messages(factory)
    assert "auth.login.failure" in messages
    assert "auth.login.success" in messages


async def test_user_create_is_audited_with_actor(settings_app):
    app, factory = settings_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    await client.post(
        "/auth/login", json={"username": "operator", "password": "admin-pass"}
    )
    created = await client.post(
        "/admin/users",
        json={"username": "newuser", "password": "pw", "role": "user", "client_ids": []},
    )
    assert created.status_code == 201
    await client.aclose()

    async with factory() as session:
        row = (
            await session.execute(
                select(EventLog).where(EventLog.message == "user.create")
            )
        ).scalar_one()
        assert row.actor == "operator"
        assert row.actor_role == "admin"
        assert row.context["target_type"] == "user"
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audit_events.py -v`
Expected: FAIL — no audit rows.

- [x] **Step 3: Add the audit calls**

Work through the action map above. For the login failure path in `backend/app/main.py`, wrap the `authenticate` call so a rejected login still writes an audit row before re-raising:

```python
    @app.post("/auth/login")
    async def login(
        credentials: Credentials,
        request: Request,
        response: Response,
        settings: Settings = Depends(get_settings),
        store: SessionStore = Depends(_store),
        db_session: AsyncSession | None = Depends(get_db_session),
    ) -> dict[str, str]:
        from .event_log import audit

        try:
            user_id = await authenticate(
                credentials,
                settings,
                None if request.app.state.session_store_injected else db_session,
            )
        except HTTPException:
            if db_session is not None:
                async with db_session.begin():
                    await audit(
                        db_session,
                        "auth.login.failure",
                        target_type="user",
                        target_id=credentials.username,
                    )
            raise
        token = await create_session(store, app.state.clock, user_id)
        set_session_cookie(response, token, settings.session_absolute_hours * 60 * 60)
        if db_session is not None:
            async with db_session.begin():
                await audit(
                    db_session, "auth.login.success", target_type="user", target_id=user_id
                )
        return {"username": user_id}
```

Note: `authenticate` raises `HTTPException` on bad credentials. If the real signature differs, check `backend/app/auth.py` and adapt the `except` clause to the exception it raises, keeping the audit-before-raise behavior.

The remaining handlers follow the table: find the handler, and immediately after the mutation (and after the id is known/flushed) insert the single `await audit(...)` line shown in the shape above, reusing the handler's existing `session` and transaction.

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_audit_events.py -v`
Expected: PASS (2 tests).

- [x] **Step 5: Run the backend gate**

Run: `uv run ruff check . ../plugins && uv run mypy . && uv run pytest -q`
Expected: full suite exit 0.

- [x] **Step 6: Commit**

```bash
git add backend/app/routes backend/app/main.py backend/tests/test_audit_events.py
git commit -m "feat(logging): audit events for auth, admin, config, and exports"
```

---

### Task 10: Frontend logs API hooks, viewer page, routing, and settings field

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/queryKeys.ts`
- Modify: `frontend/src/api/hooks.ts`
- Modify: `frontend/src/features/admin/AdminSettingsPage.tsx`
- Modify: `frontend/src/features/systemLogs/SystemLogsPage.tsx`
- Modify: `frontend/src/app/router.tsx`
- Modify: `frontend/src/app/AppShell.tsx`
- Modify: `frontend/public/locales/en/systemLogs.json`, `frontend/public/locales/de/systemLogs.json`
- Modify: `frontend/public/locales/en/common.json`, `frontend/public/locales/de/common.json` (only if a nav hide flag is needed)
- Test: `frontend/src/features/systemLogs/SystemLogsPage.test.tsx`, `frontend/src/api/hooks.logs.test.tsx`

**Interfaces:**
- Consumes: `GET /logs/entries` (Task 8), `useSession` (`hooks.ts`).
- Produces: `useEventLogs(filters)` infinite query; `EventLogEntry` type; `GlobalSettings.event_log_retention_days`.

- [x] **Step 1: Write the failing tests**

Replace `frontend/src/features/systemLogs/SystemLogsPage.test.tsx`:

```tsx
import { beforeAll, describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { SystemLogsPage } from './SystemLogsPage';

const fetchMock = vi.fn<typeof fetch>();

beforeAll(async () => {
  await i18n.loadNamespaces(['systemLogs']);
});

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
});

describe('SystemLogsPage', () => {
  it('renders log rows from the API', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [
            {
              id: 2,
              created_at: '2026-09-17T10:00:00Z',
              category: 'audit',
              level: 'info',
              source: 'backend',
              logger: null,
              actor: 'operator',
              actor_role: 'admin',
              client_id: null,
              feed_source_id: null,
              request_id: 'req-1',
              run_id: null,
              message: 'user.create',
              context: { target_type: 'user' },
            },
          ],
          next_cursor: null,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    render(<SystemLogsPage />);
    await waitFor(() => expect(screen.getByText('user.create')).toBeInTheDocument());
    expect(screen.getByText('operator')).toBeInTheDocument();
  });
});
```

Create `frontend/src/api/hooks.logs.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { renderHook } from '../test/render';
import { useEventLogs } from './hooks';

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
});

describe('useEventLogs', () => {
  it('passes filters as query params', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const { result } = renderHook(() => useEventLogs({ category: 'audit', q: 'login' }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchMock).toHaveBeenCalledWith(
      '/logs/entries?category=audit&q=login',
      expect.objectContaining({ credentials: 'include' }),
    );
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `npm run test -- SystemLogsPage hooks.logs`
Expected: FAIL — `useEventLogs` not exported; page shows coming-soon.

- [x] **Step 3: Add types, keys, hooks, page, routing, settings**

Add to `frontend/src/api/types.ts`:

```ts
export type EventLogEntry = {
  id: number;
  created_at: string;
  category: 'audit' | 'server_error' | 'client_error';
  level: string;
  source: 'backend' | 'frontend';
  logger: string | null;
  actor: string | null;
  actor_role: string | null;
  client_id: number | null;
  feed_source_id: number | null;
  request_id: string | null;
  run_id: number | null;
  message: string;
  context: Record<string, unknown>;
};

export type EventLogPage = { items: EventLogEntry[]; next_cursor: number | null };

export type EventLogFilters = {
  category?: string;
  level?: string;
  source?: string;
  actor?: string;
  request_id?: string;
  q?: string;
  feed_source_id?: number;
  limit?: number;
};
```

Add `event_log_retention_days: number;` to the existing `GlobalSettings` type in the same file.

Add to `frontend/src/api/queryKeys.ts`:

```ts
  eventLogs: (filters: unknown) => ['logs', 'entries', filters] as const,
```

Add to `frontend/src/api/hooks.ts`:

```ts
import { useInfiniteQuery } from '@tanstack/react-query';
import type { EventLogFilters, EventLogPage } from './types';

export function useEventLogs(filters: EventLogFilters) {
  return useInfiniteQuery({
    queryKey: queryKeys.eventLogs(filters),
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(filters)) {
        if (value !== undefined && value !== '') params.set(key, String(value));
      }
      if (pageParam !== undefined) params.set('cursor', String(pageParam));
      const query = params.toString();
      return apiGet<EventLogPage>(`/logs/entries${query ? `?${query}` : ''}`);
    },
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
}
```

Extend `import { ... } from '@tanstack/react-query'` to include `useInfiniteQuery` (do not add a second import line if the existing import already lists names — merge it).

Replace `frontend/src/features/systemLogs/SystemLogsPage.tsx`:

```tsx
import { useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Code,
  Group,
  Select,
  Stack,
  Table,
  TextInput,
  Title,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useEventLogs } from '../../api/hooks';
import type { EventLogEntry } from '../../api/types';
import { ErrorState, LoadingState } from '../../components/StateViews';

const LEVELS = ['debug', 'info', 'warning', 'error', 'critical'];
const CATEGORIES = ['audit', 'server_error', 'client_error'];
const SOURCES = ['backend', 'frontend'];

export function SystemLogsPage() {
  const { t } = useTranslation('systemLogs');
  const [category, setCategory] = useState<string | null>(null);
  const [level, setLevel] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const [actor, setActor] = useState('');
  const [requestId, setRequestId] = useState('');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<number | null>(null);

  const filters = useMemo(
    () => ({
      category: category ?? undefined,
      level: level ?? undefined,
      source: source ?? undefined,
      actor: actor || undefined,
      request_id: requestId || undefined,
      q: search || undefined,
      limit: 50,
    }),
    [category, level, source, actor, requestId, search],
  );

  const query = useEventLogs(filters);

  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState onRetry={() => void query.refetch()} />;

  const items = query.data.pages.flatMap((page) => page.items);

  const renderRow = (entry: EventLogEntry) => (
    <>
      <Table.Tr key={entry.id} onClick={() => setExpanded(expanded === entry.id ? null : entry.id)}>
        <Table.Td>{new Date(entry.created_at).toLocaleString()}</Table.Td>
        <Table.Td>
          <Badge color={entry.level === 'error' ? 'red' : 'gray'}>{entry.level}</Badge>
        </Table.Td>
        <Table.Td>{entry.category}</Table.Td>
        <Table.Td>{entry.source}</Table.Td>
        <Table.Td>{entry.actor ?? ''}</Table.Td>
        <Table.Td>{entry.message}</Table.Td>
      </Table.Tr>
      {expanded === entry.id ? (
        <Table.Tr key={`${entry.id}-detail`}>
          <Table.Td colSpan={6}>
            <Code block>{JSON.stringify(entry, null, 2)}</Code>
          </Table.Td>
        </Table.Tr>
      ) : null}
    </>
  );

  return (
    <Stack pt="md">
      <Title order={3}>{t('title')}</Title>
      <Group align="flex-end">
        <Select
          label={t('filters.category')}
          data={CATEGORIES}
          value={category}
          onChange={setCategory}
          clearable
        />
        <Select
          label={t('filters.level')}
          data={LEVELS}
          value={level}
          onChange={setLevel}
          clearable
        />
        <Select
          label={t('filters.source')}
          data={SOURCES}
          value={source}
          onChange={setSource}
          clearable
        />
        <TextInput
          label={t('filters.actor')}
          value={actor}
          onChange={(event) => setActor(event.currentTarget.value)}
        />
        <TextInput
          label={t('filters.requestId')}
          value={requestId}
          onChange={(event) => setRequestId(event.currentTarget.value)}
        />
        <TextInput
          label={t('filters.search')}
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
        />
      </Group>
      <Table highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('columns.time')}</Table.Th>
            <Table.Th>{t('columns.level')}</Table.Th>
            <Table.Th>{t('columns.category')}</Table.Th>
            <Table.Th>{t('columns.source')}</Table.Th>
            <Table.Th>{t('columns.actor')}</Table.Th>
            <Table.Th>{t('columns.message')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>{items.map(renderRow)}</Table.Tbody>
      </Table>
      {query.hasNextPage ? (
        <Button
          variant="light"
          loading={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {t('loadMore')}
        </Button>
      ) : null}
    </Stack>
  );
}
```

In `frontend/src/app/router.tsx`, move the `logs` route inside the existing `RequireAdmin` block (next to `admin/ai`):

```tsx
              { path: 'logs', element: <SystemLogsPage /> },
```

and remove the old `{ path: 'logs', element: <SystemLogsPage /> }` line outside the admin block.

In `frontend/src/app/AppShell.tsx`, only include the `/logs` nav item when the session role is `admin`. Use the existing `useSession()` result already available in `AppShell` (check the file; if it is not already calling `useSession`, import it from `../api/hooks`). Change the `globalNav` entry to be conditional:

```tsx
  const globalNav = [
    { to: '/', label: t('nav.fleetOverview'), icon: IconDashboard },
    { to: '/#clients', label: t('nav.clients'), icon: IconUsers },
    ...(session.data?.role === 'admin'
      ? [{ to: '/logs', label: t('nav.systemLogs'), icon: IconListDetails }]
      : []),
    { to: '/rules', label: t('nav.globalRules'), icon: IconGavel },
  ];
```

In `frontend/src/features/admin/AdminSettingsPage.tsx`, add a number input for `event_log_retention_days` alongside the existing retention fields, wired to the same form state and save mutation. Follow the exact pattern of the neighboring retention field in that file.

Extend `frontend/public/locales/en/systemLogs.json`:

```json
{
  "title": "System Logs",
  "loadMore": "Load more",
  "filters": {
    "category": "Category",
    "level": "Level",
    "source": "Source",
    "actor": "Actor",
    "requestId": "Request ID",
    "search": "Message contains"
  },
  "columns": {
    "time": "Time",
    "level": "Level",
    "category": "Category",
    "source": "Source",
    "actor": "Actor",
    "message": "Message"
  }
}
```

Apply matching German translations to `frontend/public/locales/de/systemLogs.json` with the same key structure.

- [x] **Step 4: Run tests to verify they pass**

Run: `npm run test -- SystemLogsPage hooks.logs && npm run typecheck`
Expected: PASS; typecheck exit 0.

- [x] **Step 5: Run the frontend gate**

Run: `npm run build`
Expected: exit 0.

- [x] **Step 6: Commit**

```bash
git add frontend/src/api frontend/src/features/systemLogs frontend/src/features/admin/AdminSettingsPage.tsx frontend/src/app/router.tsx frontend/src/app/AppShell.tsx frontend/public/locales
git commit -m "feat(logging): admin system logs viewer and settings retention field"
```

---

# Part 4 — Frontend error capture and correlation

### Task 11: Frontend logger util

**Files:**
- Create: `frontend/src/logging/logger.ts`
- Test: `frontend/src/logging/logger.test.ts`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Produces: `createLogger(scope)`, `captureException(error, context)`, `newRequestId()`, `flushLogs()`, `resetLogQueue()`, `installGlobalErrorHandlers()`, `logger`.
- Consumes: `POST /logs/client` (Task 8).

- [x] **Step 1: Write the failing test**

```ts
// frontend/src/logging/logger.test.ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createLogger,
  flushLogs,
  newRequestId,
  resetLogQueue,
} from './logger';

const beaconMock = vi.fn(() => true);

beforeEach(() => {
  resetLogQueue();
  vi.stubGlobal('navigator', { ...navigator, sendBeacon: beaconMock });
  beaconMock.mockReset();
});

describe('logger', () => {
  it('does not ship debug/info', () => {
    const log = createLogger('test');
    log.info('hello');
    flushLogs();
    expect(beaconMock).not.toHaveBeenCalled();
  });

  it('ships errors with redacted context', () => {
    const log = createLogger('test');
    log.error('failed', { password: 'hunter2', keep: 'value' });
    flushLogs();
    expect(beaconMock).toHaveBeenCalledTimes(1);
    const [url, blob] = beaconMock.mock.calls[0] as unknown as [string, Blob];
    expect(url).toBe('/logs/client');
    return blob.text().then((text) => {
      const payload = JSON.parse(text) as {
        entries: Array<{ context: Record<string, unknown>; level: string }>;
      };
      expect(payload.entries[0].level).toBe('error');
      expect(payload.entries[0].context.password).toBe('[REDACTED]');
      expect(payload.entries[0].context.keep).toBe('value');
    });
  });

  it('generates a request id', () => {
    expect(newRequestId().length).toBeGreaterThan(8);
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `npm run test -- logger`
Expected: FAIL — module does not exist.

- [x] **Step 3: Implement the logger**

```ts
// frontend/src/logging/logger.ts
export type LogLevel = 'debug' | 'info' | 'warn' | 'error';
export type LogContext = Record<string, unknown>;

type LogEntry = {
  level: LogLevel;
  message: string;
  scope: string;
  route: string;
  url: string;
  request_id: string;
  context: LogContext;
  stack?: string;
  timestamp: string;
};

const SENSITIVE = [
  'password',
  'passwd',
  'token',
  'secret',
  'cookie',
  'authorization',
  'api_key',
  'apikey',
  'session',
  'credential',
];
const MAX_VALUE = 2000;
const MAX_DEPTH = 3;
const MAX_BATCH = 10;
const FLUSH_INTERVAL_MS = 5000;

function isSensitive(key: string): boolean {
  const lowered = key.toLowerCase();
  return SENSITIVE.some((marker) => lowered.includes(marker));
}

function truncate(value: string): string {
  return value.length <= MAX_VALUE ? value : `${value.slice(0, MAX_VALUE)}…[truncated]`;
}

function scrub(value: unknown, depth = 0): unknown {
  if (depth >= MAX_DEPTH) return value;
  if (Array.isArray(value)) return value.map((item) => scrub(item, depth + 1));
  if (value !== null && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      out[key] = isSensitive(key) ? '[REDACTED]' : scrub(item, depth + 1);
    }
    return out;
  }
  if (typeof value === 'string') return truncate(value);
  return value;
}

let queue: LogEntry[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;

function flush(): void {
  if (queue.length === 0) return;
  const entries = queue.splice(0, queue.length);
  const body = JSON.stringify({ entries });
  try {
    if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
      navigator.sendBeacon('/logs/client', new Blob([body], { type: 'application/json' }));
      return;
    }
  } catch {
    // fall through to fetch
  }
  void fetch('/logs/client', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    keepalive: true,
    credentials: 'include',
  }).catch(() => undefined);
}

function enqueue(entry: LogEntry): void {
  queue.push(entry);
  if (queue.length >= MAX_BATCH) {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    flush();
    return;
  }
  if (timer === null) {
    timer = setTimeout(() => {
      timer = null;
      flush();
    }, FLUSH_INTERVAL_MS);
  }
}

export function flushLogs(): void {
  flush();
}

export function resetLogQueue(): void {
  queue = [];
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
}

export function newRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

function currentPath(): string {
  return typeof window === 'undefined' ? '' : window.location.pathname;
}

export function createLogger(scope: string) {
  const log = (level: LogLevel, message: string, context: LogContext = {}, error?: unknown) => {
    const safe = scrub(context) as LogContext;
    if (level === 'debug' || level === 'info') {
      console[level](`[${scope}] ${message}`, safe);
      return;
    }
    console[level](`[${scope}] ${message}`, safe, error ?? '');
    enqueue({
      level,
      message: truncate(message),
      scope,
      route: currentPath(),
      url: currentPath(),
      request_id: typeof safe.request_id === 'string' ? safe.request_id : newRequestId(),
      context: safe,
      stack: error instanceof Error ? error.stack?.slice(0, 8000) : undefined,
      timestamp: new Date().toISOString(),
    });
  };
  return {
    debug: (message: string, context?: LogContext) => log('debug', message, context),
    info: (message: string, context?: LogContext) => log('info', message, context),
    warn: (message: string, context?: LogContext, error?: unknown) =>
      log('warn', message, context, error),
    error: (message: string, context?: LogContext, error?: unknown) =>
      log('error', message, context, error),
  };
}

export const logger = createLogger('app');

export function captureException(error: unknown, context: LogContext = {}): void {
  const scope = typeof context.scope === 'string' ? context.scope : 'app';
  const message = error instanceof Error ? error.message : String(error);
  createLogger(scope).error(message, context, error);
}

export function installGlobalErrorHandlers(): void {
  window.addEventListener('error', (event) => {
    createLogger('window').error(
      event.message,
      { url: currentPath() },
      event.error,
    );
  });
  window.addEventListener('unhandledrejection', (event) => {
    createLogger('promise').error(
      'unhandledrejection',
      { url: currentPath() },
      event.reason,
    );
  });
  window.addEventListener('pagehide', flush);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush();
  });
}
```

In `frontend/src/main.tsx`, call the installer before rendering:

```tsx
import './i18n';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { installGlobalErrorHandlers } from './logging/logger';

installGlobalErrorHandlers();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [x] **Step 4: Run test to verify it passes**

Run: `npm run test -- logger`
Expected: PASS (3 tests).

- [x] **Step 5: Commit**

```bash
git add frontend/src/logging frontend/src/main.tsx
git commit -m "feat(logging): frontend logger with batching and redaction"
```

---

### Task 12: API request correlation, failed-call logging, and app error boundary

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/app/AppErrorBoundary.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/api/client.test.ts` (extend), `frontend/src/app/AppErrorBoundary.test.tsx`

**Interfaces:**
- Consumes: `createLogger`, `newRequestId`, `captureException`, `resetLogQueue` (Task 11).
- Produces: every API request carries `X-Request-ID`; failed responses are logged; render errors are reported.

- [x] **Step 1: Write the failing tests**

Append to `frontend/src/api/client.test.ts` (inside the existing `describe`):

```ts
  it('attaches an X-Request-ID header to every request', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ username: 'operator' }));
    await getCurrentUser();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers['X-Request-ID']).toBeTruthy();
  });

  it('logs failed API calls', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'nope' }, 500));
    const logger = await import('../logging/logger');
    const spy = vi.spyOn(logger, 'createLogger');
    await apiGet('/dashboard/summary').catch(() => undefined);
    expect(spy).toHaveBeenCalledWith('api');
  });
```

Add `resetLogQueue` import and call it in the existing `beforeEach` so queued entries do not leak across tests:

```ts
import { resetLogQueue } from '../logging/logger';
```

```ts
beforeEach(() => {
  resetLogQueue();
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
  setUnauthorizedHandler(null);
});
```

Create `frontend/src/app/AppErrorBoundary.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../test/render';
import { AppErrorBoundary } from './AppErrorBoundary';

function Boom(): never {
  throw new Error('kaboom');
}

describe('AppErrorBoundary', () => {
  it('renders a fallback when a child throws', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(
      <AppErrorBoundary>
        <Boom />
      </AppErrorBoundary>,
    );
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `npm run test -- client AppErrorBoundary`
Expected: FAIL — no header; module doesn't exist.

- [x] **Step 3: Implement correlation, logging, and the boundary**

In `frontend/src/api/client.ts`, add the import and a logger:

```ts
import { createLogger, newRequestId } from '../logging/logger';

const apiLogger = createLogger('api');
```

In `request<T>`, replace the fetch and non-ok handling:

```ts
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const requestId = newRequestId();
  const response = await fetch(url, {
    ...init,
    credentials: 'include',
    headers: { ...(init?.headers ?? {}), 'X-Request-ID': requestId },
  });
  if (!response.ok) {
    const authExempt =
      url.startsWith('/auth/login') || url.startsWith('/auth/password');
    if (response.status === 401 && unauthorizedHandler && !authExempt) {
      unauthorizedHandler();
    }
    const error = await parseError(response);
    apiLogger.error(
      'request failed',
      {
        request_id: requestId,
        method: init?.method ?? 'GET',
        url: url.split('?')[0],
        status: response.status,
      },
      error,
    );
    throw error;
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type');
  if (contentType && !contentType.includes('application/json')) {
    throw new ApiError(
      response.status,
      `Unexpected response content type: ${contentType}`,
    );
  }
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}
```

Apply the same header + logging change to `requestWithHeaders<T>` (same pattern; it returns `{ data, headers }`).

Create `frontend/src/app/AppErrorBoundary.tsx`:

```tsx
import { Component, type ReactNode } from 'react';
import { Alert, Button, Stack, Text } from '@mantine/core';
import { captureException } from '../logging/logger';

type Props = { children: ReactNode };
type State = { error: Error | null };

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error): void {
    captureException(error, { scope: 'boundary' });
  }

  render() {
    if (this.state.error !== null) {
      return (
        <Alert color="red" title="Something went wrong" m="md">
          <Stack gap="xs" mt={4}>
            <Text size="sm" c="dimmed">
              An unexpected error occurred. The error has been reported.
            </Text>
            <div>
              <Button size="xs" onClick={() => this.setState({ error: null })}>
                Reload view
              </Button>
            </div>
          </Stack>
        </Alert>
      );
    }
    return this.props.children;
  }
}
```

In `frontend/src/App.tsx`, wrap the provider tree:

```tsx
import { AppErrorBoundary } from './app/AppErrorBoundary';
```

```tsx
export default function App() {
  return (
    <AppErrorBoundary>
      <MantineProvider theme={theme} env={import.meta.env.VITEST ? 'test' : undefined}>
        <Notifications position="bottom-right" limit={5} />
        <LocaleProvider>
          <Suspense
            fallback={
              <Center h="100vh">
                <Loader />
              </Center>
            }
          >
            <AppRouter />
          </Suspense>
        </LocaleProvider>
      </MantineProvider>
    </AppErrorBoundary>
  );
}
```

- [x] **Step 4: Run tests to verify they pass**

Run: `npm run test -- client AppErrorBoundary && npm run typecheck`
Expected: PASS; typecheck exit 0.

- [x] **Step 5: Run the full frontend gate**

Run: `npm run test && npm run build`
Expected: exit 0.

- [x] **Step 6: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/src/app/AppErrorBoundary.tsx frontend/src/app/AppErrorBoundary.test.tsx frontend/src/App.tsx
git commit -m "feat(logging): api request correlation and app error boundary"
```

---

### Task 13: Documentation and ADR

**Files:**
- Create: `docs/decisions/0012-structured-logging-and-audit-trail.md`
- Modify: `backend/docs/architecture.md`
- Modify: `backend/docs/api.md`
- Modify: `backend/docs/data-model.md`
- Modify: `backend/AGENTS.md`
- Modify: `backend/docs/decisions.md`
- Modify: `frontend/docs/architecture.md`
- Modify: `frontend/AGENTS.md`

- [x] **Step 1: Write the ADR**

`docs/decisions/0012-structured-logging-and-audit-trail.md` — follow the format of `docs/decisions/0011-ai-action-rules-plugin.md` (Context / Decision / Consequences). Record: stdlib-first with a structlog bridge (existing call sites unchanged), contextvar propagation (`request_id`/`actor`/`run_id`), one append-only `event_log` table with `category` (audit/server_error/client_error), 180-day configurable retention, `/logs/*` API (not `/logs` because the SPA owns it), admin-only viewer, frontend errors shipped to `/logs/client`.

- [x] **Step 2: Update the docs**

- `backend/docs/architecture.md`: add a "Logging and observability" section — JSON stdout, structlog bridge, contextvars, event_log table and purge.
- `backend/docs/api.md`: document `GET /logs/entries` (admin) and `POST /logs/client`, noting the SPA collision and `/logs/*` prefix.
- `backend/docs/data-model.md`: document the `event_log` table, `category` values, retention, and that `client_id`/`feed_source_id` are plain telemetry integers (not FKs).
- `backend/AGENTS.md`: extend "Error handling & logging" with the request-id/actor/run_id contextvars, redaction processor, and audit helper.
- `backend/docs/decisions.md`: dated entry for the `structlog` addition.
- `frontend/docs/architecture.md`: logger util, error shipping, request-id correlation, and the admin-gated `/logs` page.
- `frontend/AGENTS.md`: note `src/logging/logger.ts` and the error-handling conventions.

- [x] **Step 3: Run the final gate**

Run:
```bash
cd backend && uv run ruff check . ../plugins && uv run mypy . && uv run alembic check && uv run pytest --report-log=.report.jsonl
cd ../frontend && npm run typecheck && npm run test && npm run build
```
Expected: all exit 0.

- [x] **Step 4: Commit**

```bash
git add docs/decisions/0012-structured-logging-and-audit-trail.md backend/docs frontend/docs backend/AGENTS.md frontend/AGENTS.md
git commit -m "docs: structured logging and audit trail"
```

---

## Self-Review

**Spec coverage:** structlog core (Tasks 1–2); redaction (Task 2); request/actor/pipeline contextvars (Tasks 3–4); `event_log` model + retention setting (Tasks 5–6); purge job (Task 7); logs API + Caddy routing (Task 8); audit call sites (Task 9); admin viewer + gating + i18n + retention UI field (Task 10); frontend logger + global handlers (Task 11); correlation + failed-call logging + `AppErrorBoundary` (Task 12); docs/ADR (Task 13). Server-error persistence is implemented in the middleware (Task 3). The spec's "denylist keys + size caps" and "in-memory fixed window" are in Tasks 2 and 8.

**Known deviations from the spec, applied intentionally:**
- `event_log.client_id`/`feed_source_id` are plain nullable integers, not FKs (matches `ai_usage_logs`). The spec file is updated to match.
- The audit "manual run trigger" and export mapping in Task 9 depends on the exact handler names in `export_history.py`; the implementer must locate the POST handler and use `export.publish`. This is the only handler whose name was not confirmed while writing the plan.

**Type consistency:** `record_event`/`audit`/`record_client_error`/`record_server_error` signatures are defined once (Task 6) and used unchanged in Tasks 7–9. `EventLogOut`/`EventLogPage`/`ClientLogBatch` are defined in Task 8 and consumed by Task 10's `EventLogEntry`/`EventLogPage` TypeScript types. `purge_expired_events` returns `EventLogPurgeCounts` with `.rows`, used in Task 7's lifespan job. Frontend `createLogger`/`newRequestId`/`resetLogQueue`/`captureException`/`installGlobalErrorHandlers` are defined in Task 11 and consumed in Task 12.
