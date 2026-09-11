# AI-Provider-Abstraktion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Swappable, resilient LLM interface (`backend/app/ai/`) with DB-backed provider config, hash-keyed result cache, retry/backoff, in-process circuit breaker, per-call cost tracking, and a minimal admin UI (provider settings + usage overview).

**Architecture:** New domain module `backend/app/ai/` (peer of `qc/`, `staging/`, `export/`). `AiService` facade resolves a task from a registry → cache lookup → provider call through resilience layer → usage log → returns `AiResult` that never raises on provider errors (fallback status). Three new tables via one Alembic migration. `AiService` wired in `create_app` lifespan, attached to `app.state.ai_service`; no pipeline-step consumers in this feature.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async (typed `Mapped[]`/`mapped_column`), httpx 0.28.1 (already a dep — no vendor SDK), PostgreSQL JSONB, Alembic, React 19 + Mantine + TanStack Query.

**Spec:** `docs/superpowers/specs/2026-09-11-ai-provider-abstraction-design.md`

## Global Constraints

- Run all commands from `backend/` unless noted. Frontend commands from `frontend/`.
- CI gate (in order): `uv run ruff check .` (exact 508-count baseline — zero new errors), `uv run mypy .` (exit-0, hard gate), `uv run pytest --report-log=.report.jsonl` (jq failure gate).
- Models: typed SQLAlchemy 2.0 style — `Mapped[T]` / `mapped_column(...)`; nested/flexible data is `JSONB`.
- Migrations only via Alembic: `uv run alembic revision --autogenerate -m "..."`; tests run the full migration chain via `pytest-postgresql` template cloning, so **the migration must be created before DB-dependent tests run**.
- Logging: module-level `logger = logging.getLogger(__name__)`, lazy `%s` interpolation in log calls.
- Async: all I/O-bound code is `async def`; one `AsyncSession` per request/task; never share a session across `asyncio.gather` branches.
- Frontend: TanStack Query only for server state (never duplicate into client stores); i18n via JSON files in `frontend/public/locales/<lang>/`; add keys to every existing locale file (`ls frontend/public/locales/` shows all languages — keep them in sync).
- Commit messages: match repo style (`feat:`, `test:`, `docs:` prefixes, concise).
- Never commit secrets or `.env` files. API keys live only in the DB (`ai_provider_configs.api_key`, an accepted DB-backed design decision for this feature — same plaintext posture as the recorded feed-source-credentials MVP decision).
- Any behavior/API/data-model change updates affected docs (`backend/docs/api.md`, `backend/docs/data-model.md`, `backend/docs/architecture.md`) in the same commit.

---

### Task 1: AI provider config, result cache, usage log models + migration

**Files:**
- Create: `backend/app/models/ai.py`
- Create: `backend/alembic/versions/20260911_0001_m13_ai_provider_abstraction.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_ai_models.py`

**Interfaces:**
- Produces: `AiProviderConfig`, `AiResultCache`, `AiUsageLog` SQLAlchemy models (imported via `app.models`), tables `ai_provider_configs`, `ai_result_cache`, `ai_usage_logs` existing in the DB schema.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ai_models.py
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.ai import AiProviderConfig, AiResultCache, AiUsageLog


@pytest_asyncio.fixture
async def session(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_ai_provider_config_round_trip(session):
    async with session.begin():
        session.add(AiProviderConfig(
            name="primary",
            provider_type="openai_compatible",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4o-mini",
            max_concurrency=4,
            timeout_s=30,
            enabled=True,
            is_default=True,
        ))
    async with session.begin():
        row = (await session.execute(
            select(AiProviderConfig).where(AiProviderConfig.name == "primary")
        )).scalar_one()
        assert row.input_price_per_mtok is None
        assert row.output_price_per_mtok is None
        assert row.is_default is True


@pytest.mark.asyncio
async def test_ai_result_cache_unique_key(session):
    async with session.begin():
        session.add(AiProviderConfig(
            name="primary", provider_type="openai_compatible",
            base_url="http://localhost:11434/v1", api_key="",
            model="llama3.3", max_concurrency=2, timeout_s=60,
            enabled=True, is_default=True,
        ))
    async with session.begin():
        config = (await session.execute(select(AiProviderConfig))).scalar_one()
        session.add(AiResultCache(
            task_type="attribute_enrichment", provider_config_id=config.id,
            model="llama3.3", template_version="builtin",
            input_hash="a" * 64, output={"color": "blue"},
        ))
    async with session.begin():
        session.add(AiResultCache(
            task_type="attribute_enrichment", provider_config_id=config.id,
            model="llama3.3", template_version="builtin",
            input_hash="a" * 64, output={"color": "red"},
        ))
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


@pytest.mark.asyncio
async def test_ai_usage_log_round_trip(session):
    async with session.begin():
        session.add(AiUsageLog(
            client_id=1, feed_source_id=None, task_type="policy_check",
            provider_config_id=1, model="gpt-4o-mini", cache_hit=False,
            prompt_tokens=100, completion_tokens=20,
            cost_usd=0.0001, latency_ms=800, error_code=None,
        ))
    async with session.begin():
        row = (await session.execute(select(AiUsageLog))).scalar_one()
        assert row.task_type == "policy_check"
        assert row.feed_source_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_ai_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.ai'` (collection error).

- [ ] **Step 3: Write the models + autogenerate the migration**

Create `backend/app/models/ai.py` following the codebase's typed-column style (see `app/models/quality.py` for the pattern — `Integer, String, ForeignKey, Index, func` imports, `JSONB` from `sqlalchemy.dialects.postgresql`):

```python
# backend/app/models/ai.py
from datetime import datetime
from typing import Any
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class AiProviderConfig(Base):
    __tablename__ = "ai_provider_configs"
    __table_args__ = (UniqueConstraint("name", name="uq_ai_provider_configs_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False, default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    api_key: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    input_price_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    output_price_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AiResultCache(Base):
    __tablename__ = "ai_result_cache"
    __table_args__ = (
        UniqueConstraint(
            "task_type", "provider_config_id", "model", "template_version", "input_hash",
            name="uq_ai_result_cache_key",
        ),
        Index("ix_ai_result_cache_input_hash", "input_hash"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_config_id: Mapped[int] = mapped_column(ForeignKey("ai_provider_configs.id", ondelete="CASCADE"), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    template_version: Mapped[str] = mapped_column(String(100), nullable=False, default="builtin")
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AiUsageLog(Base):
    __tablename__ = "ai_usage_logs"
    __table_args__ = (
        Index("ix_ai_usage_logs_client_id", "client_id"),
        Index("ix_ai_usage_logs_feed_source_id", "feed_source_id"),
        Index("ix_ai_usage_logs_created_at", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feed_source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_config_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

Then in `backend/app/models/__init__.py` add the import (follow the existing import-list style there):

```python
from .ai import AiProviderConfig, AiResultCache, AiUsageLog
```

Generate the migration (needs a live PostgreSQL — use the compose one):

```bash
cd backend && docker compose up -d postgres && \
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed \
  uv run alembic revision --autogenerate -m "m13 ai provider abstraction"
```

Open the generated file (name starts with the date, e.g. `20260911_0001_m13_ai_provider_abstraction.py`), set `down_revision` to `'20260909_0001'` (the current head — verify with `uv run alembic heads`), and confirm it contains three `op.create_table` calls (ai_provider_configs, ai_result_cache, ai_usage_logs) with the unique constraints and indexes. Rename the file to match the `20260911_0001_m13_...` convention if autogenerate chose a different prefix.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/test_ai_models.py -v
```
Expected: 3 passed. (The `isolated_database_url` fixture clones the template DB with the full migration chain — proving the migration applies cleanly.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/ai.py backend/app/models/__init__.py backend/alembic/versions/20260911_0001_m13_ai_provider_abstraction.py backend/tests/test_ai_models.py
git commit -m "feat: ai provider/cache/usage models and migration (m13)"
```

---

### Task 2: `AIProvider` protocol, task registry, builtin renderers/validators

**Files:**
- Create: `backend/app/ai/__init__.py`
- Create: `backend/app/ai/provider.py`
- Create: `backend/app/ai/tasks.py`
- Test: `backend/tests/test_ai_tasks.py`

**Interfaces:**
- Produces (used by Tasks 4–6):
  - `app.ai.provider.AIProvider` Protocol with `async def complete(self, request: AiRequest) -> AiResponse`
  - `app.ai.provider.AiRequest(task_type: str, messages: list[dict[str, str]], response_format: dict[str, Any] | None, max_tokens: int, temperature: float)` (frozen dataclass)
  - `app.ai.provider.AiResponse(content: str, prompt_tokens: int, completion_tokens: int, model: str, latency_ms: int)` (frozen dataclass)
  - `app.ai.tasks.TaskSpec(render, validate)`, `app.ai.tasks.TASK_SPECS: dict[str, TaskSpec]`, `app.ai.tasks.TaskSpecError`
  - `app.ai.tasks.render_task(task_type: str, variables: dict[str, Any]) -> list[dict[str, str]]`
  - `app.ai.tasks.validate_task(task_type: str, content: str) -> Any`
  - `app.ai.tasks.input_hash(task_type: str, variables: dict[str, Any]) -> str` — sha256 over canonical JSON (reuses `app.staging.hashing.canonical_json`)
  - Task types: `title_optimization`, `category_classification`, `policy_check`, `attribute_enrichment`, `image_quality`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ai_tasks.py
from __future__ import annotations

import pytest

from app.ai.tasks import (
    TASK_SPECS,
    TaskSpecError,
    input_hash,
    render_task,
    validate_task,
)

EXPECTED_TASK_TYPES = {
    "title_optimization",
    "category_classification",
    "policy_check",
    "attribute_enrichment",
    "image_quality",
}


def test_registry_has_all_task_types():
    assert set(TASK_SPECS) == EXPECTED_TASK_TYPES


def test_render_task_builds_messages():
    messages = render_task("title_optimization", {"title": "Running Shoe", "brand": "Acme"})
    assert isinstance(messages, list)
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user"]
    assert "Running Shoe" in messages[1]["content"]


def test_render_task_unknown_type_raises():
    with pytest.raises(TaskSpecError):
        render_task("nonexistent_task", {})


def test_validate_task_parses_json():
    value = validate_task("attribute_enrichment", '{"color": "blue"}')
    assert value == {"color": "blue"}


def test_validate_task_invalid_json_raises():
    with pytest.raises(TaskSpecError):
        validate_task("attribute_enrichment", "not json at all")


def test_input_hash_stable_and_content_sensitive():
    a = input_hash("attribute_enrichment", {"title": "Blue Shirt"})
    b = input_hash("attribute_enrichment", {"title": "Blue Shirt"})
    c = input_hash("attribute_enrichment", {"title": "Red Shirt"})
    assert a == b
    assert a != c


def test_input_hash_key_order_insensitive():
    a = input_hash("policy_check", {"title": "T", "description": "D"})
    b = input_hash("policy_check", {"description": "D", "title": "T"})
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_ai_tasks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai'`.

- [ ] **Step 3: Write the implementation**

```python
# backend/app/ai/__init__.py
from .provider import AIProvider, AiRequest, AiResponse
from .tasks import TASK_SPECS, TaskSpec, TaskSpecError

__all__ = [
    "AIProvider", "AiRequest", "AiResponse",
    "TASK_SPECS", "TaskSpec", "TaskSpecError",
]
```

```python
# backend/app/ai/provider.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AiRequest:
    task_type: str
    messages: list[dict[str, str]]
    response_format: dict[str, Any] | None = None
    max_tokens: int = 1024
    temperature: float = 0.0


@dataclass(frozen=True)
class AiResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    latency_ms: int


@runtime_checkable
class AIProvider(Protocol):
    async def complete(self, request: AiRequest) -> AiResponse: ...
```

```python
# backend/app/ai/tasks.py
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable

from ..staging.hashing import canonical_json


class TaskSpecError(ValueError):
    """Raised for unknown task types or invalid model output."""


@dataclass(frozen=True)
class TaskSpec:
    render: Callable[[dict[str, Any]], list[dict[str, str]]]
    validate: Callable[[str], Any]


def _render(system: str, user: str) -> Callable[[dict[str, Any]], list[dict[str, str]]]:
    def _renderer(variables: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user.format(**variables)},
        ]

    return _renderer


def _validate_json(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise TaskSpecError("model output is not valid JSON") from exc


def _validate_text(content: str) -> str:
    return content.strip()


# Builtin defaults — Feature 2 replaces these with versioned DB templates;
# the registry is the seam.
TASK_SPECS: dict[str, TaskSpec] = {
    "title_optimization": TaskSpec(
        render=_render(
            "You rewrite product titles for Google Merchant Center. "
            "Reply with the optimized title only, no explanations.",
            "Brand: {brand}\nCurrent title: {title}\n"
            "Rewrite the title to be concise and search-friendly.",
        ),
        validate=_validate_text,
    ),
    "category_classification": TaskSpec(
        render=_render(
            "You classify products into Google product categories. "
            "Reply with the category path only.",
            "Title: {title}\nDescription: {description}\nClassify.",
        ),
        validate=_validate_text,
    ),
    "policy_check": TaskSpec(
        render=_render(
            "You check product data against Google Merchant Center policies. "
            'Reply with JSON: {"violations": [{"rule": string, "reason": string}], '
            '"confidence": number between 0 and 1}. No other text.',
            "Title: {title}\nDescription: {description}\nCheck for policy violations.",
        ),
        validate=_validate_json,
    ),
    "attribute_enrichment": TaskSpec(
        render=_render(
            "You extract product attributes from free text. "
            'Reply with JSON: {"color": string|null, "material": string|null, '
            '"size": string|null, "gtin": string|null}. No other text.',
            "Title: {title}\nDescription: {description}\nExtract the attributes.",
        ),
        validate=_validate_json,
    ),
    "image_quality": TaskSpec(
        render=_render(
            "You assess product images for Google Merchant Center. "
            'Reply with JSON: {"watermark": boolean, "text_overlay": boolean, '
            '"background": string, "confidence": number}. No other text.',
            "Image URL: {image_link}\nAssess the image.",
        ),
        validate=_validate_json,
    ),
}


def render_task(task_type: str, variables: dict[str, Any]) -> list[dict[str, str]]:
    try:
        spec = TASK_SPECS[task_type]
    except KeyError as exc:
        raise TaskSpecError(f"unknown task type {task_type!r}") from exc
    try:
        return spec.render(variables)
    except KeyError as exc:
        raise TaskSpecError(f"missing variable {exc.args[0]!r} for task {task_type!r}") from exc


def validate_task(task_type: str, content: str) -> Any:
    try:
        spec = TASK_SPECS[task_type]
    except KeyError as exc:
        raise TaskSpecError(f"unknown task type {task_type!r}") from exc
    return spec.validate(content)


def input_hash(task_type: str, variables: dict[str, Any]) -> str:
    payload = canonical_json({"task_type": task_type, "variables": variables})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_ai_tasks.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/__init__.py backend/app/ai/provider.py backend/app/ai/tasks.py backend/tests/test_ai_tasks.py
git commit -m "feat: ai provider protocol and task registry"
```

---

### Task 3: Resilience layer — retry/backoff and circuit breaker

**Files:**
- Create: `backend/app/ai/resilience.py`
- Test: `backend/tests/test_ai_resilience.py`

**Interfaces:**
- Consumes: `app.clock.Clock` (`now() -> datetime`, already exists — `TestClock` in tests).
- Produces (used by Task 5):
  - `app.ai.resilience.CallOutcome` (enum: `OK`, `RATE_LIMITED`, `TIMEOUT`, `SERVER_ERROR`)
  - `app.ai.resilience.CircuitBreaker(failure_threshold: int = 5, window_s: int = 60, cooldown_s: int = 30, clock: Clock)` — methods `allow_call() -> bool`, `record_success()`, `record_failure()`, property `is_open -> bool`
  - `app.ai.resilience.RetryPolicy(max_attempts: int = 3, base_delay_s: float = 0.5, max_delay_s: float = 8.0, jitter: float = 0.25)` — method `delay_for_attempt(attempt: int) -> float` (1-based)
  - `app.ai.resilience.classify_failure(exc: Exception) -> tuple[CallOutcome, bool]` — returns `(outcome, retryable)`; retryable=True for 429/timeout/5xx/connection errors, False for everything else (4xx, invalid responses)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ai_resilience.py
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.ai.resilience import (
    CallOutcome,
    CircuitBreaker,
    RetryPolicy,
    classify_failure,
)
from app.clock import TestClock


def _clock() -> TestClock:
    return TestClock(datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_breaker_opens_after_threshold_failures():
    clock = _clock()
    breaker = CircuitBreaker(failure_threshold=3, window_s=60, cooldown_s=30, clock=clock)
    assert breaker.allow_call()
    for _ in range(3):
        breaker.record_failure()
    assert breaker.is_open
    assert not breaker.allow_call()


def test_breaker_half_open_after_cooldown_then_closes_on_success():
    clock = _clock()
    breaker = CircuitBreaker(failure_threshold=2, window_s=60, cooldown_s=30, clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.is_open
    clock.advance(seconds=31)
    assert breaker.allow_call()  # half-open probe
    breaker.record_success()
    assert not breaker.is_open
    assert breaker.allow_call()


def test_breaker_stays_open_inside_cooldown():
    clock = _clock()
    breaker = CircuitBreaker(failure_threshold=2, window_s=60, cooldown_s=30, clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    clock.advance(seconds=10)
    assert not breaker.allow_call()


def test_breaker_failure_window_expires():
    clock = _clock()
    breaker = CircuitBreaker(failure_threshold=3, window_s=60, cooldown_s=30, clock=clock)
    breaker.record_failure()
    clock.advance(seconds=61)
    breaker.record_failure()
    breaker.record_failure()
    # 3 failures did not accumulate inside a 60s window -> still closed
    assert not breaker.is_open


def test_retry_policy_delay_bounds():
    policy = RetryPolicy(max_attempts=3, base_delay_s=0.5, max_delay_s=8.0, jitter=0.25)
    assert 0.25 <= policy.delay_for_attempt(1) <= 0.75   # 0.5 ± 25%
    assert 1.0 <= policy.delay_for_attempt(2) <= 2.0     # 1.0 ± 25%
    assert 2.0 <= policy.delay_for_attempt(3) <= 4.0     # 2.0 ± 25%


def test_classify_failure_rate_limit_retryable():
    exc = httpx.HTTPStatusError(
        "rate limited", request=httpx.Request("POST", "http://x"),
        response=httpx.Response(429),
    )
    outcome, retryable = classify_failure(exc)
    assert outcome is CallOutcome.RATE_LIMITED
    assert retryable


def test_classify_failure_timeout_retryable():
    outcome, retryable = classify_failure(httpx.TimeoutException("timed out"))
    assert outcome is CallOutcome.TIMEOUT
    assert retryable


def test_classify_failure_server_error_retryable():
    exc = httpx.HTTPStatusError(
        "boom", request=httpx.Request("POST", "http://x"),
        response=httpx.Response(500),
    )
    outcome, retryable = classify_failure(exc)
    assert outcome is CallOutcome.SERVER_ERROR
    assert retryable


def test_classify_failure_client_error_not_retryable():
    exc = httpx.HTTPStatusError(
        "bad request", request=httpx.Request("POST", "http://x"),
        response=httpx.Response(400),
    )
    outcome, retryable = classify_failure(exc)
    assert outcome is CallOutcome.CLIENT_ERROR
    assert not retryable
```

Note: the test file uses `CallOutcome.CLIENT_ERROR` — include it in the enum (4 members: `OK`, `RATE_LIMITED`, `TIMEOUT`, `SERVER_ERROR`, `CLIENT_ERROR` — 5 members total).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_ai_resilience.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.resilience'`.

- [ ] **Step 3: Write the implementation**

```python
# backend/app/ai/resilience.py
from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

import httpx


class CallOutcome(Enum):
    OK = "ok"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"


class _ClockLike(Protocol):
    def now(self) -> datetime: ...


def _utcnow(clock: _ClockLike | None) -> datetime:
    if clock is not None:
        return clock.now()
    return datetime.now(timezone.utc)


class CircuitBreaker:
    """In-process, per-provider-config circuit breaker.

    closed -> open: `failure_threshold` failures within `window_s`
    open -> half-open: `cooldown_s` elapsed
    half-open -> closed: one successful probe
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        window_s: int = 60,
        cooldown_s: int = 30,
        clock: _ClockLike | None = None,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._window_s = window_s
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._failures: deque[datetime] = deque()
        self._opened_at: datetime | None = None
        self._half_open = False

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None

    def allow_call(self) -> bool:
        if self._opened_at is None:
            return True
        elapsed = (_utcnow(self._clock) - self._opened_at).total_seconds()
        if elapsed >= self._cooldown_s:
            self._half_open = True
            return True  # probe
        return False

    def record_success(self) -> None:
        self._failures.clear()
        self._opened_at = None
        self._half_open = False

    def record_failure(self) -> None:
        now = _utcnow(self._clock)
        self._failures.append(now)
        cutoff = now.timestamp() - self._window_s
        while self._failures and self._failures[0].timestamp() < cutoff:
            self._failures.popleft()
        if self._half_open or len(self._failures) >= self._failure_threshold:
            self._opened_at = now
            self._half_open = False


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    jitter: float = 0.25

    def delay_for_attempt(self, attempt: int) -> float:
        """1-based attempt -> delay before that attempt's retry (exp backoff + jitter)."""
        delay = min(self.base_delay_s * (2 ** (attempt - 1)), self.max_delay_s)
        spread = delay * self.jitter
        return max(0.0, delay + random.uniform(-spread, spread))


def classify_failure(exc: Exception) -> tuple[CallOutcome, bool]:
    """Classify a provider exception into (outcome, retryable)."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return CallOutcome.RATE_LIMITED, True
        if status >= 500:
            return CallOutcome.SERVER_ERROR, True
        return CallOutcome.CLIENT_ERROR, False
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout)):
        return CallOutcome.TIMEOUT, True
    return CallOutcome.CLIENT_ERROR, False
```

Note: the enum has 5 members — `OK`, `RATE_LIMITED`, `TIMEOUT`, `SERVER_ERROR`, `CLIENT_ERROR`. `OK` is included so `CallOutcome` covers the success path for callers that classify every call uniformly.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_ai_resilience.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/resilience.py backend/tests/test_ai_resilience.py
git commit -m "feat: ai retry policy and circuit breaker"
```

---

### Task 4: OpenAI-compatible provider (httpx, no SDK)

**Files:**
- Create: `backend/app/ai/openai_compat.py`
- Test: `backend/tests/test_ai_openai_compat.py`

**Interfaces:**
- Consumes: `app.ai.provider.AIProvider`, `AiRequest`, `AiResponse` (Task 2).
- Produces (used by Task 5): `app.ai.openai_compat.OpenAICompatibleProvider(base_url: str, api_key: str, model: str, timeout_s: int = 30, client: httpx.AsyncClient | None = None)`. The optional `client` parameter enables `httpx.MockTransport` in tests and lets `create_app` share its `app.state.image_http_client`-style lifecycle (provider owns the client only when it creates one).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ai_openai_compat.py
from __future__ import annotations

import httpx
import pytest

from app.ai.openai_compat import OpenAICompatibleProvider
from app.ai.provider import AiRequest


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_complete_posts_chat_completions_and_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openai.com"
        assert request.headers["authorization"] == "Bearer sk-test"
        body = request.read()
        import json
        payload = json.loads(body)
        assert payload["model"] == "gpt-4o-mini"
        assert payload["messages"][0]["role"] == "system"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "Optimized Title"}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 7},
        })

    provider = OpenAICompatibleProvider(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o-mini",
        client=_mock_client(handler),
    )
    request = AiRequest(
        task_type="title_optimization",
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
    )
    response = await provider.complete(request)
    assert response.content == "Optimized Title"
    assert response.prompt_tokens == 42
    assert response.completion_tokens == 7
    assert response.model == "gpt-4o-mini"
    assert response.latency_ms >= 0


@pytest.mark.asyncio
async def test_complete_passes_response_format_when_set():
    def handler(request: httpx.Request) -> httpx.Response:
        import json
        payload = json.loads(request.read())
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })

    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1",
        api_key="",
        model="llama3.3",
        client=_mock_client(handler),
    )
    request = AiRequest(
        task_type="attribute_enrichment",
        messages=[{"role": "user", "content": "u"}],
        response_format={"type": "json_object"},
    )
    response = await provider.complete(request)
    assert response.content == "{}"


@pytest.mark.asyncio
async def test_complete_rate_limit_raises_http_status_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    provider = OpenAICompatibleProvider(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o-mini",
        client=_mock_client(handler),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await provider.complete(AiRequest(
            task_type="title_optimization",
            messages=[{"role": "user", "content": "u"}],
        ))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_ai_openai_compat.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.openai_compat'`.

- [ ] **Step 3: Write the implementation**

```python
# backend/app/ai/openai_compat.py
from __future__ import annotations

import time

import httpx

from .provider import AiRequest, AiResponse


class OpenAICompatibleProvider:
    """Chat-completions client for OpenAI-compatible APIs.

    Covers OpenAI itself and self-hosted servers exposing the same
    protocol (vLLM, Ollama, LM Studio) via `base_url`.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: int = 30,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s
        self._client = client
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def complete(self, request: AiRequest) -> AiResponse:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
            self._owns_client = True
        payload: dict[str, object] = {
            "model": self._model,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.response_format is not None:
            payload["response_format"] = request.response_format
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        started = time.monotonic()
        response = await self._client.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        latency_ms = int((time.monotonic() - started) * 1000)
        return AiResponse(
            content=data["choices"][0]["message"]["content"],
            prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
            completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
            model=data.get("model", self._model),
            latency_ms=latency_ms,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_ai_openai_compat.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/openai_compat.py backend/tests/test_ai_openai_compat.py
git commit -m "feat: openai-compatible provider via httpx"
```

---

### Task 5: DB result cache + usage log persistence

**Files:**
- Create: `backend/app/ai/cache.py`
- Create: `backend/app/ai/usage.py`
- Test: `backend/tests/test_ai_cache_usage.py`

**Interfaces:**
- Consumes: `AiResultCache`, `AiUsageLog` models (Task 1); `app.ai.tasks.input_hash` (Task 2).
- Produces (used by Task 6):
  - `app.ai.cache.CacheEntry(output: dict[str, Any])`; `app.ai.cache.AiResultCacheStore(session_factory) -> .lookup(task_type, provider_config_id, model, template_version, input_hash) -> CacheEntry | None` and `.store(task_type, provider_config_id, model, template_version, input_hash, output)` (integrity violations on the unique key — concurrent inserts of same key — are swallowed: cache write failure never fails a call)
  - `app.ai.usage.UsageRecord` dataclass with fields matching `AiUsageLog` columns (`client_id`, `feed_source_id`, `task_type`, `provider_config_id`, `model`, `cache_hit`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `latency_ms`, `error_code`); `app.ai.usage.UsageLogWriter(session_factory) -> .write(record: UsageRecord)` (own short transaction; failures logged, never raised)
  - `app.ai.usage.estimate_cost(prompt_tokens, completion_tokens, input_price_per_mtok, output_price_per_mtok) -> Decimal | None` (None when either price is None)
  - `app.ai.usage.aggregate_usage(session, client_id=None, feed_source_id=None, task_type=None, from_dt=None, to_dt=None, group_by="client") -> list[dict]` — groups per the `group_by` param (`client`, `feed_source`, `task_type`, `day`), returning rows with `group_key`, `calls`, `cache_hits`, `prompt_tokens`, `completion_tokens`, `cost_usd`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ai_cache_usage.py
from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.cache import AiResultCacheStore
from app.ai.usage import UsageLogWriter, UsageRecord, aggregate_usage, estimate_cost
from app.models.ai import AiProviderConfig, AiUsageLog
from app.models.global_setting import GlobalSetting


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def config_id(session_factory):
    async with session_factory() as session:
        async with session.begin():
            config = AiProviderConfig(
                name="primary", provider_type="openai_compatible",
                base_url="https://api.openai.com/v1", api_key="sk-test",
                model="gpt-4o-mini", max_concurrency=4, timeout_s=30,
                enabled=True, is_default=True,
            )
            session.add(config)
            await session.flush()
            return config.id


@pytest.mark.asyncio
async def test_cache_store_and_lookup_round_trip(session_factory, config_id):
    store = AiResultCacheStore(session_factory)
    hit = await store.lookup(
        "attribute_enrichment", config_id, "gpt-4o-mini", "builtin", "a" * 64
    )
    assert hit is None
    await store.store(
        "attribute_enrichment", config_id, "gpt-4o-mini", "builtin", "a" * 64,
        {"color": "blue"},
    )
    hit = await store.lookup(
        "attribute_enrichment", config_id, "gpt-4o-mini", "builtin", "a" * 64
    )
    assert hit is not None
    assert hit.output == {"color": "blue"}


@pytest.mark.asyncio
async def test_cache_lookup_misses_on_different_template_version(session_factory, config_id):
    store = AiResultCacheStore(session_factory)
    await store.store(
        "attribute_enrichment", config_id, "gpt-4o-mini", "builtin", "a" * 64,
        {"color": "blue"},
    )
    assert await store.lookup(
        "attribute_enrichment", config_id, "gpt-4o-mini", "v2", "a" * 64
    ) is None


@pytest.mark.asyncio
async def test_cache_store_duplicate_key_does_not_raise(session_factory, config_id):
    store = AiResultCacheStore(session_factory)
    await store.store(
        "attribute_enrichment", config_id, "gpt-4o-mini", "builtin", "a" * 64,
        {"color": "blue"},
    )
    # Concurrent insert of the same key must be swallowed, not raised.
    await store.store(
        "attribute_enrichment", config_id, "gpt-4o-mini", "builtin", "a" * 64,
        {"color": "red"},
    )


@pytest.mark.asyncio
async def test_usage_writer_persists_row(session_factory):
    writer = UsageLogWriter(session_factory)
    await writer.write(UsageRecord(
        client_id=7, feed_source_id=None, task_type="policy_check",
        provider_config_id=1, model="gpt-4o-mini", cache_hit=False,
        prompt_tokens=100, completion_tokens=20,
        cost_usd=Decimal("0.000100"), latency_ms=800, error_code=None,
    ))
    async with session_factory() as session:
        rows = list((await session.execute(select(AiUsageLog))).scalars())
        assert len(rows) == 1
        assert rows[0].client_id == 7
        assert rows[0].cost_usd == Decimal("0.000100")


@pytest.mark.asyncio
async def test_usage_writer_never_raises_on_db_error(session_factory):
    async def broken_factory():
        raise RuntimeError("db down")
    writer = UsageLogWriter(broken_factory)  # type: ignore[arg-type]
    await writer.write(UsageRecord(
        client_id=None, feed_source_id=None, task_type="policy_check",
        provider_config_id=None, model="x", cache_hit=False,
        prompt_tokens=0, completion_tokens=0, cost_usd=None,
        latency_ms=0, error_code="timeout",
    ))  # must not raise


def test_estimate_cost_with_prices():
    cost = estimate_cost(1_000_000, 500_000, Decimal("0.15"), Decimal("0.60"))
    assert cost == Decimal("0.450000")


def test_estimate_cost_without_prices_is_none():
    assert estimate_cost(100, 50, None, Decimal("0.60")) is None
    assert estimate_cost(100, 50, Decimal("0.15"), None) is None


@pytest.mark.asyncio
async def test_aggregate_usage_group_by_client(session_factory):
    writer = UsageLogWriter(session_factory)
    for client_id in (7, 7, 9):
        await writer.write(UsageRecord(
            client_id=client_id, feed_source_id=None, task_type="policy_check",
            provider_config_id=1, model="gpt-4o-mini", cache_hit=False,
            prompt_tokens=100, completion_tokens=20,
            cost_usd=Decimal("0.000100"), latency_ms=800, error_code=None,
        ))
    async with session_factory() as session:
        rows = await aggregate_usage(session, group_by="client")
    by_key = {r["group_key"]: r for r in rows}
    assert by_key[7]["calls"] == 2
    assert by_key[9]["calls"] == 1
    assert by_key[7]["prompt_tokens"] == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_ai_cache_usage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.cache'`.

- [ ] **Step 3: Write the implementation**

```python
# backend/app/ai/cache.py
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.ai import AiResultCache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheEntry:
    output: dict[str, Any]


class AiResultCacheStore:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    async def lookup(
        self,
        task_type: str,
        provider_config_id: int,
        model: str,
        template_version: str,
        input_hash_value: str,
    ) -> CacheEntry | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(AiResultCache.output).where(
                    AiResultCache.task_type == task_type,
                    AiResultCache.provider_config_id == provider_config_id,
                    AiResultCache.model == model,
                    AiResultCache.template_version == template_version,
                    AiResultCache.input_hash == input_hash_value,
                )
            )
            output = result.scalar_one_or_none()
        if output is None:
            return None
        return CacheEntry(output=dict(output) if output else {})

    async def store(
        self,
        task_type: str,
        provider_config_id: int,
        model: str,
        template_version: str,
        input_hash_value: str,
        output: dict[str, Any],
    ) -> None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add(AiResultCache(
                        task_type=task_type,
                        provider_config_id=provider_config_id,
                        model=model,
                        template_version=template_version,
                        input_hash=input_hash_value,
                        output=output,
                    ))
        except IntegrityError:
            # Concurrent insert of the same cache key — the first writer won.
            logger.debug("ai cache: concurrent insert swallowed for %s", input_hash_value)
        except Exception:
            # Cache write failure must never fail the AI call.
            logger.exception("ai cache: write failed for %s", input_hash_value)
```

```python
# backend/app/ai/usage.py
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.ai import AiUsageLog

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UsageRecord:
    client_id: int | None
    feed_source_id: int | None
    task_type: str
    provider_config_id: int | None
    model: str
    cache_hit: bool
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal | None
    latency_ms: int
    error_code: str | None


class UsageLogWriter:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    async def write(self, record: UsageRecord) -> None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add(AiUsageLog(**dataclass_fields(record)))
        except Exception:
            # Usage logging must never fail the AI call.
            logger.exception("ai usage log write failed for task %s", record.task_type)


def dataclass_fields(record: UsageRecord) -> dict[str, Any]:
    return {
        "client_id": record.client_id,
        "feed_source_id": record.feed_source_id,
        "task_type": record.task_type,
        "provider_config_id": record.provider_config_id,
        "model": record.model,
        "cache_hit": record.cache_hit,
        "prompt_tokens": record.prompt_tokens,
        "completion_tokens": record.completion_tokens,
        "cost_usd": record.cost_usd,
        "latency_ms": record.latency_ms,
        "error_code": record.error_code,
    }


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    input_price_per_mtok: Decimal | None,
    output_price_per_mtok: Decimal | None,
) -> Decimal | None:
    if input_price_per_mtok is None or output_price_per_mtok is None:
        return None
    return (
        Decimal(prompt_tokens) * input_price_per_mtok / Decimal(1_000_000)
        + Decimal(completion_tokens) * output_price_per_mtok / Decimal(1_000_000)
    ).quantize(Decimal("0.000001"))


_GROUP_COLUMNS = {
    "client": AiUsageLog.client_id,
    "feed_source": AiUsageLog.feed_source_id,
    "task_type": AiUsageLog.task_type,
    "day": func.date(AiUsageLog.created_at),
}


async def aggregate_usage(
    session: AsyncSession,
    *,
    client_id: int | None = None,
    feed_source_id: int | None = None,
    task_type: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    group_by: str = "client",
) -> list[dict[str, Any]]:
    group_column = _GROUP_COLUMNS[group_by]
    statement = (
        select(
            group_column.label("group_key"),
            func.count().label("calls"),
            func.sum(case((AiUsageLog.cache_hit.is_(True), 1), else_=0)).label("cache_hits"),
            func.coalesce(func.sum(AiUsageLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(AiUsageLog.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(AiUsageLog.cost_usd), 0).label("cost_usd"),
        )
        .group_by(group_column)
        .order_by(group_column)
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
    result = await session.execute(statement)
    return [dict(row._mapping) for row in result.all()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_ai_cache_usage.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/cache.py backend/app/ai/usage.py backend/tests/test_ai_cache_usage.py
git commit -m "feat: ai result cache store and usage logging"
```

---

### Task 6: `AiService` facade — resolve → cache → call → validate → log → fallback

**Files:**
- Create: `backend/app/ai/service.py`
- Modify: `backend/app/ai/__init__.py`
- Test: `backend/tests/test_ai_service.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5. Also `app.clock.Clock`.
- Produces (used by Task 7 for app wiring, and by Features 4/5 later):
  - `app.ai.service.AiResult(value: Any, status: str, error_code: str | None, prompt_tokens: int, completion_tokens: int)` (frozen dataclass; `status` in `{"ok", "cache_hit", "fallback"}`)
  - `app.ai.service.AiService(session_factory, clock: Clock | None = None, provider_factory: Callable[[AiProviderConfig], AIProvider] | None = None)` — the factory parameter is the provider-swap seam (tests inject `FakeProvider`; default builds `OpenAICompatibleProvider` from the config row)
  - `await service.run_task(task_type, variables, *, client_id=None, feed_source_id=None) -> AiResult`
  - `await service.test_provider(config_id: int) -> dict` — live probe (`{"status": "ok", "latency_ms": int, "prompt_tokens": int, "completion_tokens": int}` or `{"status": "error", "error_code": str}`)
  - Internal default factory: `app.ai.service.default_provider_factory(config: AiProviderConfig) -> OpenAICompatibleProvider`

**Error-code contract** (assert in tests): `"no_provider"` (no enabled default config), `"circuit_open"`, `"rate_limited"`, `"timeout"`, `"server_error"`, `"client_error"`, `"invalid_response"`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ai_service.py
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.provider import AiRequest, AiResponse
from app.ai.service import AiResult, AiService, default_provider_factory
from app.models.ai import AiProviderConfig


class FakeProvider:
    """Test double recording calls, returning canned responses or raising."""

    def __init__(self, responses=None, errors=None):
        self.responses = list(responses or [])
        self.errors = list(errors or [])
        self.calls: list[AiRequest] = []

    async def complete(self, request: AiRequest) -> AiResponse:
        self.calls.append(request)
        if self.errors:
            raise self.errors.pop(0)
        content, tokens = self.responses.pop(0)
        return AiResponse(
            content=content, prompt_tokens=tokens[0], completion_tokens=tokens[1],
            model="fake", latency_ms=5,
        )


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_default_config(session_factory) -> int:
    async with session_factory() as session:
        async with session.begin():
            config = AiProviderConfig(
                name="primary", provider_type="openai_compatible",
                base_url="https://api.openai.com/v1", api_key="sk-test",
                model="gpt-4o-mini", max_concurrency=4, timeout_s=1,
                enabled=True, is_default=True,
            )
            session.add(config)
            await session.flush()
            return config.id


@pytest.mark.asyncio
async def test_run_task_ok_and_cached_on_second_call(session_factory):
    await _seed_default_config(session_factory)
    provider = FakeProvider(
        responses=[('{"color": "blue"}', (50, 10))],
    )
    service = AiService(session_factory, provider_factory=lambda config: provider)
    variables = {"title": "Blue Cotton Shirt", "description": "A shirt"}

    first = await service.run_task("attribute_enrichment", variables)
    assert first.status == "ok"
    assert first.value == {"color": "blue"}
    assert first.prompt_tokens == 50
    assert len(provider.calls) == 1

    second = await service.run_task("attribute_enrichment", variables)
    assert second.status == "cache_hit"
    assert second.value == {"color": "blue"}
    assert second.prompt_tokens == 0
    assert len(provider.calls) == 1  # no second provider call


@pytest.mark.asyncio
async def test_run_task_no_provider_returns_fallback(session_factory):
    service = AiService(session_factory, provider_factory=lambda config: FakeProvider())
    result = await service.run_task("attribute_enrichment", {"title": "T", "description": "D"})
    assert result.status == "fallback"
    assert result.error_code == "no_provider"
    assert result.value is None


@pytest.mark.asyncio
async def test_run_task_retries_rate_limit_then_falls_back(session_factory):
    await _seed_default_config(session_factory)
    limit_error = httpx.HTTPStatusError(
        "rate limited", request=httpx.Request("POST", "http://x"),
        response=httpx.Response(429),
    )
    provider = FakeProvider(errors=[limit_error, limit_error, limit_error])
    service = AiService(
        session_factory,
        provider_factory=lambda config: provider,
        retry_policy=__import__("app.ai.resilience", fromlist=["RetryPolicy"]).RetryPolicy(
            max_attempts=3, base_delay_s=0.0, jitter=0.0
        ),
    )
    result = await service.run_task("attribute_enrichment", {"title": "T", "description": "D"})
    assert result.status == "fallback"
    assert result.error_code == "rate_limited"
    assert len(provider.calls) == 3  # exactly max_attempts


@pytest.mark.asyncio
async def test_run_task_invalid_response_is_fallback_without_retry(session_factory):
    await _seed_default_config(session_factory)
    provider = FakeProvider(responses=[("not json", (10, 2))])
    service = AiService(session_factory, provider_factory=lambda config: provider)
    result = await service.run_task("attribute_enrichment", {"title": "T", "description": "D"})
    assert result.status == "fallback"
    assert result.error_code == "invalid_response"
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_run_task_opens_circuit_after_failures(session_factory):
    await _seed_default_config(session_factory)
    timeout = httpx.TimeoutException("timed out")
    provider = FakeProvider(errors=[timeout] * 6)
    service = AiService(
        session_factory,
        provider_factory=lambda config: provider,
        retry_policy=__import__("app.ai.resilience", fromlist=["RetryPolicy"]).RetryPolicy(
            max_attempts=1, base_delay_s=0.0, jitter=0.0
        ),
        breaker_failure_threshold=2, breaker_window_s=60, breaker_cooldown_s=30,
    )
    # call 1: timeout -> fallback; call 2: timeout -> breaker opens
    await service.run_task("attribute_enrichment", {"title": "T", "description": "D"})
    await service.run_task("attribute_enrichment", {"title": "T", "description": "D"})
    # call 3: circuit open — no provider attempt at all
    result = await service.run_task("attribute_enrichment", {"title": "T2", "description": "D"})
    assert result.status == "fallback"
    assert result.error_code == "circuit_open"
    assert len(provider.calls) == 2  # third call never reached the provider


@pytest.mark.asyncio
async def test_usage_row_written_on_ok_and_cache_hit(session_factory):
    from sqlalchemy import select
    from app.models.ai import AiUsageLog

    await _seed_default_config(session_factory)
    provider = FakeProvider(responses=[('{"color": "blue"}', (50, 10))])
    service = AiService(session_factory, provider_factory=lambda config: provider)
    variables = {"title": "Shirt", "description": "D"}
    await service.run_task("attribute_enrichment", variables)
    await service.run_task("attribute_enrichment", variables)

    async with session_factory() as session:
        rows = list((await session.execute(
            select(AiUsageLog).order_by(AiUsageLog.id)
        )).scalars())
    assert len(rows) == 2
    assert rows[0].cache_hit is False
    assert rows[0].prompt_tokens == 50
    assert rows[1].cache_hit is True
    assert rows[1].prompt_tokens == 0


def test_default_provider_factory_builds_openai_compatible():
    from app.ai.openai_compat import OpenAICompatibleProvider

    config = AiProviderConfig(
        id=1, name="primary", provider_type="openai_compatible",
        base_url="https://api.openai.com/v1", api_key="sk",
        model="gpt-4o-mini", max_concurrency=4, timeout_s=30,
        enabled=True, is_default=True,
    )
    provider = default_provider_factory(config)
    assert isinstance(provider, OpenAICompatibleProvider)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_ai_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.service'`.

- [ ] **Step 3: Write the implementation**

```python
# backend/app/ai/service.py
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..clock import Clock
from ..models.ai import AiProviderConfig
from .cache import AiResultCacheStore
from .openai_compat import OpenAICompatibleProvider
from .provider import AIProvider, AiRequest, AiResponse
from .resilience import (
    CallOutcome,
    CircuitBreaker,
    RetryPolicy,
    classify_failure,
)
from .tasks import TaskSpecError, input_hash, render_task, validate_task
from .usage import UsageLogWriter, UsageRecord, estimate_cost

logger = logging.getLogger(__name__)

TEMPLATE_VERSION_BUILTIN = "builtin"


@dataclass(frozen=True)
class AiResult:
    value: Any
    status: str  # "ok" | "cache_hit" | "fallback"
    error_code: str | None
    prompt_tokens: int
    completion_tokens: int


def default_provider_factory(config: AiProviderConfig) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        timeout_s=config.timeout_s,
    )


class AiService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        clock: Clock | None = None,
        provider_factory: Callable[[AiProviderConfig], AIProvider] | None = None,
        retry_policy: RetryPolicy | None = None,
        breaker_failure_threshold: int = 5,
        breaker_window_s: int = 60,
        breaker_cooldown_s: int = 30,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._provider_factory = (
            provider_factory if provider_factory is not None else default_provider_factory
        )
        self._retry_policy = retry_policy if retry_policy is not None else RetryPolicy()
        self._cache = AiResultCacheStore(session_factory)
        self._usage = UsageLogWriter(session_factory)
        self._providers: dict[int, AIProvider] = {}
        self._breakers: dict[int, CircuitBreaker] = {}
        self._semaphores: dict[int, asyncio.Semaphore] = {}
        self._breaker_failure_threshold = breaker_failure_threshold
        self._breaker_window_s = breaker_window_s
        self._breaker_cooldown_s = breaker_cooldown_s

    # -- config resolution ------------------------------------------------

    async def _default_config(self) -> AiProviderConfig | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(AiProviderConfig)
                .where(AiProviderConfig.enabled.is_(True), AiProviderConfig.is_default.is_(True))
                .order_by(AiProviderConfig.id)
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def _get_config(self, provider_config_id: int) -> AiProviderConfig | None:
        async with self._session_factory() as session:
            return await session.get(AiProviderConfig, provider_config_id)

    # -- per-config collaborators -----------------------------------------

    def _provider_for(self, config: AiProviderConfig) -> AIProvider:
        provider = self._providers.get(config.id)
        if provider is None:
            provider = self._provider_factory(config)
            self._providers[config.id] = provider
        return provider

    def _breaker_for(self, config: AiProviderConfig) -> CircuitBreaker:
        breaker = self._breakers.get(config.id)
        if breaker is None:
            breaker = CircuitBreaker(
                failure_threshold=self._breaker_failure_threshold,
                window_s=self._breaker_window_s,
                cooldown_s=self._breaker_cooldown_s,
                clock=self._clock,
            )
            self._breakers[config.id] = breaker
        return breaker

    def _semaphore_for(self, config: AiProviderConfig) -> asyncio.Semaphore:
        semaphore = self._semaphores.get(config.id)
        if semaphore is None:
            semaphore = asyncio.Semaphore(max(1, config.max_concurrency))
            self._semaphores[config.id] = semaphore
        return semaphore

    # -- public API ---------------------------------------------------------

    async def run_task(
        self,
        task_type: str,
        variables: dict[str, Any],
        *,
        client_id: int | None = None,
        feed_source_id: int | None = None,
    ) -> AiResult:
        config = await self._default_config()
        if config is None:
            await self._log_usage(UsageRecord(
                client_id=client_id, feed_source_id=feed_source_id,
                task_type=task_type, provider_config_id=None, model="",
                cache_hit=False, prompt_tokens=0, completion_tokens=0,
                cost_usd=None, latency_ms=0, error_code="no_provider",
            ))
            return AiResult(value=None, status="fallback", error_code="no_provider",
                            prompt_tokens=0, completion_tokens=0)

        hash_value = input_hash(task_type, variables)
        template_version = TEMPLATE_VERSION_BUILTIN

        cache_entry = await self._cache.lookup(
            task_type, config.id, config.model, template_version, hash_value
        )
        if cache_entry is not None:
            await self._log_usage(UsageRecord(
                client_id=client_id, feed_source_id=feed_source_id,
                task_type=task_type, provider_config_id=config.id, model=config.model,
                cache_hit=True, prompt_tokens=0, completion_tokens=0,
                cost_usd=None, latency_ms=0, error_code=None,
            ))
            return AiResult(value=cache_entry.output.get("value"), status="cache_hit",
                            error_code=None, prompt_tokens=0, completion_tokens=0)

        return await self._call_provider(
            config, task_type, variables, hash_value,
            client_id=client_id, feed_source_id=feed_source_id,
        )

    async def test_provider(self, config_id: int) -> dict[str, Any]:
        config = await self._get_config(config_id)
        if config is None:
            return {"status": "error", "error_code": "no_provider"}
        provider = self._provider_for(config)
        try:
            request = AiRequest(
                task_type="test",
                messages=[
                    {"role": "system", "content": "Reply with the single word OK."},
                    {"role": "user", "content": "Ping"},
                ],
                max_tokens=8,
                temperature=0.0,
            )
            response = await provider.complete(request)
        except Exception as exc:
            outcome, _ = classify_failure(exc)
            return {"status": "error", "error_code": outcome.value}
        return {
            "status": "ok",
            "latency_ms": response.latency_ms,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
        }

    # -- internals -----------------------------------------------------------

    async def _call_provider(
        self,
        config: AiProviderConfig,
        task_type: str,
        variables: dict[str, Any],
        hash_value: str,
        *,
        client_id: int | None,
        feed_source_id: int | None,
    ) -> AiResult:
        breaker = self._breaker_for(config)
        if not breaker.allow_call():
            await self._log_usage(UsageRecord(
                client_id=client_id, feed_source_id=feed_source_id,
                task_type=task_type, provider_config_id=config.id, model=config.model,
                cache_hit=False, prompt_tokens=0, completion_tokens=0,
                cost_usd=None, latency_ms=0, error_code="circuit_open",
            ))
            return AiResult(value=None, status="fallback", error_code="circuit_open",
                            prompt_tokens=0, completion_tokens=0)

        provider = self._provider_for(config)
        semaphore = self._semaphore_for(config)
        messages = render_task(task_type, variables)
        retryable_error_code: str | None = None

        async with semaphore:
            for attempt in range(1, self._retry_policy.max_attempts + 1):
                try:
                    response = await provider.complete(AiRequest(
                        task_type=task_type, messages=messages,
                    ))
                except Exception as exc:
                    outcome, retryable = classify_failure(exc)
                    if not retryable or attempt == self._retry_policy.max_attempts:
                        retryable_error_code = outcome.value
                        breaker.record_failure()
                        break
                    await asyncio.sleep(self._retry_policy.delay_for_attempt(attempt))
                    continue
                # Provider responded — validate the content.
                try:
                    value = validate_task(task_type, response.content)
                except TaskSpecError:
                    breaker.record_failure()
                    await self._log_usage(UsageRecord(
                        client_id=client_id, feed_source_id=feed_source_id,
                        task_type=task_type, provider_config_id=config.id,
                        model=response.model, cache_hit=False,
                        prompt_tokens=response.prompt_tokens,
                        completion_tokens=response.completion_tokens,
                        cost_usd=None, latency_ms=response.latency_ms,
                        error_code="invalid_response",
                    ))
                    return AiResult(value=None, status="fallback",
                                    error_code="invalid_response",
                                    prompt_tokens=response.prompt_tokens,
                                    completion_tokens=response.completion_tokens)
                breaker.record_success()
                await self._cache.store(
                    task_type, config.id, config.model, TEMPLATE_VERSION_BUILTIN,
                    hash_value, {"value": value},
                )
                cost = estimate_cost(
                    response.prompt_tokens, response.completion_tokens,
                    config.input_price_per_mtok, config.output_price_per_mtok,
                )
                await self._log_usage(UsageRecord(
                    client_id=client_id, feed_source_id=feed_source_id,
                    task_type=task_type, provider_config_id=config.id,
                    model=response.model, cache_hit=False,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    cost_usd=cost, latency_ms=response.latency_ms, error_code=None,
                ))
                return AiResult(value=value, status="ok", error_code=None,
                                prompt_tokens=response.prompt_tokens,
                                completion_tokens=response.completion_tokens)

        # Exhausted retries (or non-retryable failure).
        assert retryable_error_code is not None
        await self._log_usage(UsageRecord(
            client_id=client_id, feed_source_id=feed_source_id,
            task_type=task_type, provider_config_id=config.id, model=config.model,
            cache_hit=False, prompt_tokens=0, completion_tokens=0,
            cost_usd=None, latency_ms=0, error_code=retryable_error_code,
        ))
        return AiResult(value=None, status="fallback", error_code=retryable_error_code,
                        prompt_tokens=0, completion_tokens=0)

    async def _log_usage(self, record: UsageRecord) -> None:
        await self._usage.write(record)
```

Then update `backend/app/ai/__init__.py`:

```python
from .provider import AIProvider, AiRequest, AiResponse
from .service import AiResult, AiService, default_provider_factory
from .tasks import TASK_SPECS, TaskSpec, TaskSpecError

__all__ = [
    "AIProvider", "AiRequest", "AiResponse",
    "AiResult", "AiService", "default_provider_factory",
    "TASK_SPECS", "TaskSpec", "TaskSpecError",
]
```

**Cache-shape contract:** the validated value is cached under a uniform `{"value": ...}` JSONB wrapper so both dict and text results round-trip through one shape: `store(..., {"value": value})`, and the cache-hit path above unwraps with `cache_entry.output.get("value")`. The `store` call in `_call_provider` below already uses this wrapper. `test_run_task_ok_and_cached_on_second_call` asserts `second.value == {"color": "blue"}` — satisfied because the wrapped `{"value": {"color": "blue"}}` is unwrapped on lookup.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_ai_service.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/service.py backend/app/ai/__init__.py backend/tests/test_ai_service.py
git commit -m "feat: AiService facade with cache, resilience, fallback semantics"
```

---

### Task 7: Admin API — provider CRUD (api_key redaction), test endpoint, usage aggregation

**Files:**
- Create: `backend/app/schemas/ai_admin.py`
- Create: `backend/app/routes/ai_admin.py`
- Modify: `backend/app/main.py` (router registration — one import + one `include_router` line next to `admin_router`)
- Test: `backend/tests/test_ai_admin_api.py`

**Interfaces:**
- Consumes: `AiService` (Task 6), `AiProviderConfig` (Task 1), `aggregate_usage` (Task 5), `require_admin` (existing `app/access.py`), `get_db_session` (existing DI), admin-route test pattern from `backend/tests/test_admin_settings_api.py`.
- Produces: routes (all under `require_admin`):
  - `GET /admin/ai/providers` → `list[AiProviderOut]`
  - `POST /admin/ai/providers` → 201 `AiProviderOut`
  - `PATCH /admin/ai/providers/{id}` → `AiProviderOut` (api_key optional; absent = unchanged; explicit `""` clears it)
  - `DELETE /admin/ai/providers/{id}` → 204 (usage logs keep `provider_config_id` — no FK, intentional)
  - `POST /admin/ai/providers/{id}/test` → `{"status": "ok", ...}` | `{"status": "error", "error_code": ...}`
  - `GET /admin/ai/usage?group_by=&client_id=&feed_source_id=&task_type=&from=&to=` → `{"rows": [...]}` (ISO date strings for `from`/`to`)
  - Pydantic schemas: `AiProviderOut(id, name, provider_type, base_url, model, input_price_per_mtok, output_price_per_mtok, max_concurrency, timeout_s, enabled, is_default)` — **no api_key field on Out**; `AiProviderCreate(name, provider_type="openai_compatible", base_url, api_key="", model, input_price_per_mtok=None, output_price_per_mtok=None, max_concurrency=4, timeout_s=30, enabled=True, is_default=False)`; `AiProviderUpdate` all-optional.

- [ ] **Step 1: Write the failing test**

Follow `test_admin_settings_api.py` exactly for fixtures (`settings_app`, `admin_http` — copy that file's fixture code verbatim; it logs in via `/auth/login` and returns an `httpx.AsyncClient` with `ASGITransport`). Add a non-admin variant by seeding a second user (pattern from `test_admin_users_api.py`).

```python
# backend/tests/test_ai_admin_api.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.global_setting import GlobalSetting
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user


@pytest_asyncio.fixture
async def settings_app(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(User))
            await session.execute(delete(GlobalSetting))
        await seed_initial_user(session, "operator", "admin-pass")
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


@pytest_asyncio.fixture
async def admin_http(settings_app):
    app, _ = settings_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.post(
        "/auth/login", json={"username": "operator", "password": "admin-pass"}
    )).status_code == 200
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_create_list_providers_api_key_redacted(admin_http):
    create = await admin_http.post("/admin/ai/providers", json={
        "name": "primary",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-secret-value",
        "model": "gpt-4o-mini",
        "is_default": True,
    })
    assert create.status_code == 201
    body = create.json()
    assert body["id"] > 0
    assert "api_key" not in body

    listing = await admin_http.get("/admin/ai/providers")
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    assert "api_key" not in rows[0]
    assert rows[0]["model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_patch_api_key_semantics(settings_app, admin_http):
    app, factory = settings_app
    create = await admin_http.post("/admin/ai/providers", json={
        "name": "primary",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-secret-value",
        "model": "gpt-4o-mini",
    })
    provider_id = create.json()["id"]

    # absent api_key -> unchanged
    await admin_http.patch(f"/admin/ai/providers/{provider_id}", json={"model": "gpt-4o-mini-2024"})
    async with factory() as session:
        row = await session.get(AiProviderConfig, provider_id)
        assert row.api_key == "sk-secret-value"
        assert row.model == "gpt-4o-mini-2024"

    # explicit "" -> cleared
    await admin_http.patch(f"/admin/ai/providers/{provider_id}", json={"api_key": ""})
    async with factory() as session:
        row = await session.get(AiProviderConfig, provider_id)
        assert row.api_key == ""


@pytest.mark.asyncio
async def test_only_one_default_provider(admin_http):
    await admin_http.post("/admin/ai/providers", json={
        "name": "first", "base_url": "https://api.openai.com/v1",
        "api_key": "k1", "model": "m1", "is_default": True,
    })
    second = await admin_http.post("/admin/ai/providers", json={
        "name": "second", "base_url": "https://api.openai.com/v1",
        "api_key": "k2", "model": "m2", "is_default": True,
    })
    assert second.status_code == 201
    listing = {row["id"]: row for row in (await admin_http.get("/admin/ai/providers")).json()}
    defaults = [row for row in listing.values() if row["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["name"] == "second"  # newest default wins


@pytest.mark.asyncio
async def test_delete_provider_204_and_gone(admin_http):
    create = await admin_http.post("/admin/ai/providers", json={
        "name": "primary", "base_url": "https://api.openai.com/v1",
        "api_key": "k", "model": "m",
    })
    provider_id = create.json()["id"]
    deleted = await admin_http.delete(f"/admin/ai/providers/{provider_id}")
    assert deleted.status_code == 204
    listing = await admin_http.get("/admin/ai/providers")
    assert listing.json() == []


@pytest.mark.asyncio
async def test_usage_endpoint_returns_aggregates(settings_app, admin_http):
    from app.ai.usage import UsageLogWriter, UsageRecord

    _, factory = settings_app
    writer = UsageLogWriter(factory)
    now = datetime.now(timezone.utc)
    await writer.write(UsageRecord(
        client_id=7, feed_source_id=None, task_type="policy_check",
        provider_config_id=1, model="gpt-4o-mini", cache_hit=False,
        prompt_tokens=100, completion_tokens=20, cost_usd=None,
        latency_ms=800, error_code=None,
    ))
    response = await admin_http.get("/admin/ai/usage", params={"group_by": "client"})
    assert response.status_code == 200
    rows = response.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["group_key"] == 7
    assert rows[0]["calls"] == 1


@pytest.mark.asyncio
async def test_usage_endpoint_rejects_bad_group_by(admin_http):
    response = await admin_http.get("/admin/ai/usage", params={"group_by": "bogus"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_admin_routes_forbidden_for_non_admin(settings_app):
    app, factory = settings_app
    async with factory() as session:
        async with session.begin():
            await seed_initial_user(session, "plain", "user-pass")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    # Seeded users start as admin — demote to plain user role directly.
    from sqlalchemy import update
    from app.models.user import User
    async with factory() as session:
        async with session.begin():
            await session.execute(
                update(User).where(User.username == "plain").values(role="user")
            )
    assert (await client.post(
        "/auth/login", json={"username": "plain", "password": "user-pass"}
    )).status_code == 200
    listing = await client.get("/admin/ai/providers")
    assert listing.status_code == 403
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_test_endpoint_reports_error(settings_app, admin_http):
    create = await admin_http.post("/admin/ai/providers", json={
        "name": "primary", "base_url": "https://api.openai.com/v1",
        "api_key": "k", "model": "m", "timeout_s": 1,
    })
    provider_id = create.json()["id"]
    # No real network in CI: the probe call fails fast (1s timeout) and the
    # endpoint reports {"status": "error", "error_code": ...} instead of raising.
    response = await admin_http.post(f"/admin/ai/providers/{provider_id}/test")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "error_code" in body
```

The test imports `AiProviderConfig` at the top of the file:

```python
from app.models.ai import AiProviderConfig
```

Implementation notes for this test file:
- `test_admin_routes_forbidden_for_non_admin` seeds a second user and demotes it to `role="user"` via a direct SQL update (seeding creates admin-role users), then asserts 403 on the AI admin routes.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_ai_admin_api.py -v`
Expected: FAIL — routes return 404 (`ModuleNotFoundError` on import of the new route module would break app import; if so the failure appears as collection error — either is the expected fail state).

- [ ] **Step 3: Write the implementation**

```python
# backend/app/schemas/ai_admin.py
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AiProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider_type: str
    base_url: str
    model: str
    input_price_per_mtok: Decimal | None
    output_price_per_mtok: Decimal | None
    max_concurrency: int
    timeout_s: int
    enabled: bool
    is_default: bool


class AiProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    provider_type: Literal["openai_compatible"] = "openai_compatible"
    base_url: str = Field(min_length=1, max_length=1024)
    api_key: str = Field(default="", max_length=1024)
    model: str = Field(min_length=1, max_length=255)
    input_price_per_mtok: Decimal | None = None
    output_price_per_mtok: Decimal | None = None
    max_concurrency: int = Field(default=4, ge=1, le=64)
    timeout_s: int = Field(default=30, ge=1, le=600)
    enabled: bool = True
    is_default: bool = False


class AiProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    provider_type: Literal["openai_compatible"] | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=1024)
    api_key: str | None = Field(default=None, max_length=1024)
    model: str | None = Field(default=None, min_length=1, max_length=255)
    input_price_per_mtok: Decimal | None = None
    output_price_per_mtok: Decimal | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=64)
    timeout_s: int | None = Field(default=None, ge=1, le=600)
    enabled: bool | None = None
    is_default: bool | None = None
```

```python
# backend/app/routes/ai_admin.py
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..access import CurrentUser, require_admin
from ..db.engine import get_db_session
from ..models.ai import AiProviderConfig
from ..schemas.ai_admin import AiProviderCreate, AiProviderOut, AiProviderUpdate
from ..ai.usage import aggregate_usage

router = APIRouter()


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _ai_service(request: Request):
    service = getattr(request.app.state, "ai_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="ai service unavailable")
    return service


async def _clear_other_defaults(session: AsyncSession, keep_id: int) -> None:
    await session.execute(
        update(AiProviderConfig)
        .where(AiProviderConfig.id != keep_id)
        .values(is_default=False)
    )


@router.get("/admin/ai/providers", response_model=list[AiProviderOut])
async def list_providers(
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> list[AiProviderOut]:
    session = _require_db(db_session)
    result = await session.execute(select(AiProviderConfig).order_by(AiProviderConfig.id))
    return [AiProviderOut.model_validate(row) for row in result.scalars()]


@router.post("/admin/ai/providers", status_code=201, response_model=AiProviderOut)
async def create_provider(
    payload: AiProviderCreate,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> AiProviderOut:
    session = _require_db(db_session)
    async with session.begin():
        row = AiProviderConfig(**payload.model_dump())
        session.add(row)
        await session.flush()
        if row.is_default:
            await _clear_other_defaults(session, row.id)
    return AiProviderOut.model_validate(row)


@router.patch("/admin/ai/providers/{provider_id}", response_model=AiProviderOut)
async def update_provider(
    provider_id: int,
    payload: AiProviderUpdate,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> AiProviderOut:
    session = _require_db(db_session)
    async with session.begin():
        row = await session.get(AiProviderConfig, provider_id)
        if row is None:
            raise HTTPException(status_code=404, detail="provider not found")
        updates = payload.model_dump(exclude_unset=True)
        if "api_key" in updates:
            setattr(row, "api_key", updates.pop("api_key"))
        for key, value in updates.items():
            setattr(row, key, value)
        await session.flush()
        if row.is_default:
            await _clear_other_defaults(session, row.id)
    await session.refresh(row)
    return AiProviderOut.model_validate(row)


@router.delete("/admin/ai/providers/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: int,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> None:
    session = _require_db(db_session)
    async with session.begin():
        row = await session.get(AiProviderConfig, provider_id)
        if row is None:
            raise HTTPException(status_code=404, detail="provider not found")
        await session.delete(row)


@router.post("/admin/ai/providers/{provider_id}/test")
async def test_provider(
    provider_id: int,
    request: Request,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict[str, Any]:
    _require_db(db_session)  # service resolves config through its own session
    service = _ai_service(request)
    return await service.test_provider(provider_id)


@router.get("/admin/ai/usage")
async def get_usage(
    group_by: str = Query(default="client", pattern="^(client|feed_source|task_type|day)$"),
    client_id: int | None = None,
    feed_source_id: int | None = None,
    task_type: str | None = None,
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict[str, Any]:
    session = _require_db(db_session)
    rows = await aggregate_usage(
        session,
        client_id=client_id, feed_source_id=feed_source_id,
         task_type=task_type, from_dt=from_dt, to_dt=to_dt,
         group_by=group_by,
     )
     return {"rows": rows}
 ```

Wire the router in `backend/app/main.py` next to the existing admin import/registration (add import near `from .routes.admin import router as admin_router` and the include near `app.include_router(admin_router)`):

```python
from .routes.ai_admin import router as ai_admin_router
# ...
app.include_router(ai_admin_router)
```

**Also required in this task:** construct `AiService` in `create_app` inside the `if app.state.db_session_factory is not None:` block (after `scheduler_service` wiring), attaching it to app state:

```python
from .ai import AiService
# ... inside create_app, after app.state.scheduler_service = scheduler_service:
app.state.ai_service = AiService(
    app.state.db_session_factory, clock=app.state.clock
)
```

(Keep the import at the top of `main.py` with the other route/service imports.)

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/test_ai_admin_api.py tests/test_m9_lifespan.py -v
```
Expected: all pass (9 new + lifespan tests unaffected).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/ai_admin.py backend/app/routes/ai_admin.py backend/app/main.py backend/tests/test_ai_admin_api.py
git commit -m "feat: admin api for ai providers and usage with api_key redaction"
```

---

### Task 8: Retention — AI purge job + GlobalSetting columns

**Files:**
- Modify: `backend/app/models/global_setting.py` (add 2 columns)
- Create: `backend/app/ai/purge.py`
- Modify: `backend/app/main.py` (register the AI purge system job in lifespan, following `run_ingestion_run_purge` registration pattern)
- Create: `backend/alembic/versions/20260911_0002_m13_ai_retention_settings.py`
- Test: `backend/tests/test_ai_purge.py`

**Interfaces:**
- Consumes: `GlobalSetting` model, purge pattern from `app/staging/purge.py` (`purge_expired_ingestion_runs` as template), system-job registration from `app/pipeline/scheduler.py` (`register_system_job(job_id, cron, func)`).
- Produces:
  - `GlobalSetting.ai_usage_retention_days` (default 90), `GlobalSetting.ai_cache_retention_days` (default 90)
  - `app.ai.purge.purge_expired_ai(session_factory, now) -> AiPurgeCounts(usage_rows: int, cache_rows: int)` — deletes usage rows older than `ai_usage_retention_days`, cache rows older than `ai_cache_retention_days`
  - New system job id constant `AI_PURGE_JOB_ID = "system-ai-purge"` (in `app/ai/purge.py`, following the `SYSTEM_PURGE_JOB_ID` placement convention)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ai_purge.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.purge import AiPurgeCounts, purge_expired_ai
from app.models.ai import AiProviderConfig, AiResultCache, AiUsageLog
from app.models.global_setting import GlobalSetting


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


NOW = datetime(2026, 3, 1, tzinfo=timezone.utc)


async def _seed_retention(factory, days: int) -> None:
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(GlobalSetting))
            session.add(GlobalSetting(
                id=1,
                staging_removal_retention_days=90,
                staging_history_retention_days=90,
                ingestion_run_retention_days=90,
                ai_usage_retention_days=days,
                ai_cache_retention_days=days,
            ))


async def _seed_rows(factory, config_id: int) -> None:
    days_old = 120  # older than the 90-day default retention
    old_usage = AiUsageLog(
        client_id=1, feed_source_id=None, task_type="policy_check",
        provider_config_id=config_id, model="m", cache_hit=False,
        prompt_tokens=1, completion_tokens=1, cost_usd=None,
        latency_ms=1, error_code=None,
    )
    fresh_usage = AiUsageLog(
        client_id=1, feed_source_id=None, task_type="policy_check",
        provider_config_id=config_id, model="m", cache_hit=False,
        prompt_tokens=1, completion_tokens=1, cost_usd=None,
        latency_ms=1, error_code=None,
    )
    old_cache = AiResultCache(
        task_type="policy_check", provider_config_id=config_id,
        model="m", template_version="builtin", input_hash="o" * 64,
        output={},
    )
    fresh_cache = AiResultCache(
        task_type="policy_check", provider_config_id=config_id,
        model="m", template_version="builtin", input_hash="f" * 64,
        output={},
    )
    async with factory() as session:
        async with session.begin():
            session.add_all([old_usage, fresh_usage, old_cache, fresh_cache])
            await session.flush()
            await session.execute(
                AiUsageLog.__table__.update()
                .where(AiUsageLog.id == old_usage.id)
                .values(created_at=NOW - timedelta(days=days_old))
            )
            await session.execute(
                AiUsageLog.__table__.update()
                .where(AiUsageLog.id == fresh_usage.id)
                .values(created_at=NOW - timedelta(days=1))
            )
            await session.execute(
                AiResultCache.__table__.update()
                .where(AiResultCache.id == old_cache.id)
                .values(created_at=NOW - timedelta(days=days_old))
            )
            await session.execute(
                AiResultCache.__table__.update()
                .where(AiResultCache.id == fresh_cache.id)
                .values(created_at=NOW - timedelta(days=1))
            )


@pytest.mark.asyncio
async def test_purge_deletes_only_expired_rows(session_factory):
    async with session_factory() as session:
        async with session.begin():
            config = AiProviderConfig(
                name="primary", provider_type="openai_compatible",
                base_url="https://api.openai.com/v1", api_key="k",
                model="m", max_concurrency=2, timeout_s=30,
                enabled=True, is_default=True,
            )
            session.add(config)
            await session.flush()
            config_id = config.id
    await _seed_retention(session_factory, days=90)
    await _seed_rows(session_factory, config_id)

    counts = await purge_expired_ai(session_factory, NOW)
    assert counts == AiPurgeCounts(usage_rows=1, cache_rows=1)

    async with session_factory() as session:
        remaining_usage = list((await session.execute(select(AiUsageLog))).scalars())
        remaining_cache = list((await session.execute(select(AiResultCache))).scalars())
    assert len(remaining_usage) == 1
    assert len(remaining_cache) == 1


@pytest.mark.asyncio
async def test_purge_respects_configured_retention(session_factory):
    async with session_factory() as session:
        async with session.begin():
            config = AiProviderConfig(
                name="primary", provider_type="openai_compatible",
                base_url="https://api.openai.com/v1", api_key="k",
                model="m", max_concurrency=2, timeout_s=30,
                enabled=True, is_default=True,
            )
            session.add(config)
            await session.flush()
            config_id = config.id
    await _seed_retention(session_factory, days=200)  # keep 120-day-old rows
    await _seed_rows(session_factory, config_id)

    counts = await purge_expired_ai(session_factory, NOW)
    assert counts == AiPurgeCounts(usage_rows=0, cache_rows=0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_ai_purge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.purge'` (and `GlobalSetting` missing the new columns).

- [ ] **Step 3: Write the implementation**

Add columns to `backend/app/models/global_setting.py`:

```python
    ai_usage_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    ai_cache_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
```

Generate the migration:

```bash
cd backend && DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed \
  uv run alembic revision --autogenerate -m "m13 ai retention settings"
```

Set `down_revision` to the Task 1 migration's revision id. Verify the generated file adds exactly the two columns to `global_settings`.

```python
# backend/app/ai/purge.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.ai import AiResultCache, AiUsageLog

AI_PURGE_JOB_ID = "system-ai-purge"

DEFAULT_AI_USAGE_RETENTION_DAYS = 90
DEFAULT_AI_CACHE_RETENTION_DAYS = 90


@dataclass(frozen=True)
class AiPurgeCounts:
    usage_rows: int
    cache_rows: int


async def _retention(session: AsyncSession) -> tuple[int, int]:
    from ..models.global_setting import GlobalSetting

    row = await session.get(GlobalSetting, 1)
    if row is None:
        return (
            DEFAULT_AI_USAGE_RETENTION_DAYS,
            DEFAULT_AI_CACHE_RETENTION_DAYS,
        )
    return (
        row.ai_usage_retention_days,
        row.ai_cache_retention_days,
    )


async def purge_expired_ai(
    session_factory: Callable[[], AsyncSession],
    now: datetime,
) -> AiPurgeCounts:
    async with session_factory() as session:
        async with session.begin():
            usage_days, cache_days = await _retention(session)
            usage = await session.execute(
                delete(AiUsageLog).where(
                    AiUsageLog.created_at < now - timedelta(days=usage_days)
                )
            )
            cache = await session.execute(
                delete(AiResultCache).where(
                    AiResultCache.created_at < now - timedelta(days=cache_days)
                )
            )
            return AiPurgeCounts(usage_rows=usage.rowcount, cache_rows=cache.rowcount)
```

Wire the system job in `backend/app/main.py` lifespan, right after the `run_ingestion_run_purge` registration (follow the exact same pattern):

```python
                from .ai.purge import AI_PURGE_JOB_ID, purge_expired_ai

                async def run_ai_purge() -> None:
                    counts = await purge_expired_ai(
                        application.state.db_session_factory,
                        datetime.now(timezone.utc),
                    )
                    logging.getLogger(__name__).info(
                        "ai purge: %s usage rows, %s cache rows",
                        counts.usage_rows,
                        counts.cache_rows,
                    )

                scheduler_service.register_system_job(
                    AI_PURGE_JOB_ID, PURGE_CRON, run_ai_purge
                )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/test_ai_purge.py tests/test_admin_settings_api.py -v
```
Expected: all pass (2 new; existing admin settings tests must stay green — they now see two extra columns but assert specific fields only; if an exact-dict assertion breaks, update it to include `ai_usage_retention_days: 90, ai_cache_retention_days: 90`).

Note: `test_admin_settings_api.py` has `test_get_settings_seeds_defaults` asserting the exact response dict — it will need the two new keys added. Handle that in this task (same commit).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/global_setting.py backend/app/ai/purge.py backend/app/main.py backend/alembic/versions/20260911_0002_m13_ai_retention_settings.py backend/tests/test_ai_purge.py backend/tests/test_admin_settings_api.py
git commit -m "feat: ai usage/cache retention purge job and settings"
```

---

### Task 9: Frontend types, hooks, API client

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/queryKeys.ts`
- Modify: `frontend/src/api/hooks.ts`
- Test: `frontend/src/api/aiHooks.test.ts`

**Interfaces:**
- Consumes: backend API from Task 7 (exact JSON shapes from `AiProviderOut`, usage rows).
- Produces (used by Task 10):
  - `types.ts`: `AiProvider`, `AiUsageRow`, `AiUsageGroupBy` (`'client' | 'feed_source' | 'task_type' | 'day'`), `AiTestResult`
  - `queryKeys.ts`: `queryKeys.ai = { providers: ['ai', 'providers'] as const, usage: (params) => ['ai', 'usage', params] as const }`
  - `hooks.ts`: `useAiProviders()`, `useCreateAiProvider()`, `useUpdateAiProvider()`, `useDeleteAiProvider()`, `useTestAiProvider()`, `useAiUsage(params)` (params: `{ group_by: AiUsageGroupBy; client_id?: number; from?: string; to?: string; task_type?: string }`)

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/api/aiHooks.test.ts
import { describe, expect, it } from 'vitest';
import { queryKeys } from './queryKeys';

describe('ai query keys', () => {
  it('exposes stable provider keys', () => {
    expect(queryKeys.ai.providers).toEqual(['ai', 'providers']);
  });

  it('builds usage keys from params', () => {
    expect(queryKeys.ai.usage({ group_by: 'client' })).toEqual([
      'ai',
      'usage',
      { group_by: 'client' },
    ]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/aiHooks.test.ts`
Expected: FAIL — `queryKeys.ai` is `undefined`.

- [ ] **Step 3: Write the implementation**

Append to `frontend/src/api/types.ts`:

```typescript
export type AiProvider = {
  id: number;
  name: string;
  provider_type: string;
  base_url: string;
  model: string;
  input_price_per_mtok: string | null;
  output_price_per_mtok: string | null;
  max_concurrency: number;
  timeout_s: number;
  enabled: boolean;
  is_default: boolean;
};

export type AiUsageGroupBy = 'client' | 'feed_source' | 'task_type' | 'day';

export type AiUsageParams = {
  group_by: AiUsageGroupBy;
  client_id?: number;
  feed_source_id?: number;
  task_type?: string;
  from?: string;
  to?: string;
};

export type AiUsageRow = {
  group_key: number | string | null;
  calls: number;
  cache_hits: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: string | null;
};

export type AiTestResult = {
  status: 'ok' | 'error';
  latency_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  error_code?: string;
};
```

Append to `frontend/src/api/queryKeys.ts` (inside the existing `queryKeys` object, after `adminSettings` if present — else at the end before the closing brace; check the file for the exact anchor):

```typescript
  ai: {
    providers: ['ai', 'providers'] as const,
    usage: (params: unknown) => ['ai', 'usage', params] as const,
  },
```

Append to `frontend/src/api/hooks.ts` (follow the existing `useAdminUsers`/`useUpdateAdminUser` mutation patterns — `apiGet`/`apiPost`/`apiPatch`/`apiDelete` from `./client`, `queryClient.invalidateQueries` on success):

```typescript
export function useAiProviders() {
  return useQuery({
    queryKey: queryKeys.ai.providers,
    queryFn: () => apiGet<AiProvider[]>('/admin/ai/providers'),
  });
}

export function useCreateAiProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Omit<AiProvider, 'id'> & { api_key?: string }) =>
      apiPost<AiProvider>('/admin/ai/providers', payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ai.providers });
    },
  });
}

export function useUpdateAiProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...payload }: {
      id: number;
      api_key?: string;
      name?: string;
      base_url?: string;
      model?: string;
      input_price_per_mtok?: string | null;
      output_price_per_mtok?: string | null;
      max_concurrency?: number;
      timeout_s?: number;
      enabled?: boolean;
      is_default?: boolean;
    }) => apiPatch<AiProvider>(`/admin/ai/providers/${id}`, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ai.providers });
    },
  });
}

export function useDeleteAiProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiDelete<void>(`/admin/ai/providers/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ai.providers });
    },
  });
}

export function useTestAiProvider() {
  return useMutation({
    mutationFn: (id: number) =>
      apiPost<AiTestResult>(`/admin/ai/providers/${id}/test`),
  });
}

export function useAiUsage(params: AiUsageParams) {
  return useQuery({
    queryKey: queryKeys.ai.usage(params),
    queryFn: () => apiGet<{ rows: AiUsageRow[] }>('/admin/ai/usage', params as never),
  });
}
```

Note for the implementer: `apiGet` in this codebase takes only a URL (see `frontend/src/api/client.ts` — signature `apiGet<T>(url: string)`). For query params, either extend `apiGet` with an optional params argument or serialize the params into the URL string manually (`'/admin/ai/usage?' + new URLSearchParams(...)`). Choose manual serialization in `useAiUsage` to avoid touching the shared client:

```typescript
export function useAiUsage(params: AiUsageParams) {
  const search = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined)
      .map(([k, v]) => [k, String(v)]),
  ).toString();
  return useQuery({
    queryKey: queryKeys.ai.usage(params),
    queryFn: () => apiGet<{ rows: AiUsageRow[] }>(`/admin/ai/usage?${search}`),
  });
}
```

Also check `hooks.ts` imports — add `AiProvider`, `AiTestResult`, `AiUsageParams`, `AiUsageRow` to the type import from `./types`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/aiHooks.test.ts`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/queryKeys.ts frontend/src/api/hooks.ts frontend/src/api/aiHooks.test.ts
git commit -m "feat: ai admin api types and hooks"
```

---

### Task 10: Admin AI tab — provider management UI + usage view

**Files:**
- Create: `frontend/src/features/admin/ai/ProvidersPage.tsx`
- Create: `frontend/src/features/admin/ai/UsagePage.tsx`
- Modify: `frontend/src/features/admin/AdminPage.tsx` (add `ai` tab)
- Modify: `frontend/src/app/router.tsx` (add `admin/ai` route)
- Modify: `frontend/public/locales/en/admin.json` (and every other locale file — check `frontend/public/locales/` for the full list; keep all languages in sync)
- Test: `frontend/src/features/admin/ai/ProvidersPage.test.tsx`

**Interfaces:**
- Consumes: hooks from Task 9; `AdminPage` tab pattern (see `AdminUsersPage.tsx` for table/modal/notify patterns — `notifySuccess`/`notifyApiError` from the codebase's shared helpers; check their import path in `AdminUsersPage.tsx`); `RequireAdmin` route guard (automatic via nesting under the admin routes).
- Produces: `/admin/ai` page with provider table, create/edit modal, delete confirm, test button, usage table with group-by filter.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/admin/ai/ProvidersPage.test.tsx
import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { queryClient } from '../../../../api/queryClient';
import { ProvidersPage } from './ProvidersPage';

describe('ProvidersPage', () => {
  it('renders the provider table headings', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <ProvidersPage />
      </QueryClientProvider>,
    );
    expect(screen.getByText('admin:ai.columns.name')).toBeTruthy();
    expect(screen.getByText('admin:ai.columns.model')).toBeTruthy();
    expect(screen.getByText('admin:ai.columns.enabled')).toBeTruthy();
  });
});
```

Note: the test asserts raw i18n keys if the test setup does not initialize i18next with the admin namespace. Check `frontend/src/test/setup.ts` for how other component tests handle i18n (`MonitoringFindingsPage.test.tsx` is the reference). If tests initialize real i18n with English strings, assert against the English labels (`Name`, `Model`, `Enabled`) instead of keys — match whatever the reference test does. The test's mock for `useAiProviders` must avoid network calls — follow the same mock pattern the reference admin tests use (e.g. mock the hooks module or the fetch call; check `AdminUsersPage` tests if they exist, otherwise `MonitoringFindingsPage.test.tsx`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/admin/ai/ProvidersPage.test.tsx`
Expected: FAIL — module `./ProvidersPage` not found.

- [ ] **Step 3: Write the implementation**

Create the pages following the `AdminUsersPage.tsx` conventions (Mantine `Table`, `Badge`, `Switch`, `ActionIcon`, `Group`, `Stack`, `Title`, `Button`, modal component colocated in the page file, `useTranslation('admin')` namespace, `data-testid` attributes):

```tsx
// frontend/src/features/admin/ai/ProvidersPage.tsx
import { useState } from 'react';
import {
  ActionIcon, Badge, Button, Group, Modal, Stack, Switch, Table, TextInput, Title,
} from '@mantine/core';
import { IconPencil, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useAiProviders, useCreateAiProvider, useDeleteAiProvider, useTestAiProvider, useUpdateAiProvider } from '../../../api/hooks';
import { EmptyState, ErrorState, LoadingState } from '../../../components/StateViews';
import type { AiProvider } from '../../../api/types';

export function ProvidersPage() {
  const { t } = useTranslation('admin');
  const providersQuery = useAiProviders();
  const createProvider = useCreateAiProvider();
  const updateProvider = useUpdateAiProvider();
  const deleteProvider = useDeleteAiProvider();
  const testProvider = useTestAiProvider();
  const [editing, setEditing] = useState<AiProvider | null>(null);
  const [creating, setCreating] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  if (providersQuery.isPending) return <LoadingState />;
  if (providersQuery.isError) {
    return <ErrorState onRetry={() => void providersQuery.refetch()} />;
  }
  const providers = providersQuery.data ?? [];
  if (providers.length === 0) return <EmptyState message={t('ai.empty')} />;

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={4}>{t('ai.providersTitle')}</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
          {t('ai.add')}
        </Button>
      </Group>
      <Table data-testid="ai-providers-table" striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('ai.columns.name')}</Table.Th>
            <Table.Th>{t('ai.columns.model')}</Table.Th>
            <Table.Th>{t('ai.columns.enabled')}</Table.Th>
            <Table.Th>{t('ai.columns.default')}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {providers.map((provider) => (
            <Table.Tr key={provider.id} data-testid={`ai-provider-row-${provider.id}`}>
              <Table.Td>{provider.name}</Table.Td>
              <Table.Td>{provider.model}</Table.Td>
              <Table.Td>
                <Switch
                  aria-label={t('ai.columns.enabled')}
                  checked={provider.enabled}
                  onChange={(event) =>
                    updateProvider.mutate({ id: provider.id, enabled: event.currentTarget.checked })
                  }
                />
              </Table.Td>
              <Table.Td>
                {provider.is_default ? <Badge variant="light" color="grape">{t('ai.default')}</Badge> : null}
              </Table.Td>
              <Table.Td>
                <Group gap="xs" wrap="nowrap">
                  <ActionIcon variant="subtle" aria-label={t('ai.test')} onClick={() => {
                    testProvider.mutate(provider.id, {
                      onSuccess: (result) => setTestResult(
                        result.status === 'ok'
                          ? t('ai.testOk', { latency: result.latency_ms ?? 0 })
                          : t('ai.testFailed', { code: result.error_code ?? 'unknown' }),
                      ),
                    });
                  }}>
                    <IconPencil size={16} />
                  </ActionIcon>
                  <ActionIcon variant="subtle" aria-label={t('ai.edit')} onClick={() => setEditing(provider)}>
                    <IconPencil size={16} />
                  </ActionIcon>
                  <ActionIcon variant="subtle" color="red" aria-label={t('ai.delete')} onClick={() => deleteProvider.mutate(provider.id)}>
                    <IconTrash size={16} />
                  </ActionIcon>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {testResult ? <div>{testResult}</div> : null}
      <ProviderModal
        opened={creating || editing !== null}
        provider={editing}
        onClose={() => { setCreating(false); setEditing(null); }}
        onSubmit={(payload) => {
          if (editing) updateProvider.mutate({ id: editing.id, ...payload });
          else createProvider.mutate(payload);
        }}
      />
    </Stack>
  );
}

function ProviderModal({
  opened, provider, onClose, onSubmit,
}: {
  opened: boolean;
  provider: AiProvider | null;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => void;
}) {
  const { t } = useTranslation('admin');
  const [name, setName] = useState(provider?.name ?? '');
  const [baseUrl, setBaseUrl] = useState(provider?.base_url ?? '');
  const [model, setModel] = useState(provider?.model ?? '');
  const [apiKey, setApiKey] = useState('');
  const [isDefault, setIsDefault] = useState(provider?.is_default ?? false);

  return (
    <Modal opened={opened} onClose={onClose} title={provider ? t('ai.edit') : t('ai.add')}>
      <Stack>
        <TextInput label={t('ai.columns.name')} value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <TextInput label="Base URL" value={baseUrl} onChange={(e) => setBaseUrl(e.currentTarget.value)} />
        <TextInput label="Model" value={model} onChange={(e) => setModel(e.currentTarget.value)} />
        <TextInput
          label={t('ai.apiKey')}
          placeholder={provider ? t('ai.apiKeyUnchanged') : ''}
          value={apiKey}
          onChange={(e) => setApiKey(e.currentTarget.value)}
        />
        <Switch label={t('ai.columns.default')} checked={isDefault} onChange={(e) => setIsDefault(e.currentTarget.checked)} />
        <Button onClick={() => onSubmit({
          name, base_url: baseUrl, model,
          ...(apiKey !== '' ? { api_key: apiKey } : {}),
          is_default: isDefault,
        })}>
          {t('ai.save')}
        </Button>
      </Stack>
    </Modal>
  );
}
```

Notes for the implementer:
- The test-button `ActionIcon` in the sketch reuses `IconPencil` — replace with an appropriate icon (e.g. `IconPlug` or `IconBolt` from `@tabler/icons-react`); semantics: `aria-label={t('ai.test')}`.
- Check the actual import paths for `notifySuccess`/`notifyApiError` (used by `AdminUsersPage.tsx` — copy from there) and wire them into mutations' `onSuccess`/`onError`.
- The test file above asserts `admin:ai.columns.name` style keys — align with whatever i18n mode the reference test uses (see Step 1 note). If tests render real i18n strings, use the English labels from the JSON you add below.
- `useDeleteAiProvider` ideally confirms via the codebase's `ConfirmModal` (see `DeleteClientModal` pattern in `AdminClientsPage.tsx`) — add that if straightforward; a plain `onClick` without confirmation is acceptable for this feature's first cut, but the confirm modal is preferred.

```tsx
// frontend/src/features/admin/ai/UsagePage.tsx
import { useState } from 'react';
import { Select, Stack, Table, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useAiUsage } from '../../../api/hooks';
import { EmptyState, ErrorState, LoadingState } from '../../../components/StateViews';
import type { AiUsageGroupBy } from '../../../api/types';

const GROUP_OPTIONS: { value: AiUsageGroupBy; label: string }[] = [
  { value: 'client', label: 'Client' },
  { value: 'feed_source', label: 'Feed Source' },
  { value: 'task_type', label: 'Task Type' },
  { value: 'day', label: 'Day' },
];

export function UsagePage() {
  const { t } = useTranslation('admin');
  const [groupBy, setGroupBy] = useState<AiUsageGroupBy>('client');
  const usageQuery = useAiUsage({ group_by: groupBy });

  if (usageQuery.isPending) return <LoadingState />;
  if (usageQuery.isError) return <ErrorState onRetry={() => void usageQuery.refetch()} />;
  const rows = usageQuery.data?.rows ?? [];
  if (rows.length === 0) return <EmptyState message={t('ai.usage.empty')} />;

  return (
    <Stack gap="md">
      <Title order={4}>{t('ai.usage.title')}</Title>
      <Select
        label={t('ai.usage.groupBy')}
        data={GROUP_OPTIONS}
        value={groupBy}
        onChange={(v) => setGroupBy((v as AiUsageGroupBy) ?? 'client')}
      />
      <Table data-testid="ai-usage-table" striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('ai.usage.groupKey')}</Table.Th>
            <Table.Th>{t('ai.usage.calls')}</Table.Th>
            <Table.Th>{t('ai.usage.cacheHits')}</Table.Th>
            <Table.Th>{t('ai.usage.promptTokens')}</Table.Th>
            <Table.Th>{t('ai.usage.completionTokens')}</Table.Th>
            <Table.Th>{t('ai.usage.cost')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row, idx) => (
            <Table.Tr key={`${row.group_key}-${idx}`} data-testid={`ai-usage-row-${idx}`}>
              <Table.Td>{String(row.group_key)}</Table.Td>
              <Table.Td>{row.calls}</Table.Td>
              <Table.Td>{row.cache_hits}</Table.Td>
              <Table.Td>{row.prompt_tokens}</Table.Td>
              <Table.Td>{row.completion_tokens}</Table.Td>
              <Table.Td>{row.cost_usd ?? '—'}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
```

Modify `AdminPage.tsx` — add `'ai'` to `TAB_VALUES`, a tab panel, and route entries in `router.tsx`:

```tsx
// AdminPage.tsx — updated constants and Tabs additions
const TAB_VALUES = ['users', 'clients', 'settings', 'ai'] as const;
// ...
<Tabs.Tab value="ai">{t('tabs.ai')}</Tabs.Tab>
// ...
<Tabs.Panel value="ai" pt="md">
  <AiAdminPage />
</Tabs.Panel>
```

```tsx
// frontend/src/features/admin/ai/AiAdminPage.tsx — small tab-internal switcher
import { useState } from 'react';
import { SegmentedControl, Stack } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { ProvidersPage } from './ProvidersPage';
import { UsagePage } from './UsagePage';

export function AiAdminPage() {
  const { t } = useTranslation('admin');
  const [section, setSection] = useState('providers');
  return (
    <Stack gap="md">
      <SegmentedControl
        value={section}
        onChange={setSection}
        data={[
          { value: 'providers', label: t('ai.section.providers') },
          { value: 'usage', label: t('ai.section.usage') },
        ]}
      />
      {section === 'providers' ? <ProvidersPage /> : <UsagePage />}
    </Stack>
  );
}
```

In `router.tsx`, add inside the `RequireAdmin` children (next to `admin/users` etc.):

```tsx
{ path: 'admin/ai', element: <AdminPage /> },
```

i18n — add to every `frontend/public/locales/<lang>/admin.json` (en shown; translate for each language file present):

```json
{
  "tabs": { "ai": "AI" },
  "ai": {
    "section": { "providers": "Providers", "usage": "Usage" },
    "providersTitle": "AI Providers",
    "empty": "No AI providers configured",
    "add": "Add Provider",
    "edit": "Edit Provider",
    "save": "Save",
    "delete": "Delete",
    "test": "Test connection",
    "testOk": "Connection OK ({{latency}} ms)",
    "testFailed": "Connection failed: {{code}}",
    "apiKey": "API Key",
    "apiKeyUnchanged": "unchanged — leave empty to keep",
    "default": "Default",
    "columns": {
      "name": "Name",
      "model": "Model",
      "enabled": "Enabled",
      "default": "Default"
    },
    "usage": {
      "title": "AI Usage",
      "empty": "No AI usage recorded yet",
      "groupBy": "Group by",
      "groupKey": "Group",
      "calls": "Calls",
      "cacheHits": "Cache hits",
      "promptTokens": "Prompt tokens",
      "completionTokens": "Completion tokens",
      "cost": "Cost (USD)"
    }
  }
}
```

(Deep-merge into the existing files — they already have `tabs`, `users`, `clients`, `settings` top-level keys; add the `ai` key and the `tabs.ai` entry.)

- [ ] **Step 4: Run tests and typecheck**

```bash
cd frontend && npx vitest run src/features/admin/ai/ProvidersPage.test.tsx && npm run typecheck
```
Expected: test PASS; typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/admin/ frontend/src/app/router.tsx frontend/public/locales/
git commit -m "feat: admin ai tab with provider management and usage view"
```

---

### Task 11: Docs update + full CI gate

**Files:**
- Modify: `backend/docs/api.md` — add `/admin/ai/*` endpoints
- Modify: `backend/docs/data-model.md` — add the 3 AI tables + retention rules
- Modify: `backend/docs/architecture.md` — add `app/ai/` module to the system overview
- Modify: `backend/docs/decisions.md` — dated entry (Topic/Decision/Rationale): AI provider abstraction, OpenAI-compatible-only protocol, DB-backed provider config incl. api_key storage decision, in-process breaker, hash-keyed cache with template_version
- Test: none (docs), CI gate validates code

- [ ] **Step 1: Update the four docs**

In `backend/docs/api.md`, add a section mirroring the existing admin endpoint style:

```markdown
### AI Administration (admin only)

| Method | Path | Description |
|---|---|---|
| GET | /admin/ai/providers | List AI provider configs (api_key never included) |
| POST | /admin/ai/providers | Create provider config |
| PATCH | /admin/ai/providers/{id} | Update provider (api_key absent = unchanged, "" = cleared) |
| DELETE | /admin/ai/providers/{id} | Delete provider config |
| POST | /admin/ai/providers/{id}/test | Live probe completion; returns status + latency or error_code |
| GET | /admin/ai/usage | Aggregated token/cost/call counts; group_by=client|feed_source|task_type|day |
```

In `backend/docs/data-model.md`, document the three tables with their key semantics (cache unique key incl. template_version; usage row per call incl. cache hits; retention via `ai_usage_retention_days`/`ai_cache_retention_days` GlobalSetting, purged by the `system-ai-purge` daily job).

In `backend/docs/architecture.md`, add an `app/ai/` section: task registry → cache → resilience (retry/breaker) → provider; AiService attached to `app.state.ai_service`; consumers (Features 4/5) call `run_task()` which never raises on provider errors — fallback is the caller's decision.

In `backend/docs/decisions.md`, append:

```markdown
### 2026-09-11 — AI provider abstraction (Feature 1)
**Topic:** LLM integration foundation.
**Decision:** Generic `AIProvider.complete()` protocol + task registry in `app/ai/`; OpenAI-compatible protocol only (self-hosted via base_url); provider config (incl. api_key) in `ai_provider_configs` DB table with redacted reads; hash-keyed `ai_result_cache` including template_version; in-process per-config circuit breaker; per-call `ai_usage_logs` with retention purge.
**Rationale:** No vendor SDK (httpx already a dep); task semantics live in prompt templates (Feature 2 seam), so new AI tasks need zero provider changes; DB-backed config allows runtime provider swap by admins; AI failures degrade to fallback results and never block the pipeline.
```

- [ ] **Step 2: Run the full CI gate**

```bash
cd backend && uv run ruff check . && uv run mypy . && uv run pytest --report-log=.report.jsonl
cd ../frontend && npm run typecheck && npx vitest run
```
Expected: ruff baseline count unchanged (508) — `wc -l ruff-baseline.txt` cross-check if reported; mypy exit 0; pytest full suite green (jq gate per backend/AGENTS.md); frontend typecheck + all vitest suites green.

- [ ] **Step 3: Commit**

```bash
git add backend/docs/ backend/ruff-baseline.txt 2>/dev/null; git add backend/docs/
git commit -m "docs: ai provider abstraction endpoints, data model, architecture, decisions"
```

---

## Plan Self-Review (already performed)

1. **Spec coverage:** Task 1 = 3 tables/migration; Task 2 = protocol + task registry (5 task types); Task 3 = retry/backoff + circuit breaker; Task 4 = OpenAI-compatible provider; Task 5 = cache + usage (incl. aggregation API); Task 6 = AiService fallback semantics + test probe; Task 7 = admin CRUD + redaction + test endpoint + usage endpoint; Task 8 = retention (purge job + GlobalSetting columns); Tasks 9–10 = minimal admin UI; Task 11 = docs. All acceptance criteria mapped: provider swap = config row + default flip (Tasks 1/6/7); cache hit on unchanged content = input_hash (Tasks 2/5/6); timeout/rate-limit fallback = resilience + AiService (Tasks 3/6).
2. **Placeholder scan:** none — first-draft code issues found during plan writing were fixed inline; the plan contains only final code.
3. **Type consistency:** `AiResult(value, status, error_code, prompt_tokens, completion_tokens)` consistent across Tasks 2/6; `RetryPolicy.delay_for_attempt` consistent; `AiResultCacheStore.lookup/store` signatures consistent between Tasks 5/6; `UsageRecord` fields match `AiUsageLog` columns; frontend types match Task 7 response shapes (Decimal serialized as string — hence `string | null` in `AiProvider`/`AiUsageRow`).
