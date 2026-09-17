# AI Provider Wizard + Model Catalog Implementation Plan (GFM-12)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the raw AI-provider form with a 3-step preset wizard whose model list comes from a LiteLLM-derived, refreshable catalog.

**Architecture:** A new `app/ai/presets.py` holds provider presets and write-side normalization; a new `app/ai/model_catalog.py` parses the LiteLLM price JSON (bundled seed from `litellm.model_cost`, refreshed from GitHub raw), persists it in two new tables, and exposes it through admin routes; the frontend swaps the modal for a Mantine `Stepper` backed by three TanStack Query hooks.

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.0 async, Alembic, httpx, litellm, pytest; React 19, TypeScript, Mantine, TanStack Query, vitest.

Spec: `docs/superpowers/specs/2026-09-17-ai-provider-wizard-model-catalog-design.md`

## Global Constraints

- Backend commands run from `backend/`; frontend commands run from `frontend/`.
- All I/O is `async def`; one `AsyncSession` per request/task; no blocking calls in the event loop.
- Models use typed SQLAlchemy 2.0 `Mapped[T]` / `mapped_column(...)`, never legacy `Column(...)`.
- Schema changes only via Alembic revisions; never `create_all`; `uv run alembic check` must be empty.
- Module-level `logger = logging.getLogger(__name__)`; log with lazy `%s` interpolation, never f-strings.
- No code comments unless the surrounding file already uses them for the same purpose.
- Do not add backend or frontend dependencies.
- Any change to behavior, API surface, data model, or commands updates the affected docs in the same commit (AGENTS.md).
- Backend gate after every backend task: `uv run ruff check . ../plugins`, `uv run mypy .`.
- Frontend gate after every frontend task: `npm run typecheck`.
- Frontend server state lives only in TanStack Query; no duplicate client stores.
- i18n keys are added to both `frontend/public/locales/en/admin.json` and `frontend/public/locales/de/admin.json`.
- `provider_type` is always `litellm` at rest after this cycle; `openai_compatible` remains readable for existing rows but is never written.

---

### Task 1: Provider presets and write normalization

**Files:**
- Create: `backend/app/ai/presets.py`
- Test: `backend/tests/test_ai_presets.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ProviderPreset` (frozen dataclass with fields `vendor_key, label, model_prefix, default_base_url, requires_base_url, api_key_env_hint, docs_url, supports_catalog`), `PROVIDER_PRESETS: tuple[ProviderPreset, ...]`, `get_preset(vendor_key: str) -> ProviderPreset | None`, `normalize_provider_input(model: str, provider_type: str) -> tuple[str, str]` returning `(provider_type, model)`.

- [x] **Step 1: Write the failing test**

Create `backend/tests/test_ai_presets.py`:

```python
from __future__ import annotations

import pytest

from app.ai.presets import PROVIDER_PRESETS, get_preset, normalize_provider_input


def test_preset_keys_and_order() -> None:
    keys = [p.vendor_key for p in PROVIDER_PRESETS]
    assert keys == [
        "openai", "anthropic", "google", "openrouter", "mistral", "groq", "custom",
    ]
    assert keys[-1] == "custom"


def test_custom_is_the_only_base_url_required_preset() -> None:
    assert [p.vendor_key for p in PROVIDER_PRESETS if p.requires_base_url] == ["custom"]
    assert [p.vendor_key for p in PROVIDER_PRESETS if not p.supports_catalog] == ["custom"]


def test_google_preset_uses_gemini_prefix() -> None:
    google = get_preset("google")
    assert google is not None
    assert google.model_prefix == "gemini"


def test_get_preset_unknown() -> None:
    assert get_preset("nope") is None


@pytest.mark.parametrize(
    ("model", "provider_type", "expected"),
    [
        ("gpt-4o-mini", "openai_compatible", ("litellm", "openai/gpt-4o-mini")),
        ("openai/gpt-4o-mini", "openai_compatible", ("litellm", "openai/gpt-4o-mini")),
        ("openai/gpt-4o-mini", "litellm", ("litellm", "openai/gpt-4o-mini")),
        ("gpt-4o", "litellm", ("litellm", "gpt-4o")),
        ("anthropic/claude-sonnet-4-5", "litellm", ("litellm", "anthropic/claude-sonnet-4-5")),
    ],
)
def test_normalize_provider_input(model: str, provider_type: str, expected: tuple[str, str]) -> None:
    assert normalize_provider_input(model, provider_type) == expected
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_presets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ai.presets'`

- [x] **Step 3: Write minimal implementation**

Create `backend/app/ai/presets.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    vendor_key: str
    label: str
    model_prefix: str
    default_base_url: str
    requires_base_url: bool
    api_key_env_hint: str
    docs_url: str
    supports_catalog: bool


PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        vendor_key="openai",
        label="OpenAI",
        model_prefix="openai",
        default_base_url="",
        requires_base_url=False,
        api_key_env_hint="OPENAI_API_KEY",
        docs_url="https://platform.openai.com/api-keys",
        supports_catalog=True,
    ),
    ProviderPreset(
        vendor_key="anthropic",
        label="Anthropic",
        model_prefix="anthropic",
        default_base_url="",
        requires_base_url=False,
        api_key_env_hint="ANTHROPIC_API_KEY",
        docs_url="https://console.anthropic.com/settings/keys",
        supports_catalog=True,
    ),
    ProviderPreset(
        vendor_key="google",
        label="Google Gemini",
        model_prefix="gemini",
        default_base_url="",
        requires_base_url=False,
        api_key_env_hint="GEMINI_API_KEY",
        docs_url="https://aistudio.google.com/app/apikey",
        supports_catalog=True,
    ),
    ProviderPreset(
        vendor_key="openrouter",
        label="OpenRouter",
        model_prefix="openrouter",
        default_base_url="",
        requires_base_url=False,
        api_key_env_hint="OPENROUTER_API_KEY",
        docs_url="https://openrouter.ai/keys",
        supports_catalog=True,
    ),
    ProviderPreset(
        vendor_key="mistral",
        label="Mistral",
        model_prefix="mistral",
        default_base_url="",
        requires_base_url=False,
        api_key_env_hint="MISTRAL_API_KEY",
        docs_url="https://console.mistral.ai/api-keys",
        supports_catalog=True,
    ),
    ProviderPreset(
        vendor_key="groq",
        label="Groq",
        model_prefix="groq",
        default_base_url="",
        requires_base_url=False,
        api_key_env_hint="GROQ_API_KEY",
        docs_url="https://console.groq.com/keys",
        supports_catalog=True,
    ),
    ProviderPreset(
        vendor_key="custom",
        label="OpenAI-kompatibel (custom)",
        model_prefix="openai",
        default_base_url="",
        requires_base_url=True,
        api_key_env_hint="",
        docs_url="",
        supports_catalog=False,
    ),
)

_PRESETS_BY_KEY = {preset.vendor_key: preset for preset in PROVIDER_PRESETS}


def get_preset(vendor_key: str) -> ProviderPreset | None:
    return _PRESETS_BY_KEY.get(vendor_key)


def normalize_provider_input(model: str, provider_type: str) -> tuple[str, str]:
    if provider_type == "openai_compatible" and "/" not in model:
        return "litellm", f"openai/{model}"
    return "litellm", model
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ai_presets.py -v`
Expected: PASS (8 passed)

- [x] **Step 5: Lint and typecheck**

Run: `uv run ruff check . ../plugins && uv run mypy .`
Expected: exit 0

- [x] **Step 6: Commit**

```bash
git add backend/app/ai/presets.py backend/tests/test_ai_presets.py
git commit -m "feat(ai): provider presets and write normalization (GFM-12)"
```

---

### Task 2: Catalog ORM models and migration

**Files:**
- Modify: `backend/app/models/ai.py` (append two classes)
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/20260917_0001_m17_ai_model_catalog.py`
- Test: `backend/tests/test_ai_model_catalog_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `AiModelCatalog` (columns `id, vendor, model_id, display_name, mode, context_window, max_output_tokens, input_price_per_mtok, output_price_per_mtok, supports_vision, supports_function_calling`), `AiModelCatalogSync` (singleton columns `id, last_attempt_at, last_success_at, last_error, source`).

- [x] **Step 1: Write the failing test**

Create `backend/tests/test_ai_model_catalog_models.py`:

```python
from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.ai import AiModelCatalog, AiModelCatalogSync


@pytest_asyncio.fixture
async def db_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _row(model_id: str) -> AiModelCatalog:
    return AiModelCatalog(
        vendor="openai",
        model_id=model_id,
        display_name=model_id.rsplit("/", 1)[-1],
        mode="chat",
        context_window=128000,
        max_output_tokens=16384,
        input_price_per_mtok=Decimal("2.500000"),
        output_price_per_mtok=Decimal("10.000000"),
        supports_vision=True,
        supports_function_calling=True,
    )


@pytest.mark.asyncio
async def test_catalog_round_trip(db_factory) -> None:
    async with db_factory() as session, session.begin():
        session.add(_row("openai/gpt-4o"))
        session.add(AiModelCatalogSync(id=1, source="bundled"))
    async with db_factory() as session:
        row = (await session.execute(select(AiModelCatalog))).scalar_one()
        assert row.model_id == "openai/gpt-4o"
        assert row.mode == "chat"
        assert row.supports_vision is True
        sync = await session.get(AiModelCatalogSync, 1)
        assert sync is not None
        assert sync.source == "bundled"


@pytest.mark.asyncio
async def test_catalog_model_id_is_unique(db_factory) -> None:
    async with db_factory() as session, session.begin():
        session.add(_row("openai/gpt-4o"))
    with pytest.raises(IntegrityError):
        async with db_factory() as session, session.begin():
            session.add(_row("openai/gpt-4o"))
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_model_catalog_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'AiModelCatalog' from 'app.models.ai'`

- [x] **Step 3: Add the ORM models**

Append to `backend/app/models/ai.py` (the module already imports `Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text` and `Decimal`, `Mapped`, `mapped_column`):

```python
class AiModelCatalog(Base):
    __tablename__ = "ai_model_catalog"
    __table_args__ = (
        UniqueConstraint("model_id", name="uq_ai_model_catalog_model_id"),
        Index("ix_ai_model_catalog_vendor_mode", "vendor", "mode"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor: Mapped[str] = mapped_column(String(50), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="chat", server_default="chat")
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_price_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    output_price_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    supports_vision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    supports_function_calling: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))


class AiModelCatalogSync(Base):
    __tablename__ = "ai_model_catalog_sync"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

- [x] **Step 4: Register the models for Alembic discovery**

In `backend/app/models/__init__.py`, change the `ai` import line and `__all__`:

```python
from .ai import AiModelCatalog, AiModelCatalogSync, AiProviderConfig, AiUsageLog, PromptTemplate
```

Add `"AiModelCatalog", "AiModelCatalogSync",` to `__all__` immediately after `"AiProviderConfig", "AiUsageLog",` (keep the list alphabetically ordered as it already is).

- [x] **Step 5: Generate the migration**

Run from `backend/`:

```bash
uv run alembic revision --autogenerate -m "m17 ai model catalog"
```

Open the generated file and replace its `upgrade()` / `downgrade()` bodies so they match exactly:

```python
def upgrade() -> None:
    op.create_table(
        "ai_model_catalog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vendor", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=20), server_default="chat", nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("input_price_per_mtok", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("output_price_per_mtok", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("supports_vision", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("supports_function_calling", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id", name="uq_ai_model_catalog_model_id"),
    )
    op.create_index("ix_ai_model_catalog_vendor_mode", "ai_model_catalog", ["vendor", "mode"], unique=False)
    op.create_table(
        "ai_model_catalog_sync",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("ai_model_catalog_sync")
    op.drop_index("ix_ai_model_catalog_vendor_mode", table_name="ai_model_catalog")
    op.drop_table("ai_model_catalog")
```

Leave the generated `revision` / `down_revision` identifiers untouched; confirm `down_revision` is `"b1a2c3d4e5f6"` (the previous head).

- [x] **Step 6: Verify no schema drift**

Run: `uv run alembic check`
Expected: `No new upgrade operations detected.`

- [x] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_ai_model_catalog_models.py -v`
Expected: PASS (2 passed)

- [x] **Step 8: Lint and typecheck**

Run: `uv run ruff check . ../plugins && uv run mypy .`
Expected: exit 0

- [x] **Step 9: Commit**

```bash
git add backend/app/models/ai.py backend/app/models/__init__.py backend/alembic/versions backend/tests/test_ai_model_catalog_models.py
git commit -m "feat(ai): model catalog tables and migration (GFM-12)"
```

---

### Task 3: Catalog parsing, bundled load, recommendations

**Files:**
- Create: `backend/app/ai/model_catalog.py` (parsing section)
- Test: `backend/tests/test_ai_model_catalog.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CatalogEntry` (frozen dataclass: `vendor, model_id, display_name, mode, context_window, max_output_tokens, input_price_per_mtok, output_price_per_mtok, supports_vision, supports_function_calling`), `SUPPORTED_VENDORS: dict[str, str]`, `RECOMMENDED_MODELS: dict[str, set[str]]`, `LITELLM_CATALOG_URL: str`, `MIN_CATALOG_ENTRIES: int`, `parse_catalog(raw: dict[str, Any]) -> list[CatalogEntry]`, `load_bundled() -> list[CatalogEntry]`, `is_recommended(vendor: str, model_id: str) -> bool`.

- [x] **Step 1: Write the failing test**

Create `backend/tests/test_ai_model_catalog.py`:

```python
from __future__ import annotations

from decimal import Decimal

from app.ai.model_catalog import (
    is_recommended,
    load_bundled,
    parse_catalog,
)

RAW = {
    "gpt-4o": {
        "litellm_provider": "openai",
        "mode": "chat",
        "input_cost_per_token": 2.5e-06,
        "output_cost_per_token": 1e-05,
        "max_input_tokens": 128000,
        "max_output_tokens": 16384,
        "supports_vision": True,
        "supports_function_calling": True,
    },
    "gpt-4o-no-prices": {
        "litellm_provider": "openai",
        "mode": "chat",
    },
    "text-embedding-3-small": {
        "litellm_provider": "openai",
        "mode": "embedding",
        "input_cost_per_token": 2e-08,
    },
    "gpt-4o-deprecated": {
        "litellm_provider": "openai",
        "mode": "chat",
        "deprecated": True,
    },
    "mistral/mistral-large-latest": {
        "litellm_provider": "mistral",
        "mode": "chat",
        "input_cost_per_token": 5e-07,
        "output_cost_per_token": 1.5e-06,
        "max_input_tokens": 262144,
    },
    "some-random-model": {
        "litellm_provider": "fireworks_ai",
        "mode": "chat",
    },
    "not-a-dict": 42,
}


def test_parse_catalog_keeps_supported_chat_models() -> None:
    entries = {entry.model_id: entry for entry in parse_catalog(RAW)}
    assert set(entries) == {
        "openai/gpt-4o",
        "openai/gpt-4o-no-prices",
        "mistral/mistral-large-latest",
    }


def test_parse_catalog_canonicalizes_bare_and_prefixed_keys() -> None:
    entries = {entry.model_id: entry for entry in parse_catalog(RAW)}
    assert entries["openai/gpt-4o"].vendor == "openai"
    assert entries["openai/gpt-4o"].display_name == "gpt-4o"
    assert entries["mistral/mistral-large-latest"].vendor == "mistral"


def test_parse_catalog_converts_costs_to_per_mtok() -> None:
    entry = {e.model_id: e for e in parse_catalog(RAW)}["openai/gpt-4o"]
    assert entry.input_price_per_mtok == Decimal("2.500000")
    assert entry.output_price_per_mtok == Decimal("10.000000")
    assert entry.context_window == 128000
    assert entry.max_output_tokens == 16384
    assert entry.supports_vision is True
    assert entry.supports_function_calling is True
    assert entry.mode == "chat"


def test_parse_catalog_allows_missing_prices() -> None:
    entry = {e.model_id: e for e in parse_catalog(RAW)}["openai/gpt-4o-no-prices"]
    assert entry.input_price_per_mtok is None
    assert entry.output_price_per_mtok is None


def test_parse_catalog_dedupes_model_ids() -> None:
    duped = dict(RAW)
    duped["openai/gpt-4o"] = duped["gpt-4o"]
    ids = [e.model_id for e in parse_catalog(duped)]
    assert ids.count("openai/gpt-4o") == 1


def test_load_bundled_returns_supported_entries() -> None:
    entries = load_bundled()
    assert len(entries) > 50
    assert all(entry.vendor in {"openai", "anthropic", "google", "openrouter", "mistral", "groq"} for entry in entries)
    assert any(entry.model_id == "openai/gpt-4o" for entry in entries)


def test_is_recommended() -> None:
    assert is_recommended("openai", "openai/gpt-4o") is True
    assert is_recommended("openai", "openai/never-heard-of-it") is False
    assert is_recommended("custom", "openai/anything") is False
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_model_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ai.model_catalog'`

- [x] **Step 3: Write the parsing implementation**

Create `backend/app/ai/model_catalog.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

LITELLM_CATALOG_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "litellm/model_prices_and_context_window.json"
)
MIN_CATALOG_ENTRIES = 50

SUPPORTED_VENDORS: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "google",
    "openrouter": "openrouter",
    "mistral": "mistral",
    "groq": "groq",
}

RECOMMENDED_MODELS: dict[str, set[str]] = {
    "openai": {"openai/gpt-4o", "openai/gpt-4o-mini"},
    "anthropic": {"anthropic/claude-sonnet-4-5", "anthropic/claude-haiku-4-5"},
    "google": {"gemini/gemini-2.5-flash", "gemini/gemini-2.0-flash"},
    "openrouter": {"openrouter/anthropic/claude-sonnet-4"},
    "mistral": {"mistral/mistral-large-latest"},
    "groq": {"groq/llama-3.3-70b-versatile"},
}


@dataclass(frozen=True)
class CatalogEntry:
    vendor: str
    model_id: str
    display_name: str
    mode: str
    context_window: int | None
    max_output_tokens: int | None
    input_price_per_mtok: Decimal | None
    output_price_per_mtok: Decimal | None
    supports_vision: bool
    supports_function_calling: bool


def _per_mtok(cost: Any) -> Decimal | None:
    if cost is None:
        return None
    return (Decimal(str(cost)) * Decimal(1_000_000)).quantize(Decimal("0.000001"))


def parse_catalog(raw: dict[str, Any]) -> list[CatalogEntry]:
    entries: dict[str, CatalogEntry] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        provider = value.get("litellm_provider")
        vendor = SUPPORTED_VENDORS.get(provider)
        if vendor is None:
            continue
        mode = value.get("mode") or "chat"
        if mode not in ("chat", "completion"):
            continue
        if value.get("deprecated"):
            continue
        model_id = key if "/" in key else f"{provider}/{key}"
        if model_id in entries:
            continue
        max_tokens = value.get("max_tokens")
        entries[model_id] = CatalogEntry(
            vendor=vendor,
            model_id=model_id,
            display_name=model_id.rsplit("/", 1)[-1],
            mode="chat",
            context_window=value.get("max_input_tokens") or max_tokens,
            max_output_tokens=value.get("max_output_tokens") or max_tokens,
            input_price_per_mtok=_per_mtok(value.get("input_cost_per_token")),
            output_price_per_mtok=_per_mtok(value.get("output_cost_per_token")),
            supports_vision=bool(value.get("supports_vision")),
            supports_function_calling=bool(value.get("supports_function_calling")),
        )
    return list(entries.values())


def load_bundled() -> list[CatalogEntry]:
    import litellm

    return parse_catalog(litellm.model_cost)


def is_recommended(vendor: str, model_id: str) -> bool:
    return model_id in RECOMMENDED_MODELS.get(vendor, set())
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ai_model_catalog.py -v`
Expected: PASS (8 passed)

- [x] **Step 5: Lint and typecheck**

Run: `uv run ruff check . ../plugins && uv run mypy .`
Expected: exit 0

- [x] **Step 6: Commit**

```bash
git add backend/app/ai/model_catalog.py backend/tests/test_ai_model_catalog.py
git commit -m "feat(ai): model catalog parser and recommendations (GFM-12)"
```

---

### Task 4: Catalog seeding, query, refresh, and job factory

**Files:**
- Modify: `backend/app/ai/model_catalog.py` (append persistence section)
- Test: `backend/tests/test_ai_model_catalog.py` (append)

**Interfaces:**
- Consumes: `CatalogEntry`, `parse_catalog`, `load_bundled`, `is_recommended`, `LITELLM_CATALOG_URL`, `MIN_CATALOG_ENTRIES` (Task 3); `AiModelCatalog`, `AiModelCatalogSync` (Task 2).
- Produces: `CatalogSyncState` (frozen dataclass: `last_attempt_at, last_success_at, last_error, source`), `MODEL_CATALOG_REFRESH_JOB_ID`, `MODEL_CATALOG_REFRESH_CRON`, `ensure_seeded(session_factory) -> None`, `replace_catalog_entries(session, entries) -> None`, `get_entries(session, vendor, mode) -> list[AiModelCatalog]`, `get_sync_state(session) -> CatalogSyncState | None`, `refresh(session_factory, http_client, now) -> CatalogSyncState`, `make_refresh_job(session_factory, http_client, clock) -> Callable[[], Awaitable[None]]`.

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_ai_model_catalog.py`:

```python
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai import model_catalog
from app.ai.model_catalog import (
    CatalogEntry,
    ensure_seeded,
    get_entries,
    get_sync_state,
    make_refresh_job,
    refresh,
)
from app.models.ai import AiModelCatalog
from app.clock import TestClock


@pytest_asyncio.fixture
async def db_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _entry(model_id: str, vendor: str = "openai") -> CatalogEntry:
    return CatalogEntry(
        vendor=vendor, model_id=model_id, display_name=model_id.rsplit("/", 1)[-1],
        mode="chat", context_window=128000, max_output_tokens=4096,
        input_price_per_mtok=Decimal("1.000000"),
        output_price_per_mtok=Decimal("2.000000"),
        supports_vision=False, supports_function_calling=True,
    )


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_ensure_seeded_inserts_bundled_once(db_factory, monkeypatch) -> None:
    monkeypatch.setattr(model_catalog, "load_bundled", lambda: [_entry("openai/gpt-4o")])
    await ensure_seeded(db_factory)
    await ensure_seeded(db_factory)
    async with db_factory() as session:
        rows = list((await session.execute(select(AiModelCatalog))).scalars())
        assert [r.model_id for r in rows] == ["openai/gpt-4o"]
        state = await get_sync_state(session)
        assert state is not None
        assert state.source == "bundled"


@pytest.mark.asyncio
async def test_get_entries_filters_by_vendor_and_mode(db_factory) -> None:
    async with db_factory() as session, session.begin():
        session.add(AiModelCatalog(vendor="openai", model_id="openai/gpt-4o", display_name="gpt-4o", mode="chat"))
        session.add(AiModelCatalog(vendor="anthropic", model_id="anthropic/claude", display_name="claude", mode="chat"))
        session.add(AiModelCatalog(vendor="openai", model_id="openai/embed", display_name="embed", mode="embedding"))
    async with db_factory() as session:
        rows = await get_entries(session, vendor="openai", mode="chat")
        assert [r.model_id for r in rows] == ["openai/gpt-4o"]
        assert {r.model_id for r in await get_entries(session, vendor=None, mode="chat")} == {
            "openai/gpt-4o", "anthropic/claude",
        }


@pytest.mark.asyncio
async def test_refresh_success_replaces_rows(db_factory) -> None:
    async with db_factory() as session, session.begin():
        session.add(AiModelCatalog(vendor="openai", model_id="openai/old", display_name="old", mode="chat"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "gpt-4o": {"litellm_provider": "openai", "mode": "chat", "max_input_tokens": 128000},
        })

    client = _client(handler)
    now = datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc)
    state = await refresh(db_factory, client, now)
    await client.aclose()
    assert state.last_error is None
    assert state.source == "github"
    assert state.last_success_at == now
    async with db_factory() as session:
        rows = list((await session.execute(select(AiModelCatalog))).scalars())
        assert [r.model_id for r in rows] == ["openai/gpt-4o"]


@pytest.mark.asyncio
async def test_refresh_failure_keeps_existing_rows(db_factory) -> None:
    async with db_factory() as session, session.begin():
        session.add(AiModelCatalog(vendor="openai", model_id="openai/keep", display_name="keep", mode="chat"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = _client(handler)
    now = datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc)
    state = await refresh(db_factory, client, now)
    await client.aclose()
    assert state.last_error is not None
    assert state.last_attempt_at == now
    async with db_factory() as session:
        rows = list((await session.execute(select(AiModelCatalog))).scalars())
        assert [r.model_id for r in rows] == ["openai/keep"]


@pytest.mark.asyncio
async def test_refresh_rejects_too_few_entries(db_factory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "gpt-4o": {"litellm_provider": "openai", "mode": "chat"},
        })

    client = _client(handler)
    state = await refresh(db_factory, client, datetime(2026, 9, 17, tzinfo=timezone.utc))
    await client.aclose()
    assert state.last_error is not None
    assert "supported entries" in state.last_error


@pytest.mark.asyncio
async def test_refresh_job_runs(db_factory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "gpt-4o": {"litellm_provider": "openai", "mode": "chat"},
        })

    client = _client(handler)
    clock = TestClock(datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc))
    job = make_refresh_job(db_factory, client, clock)
    await job()
    await client.aclose()
    async with db_factory() as session:
        state = await get_sync_state(session)
        assert state is not None
        assert state.last_attempt_at == clock.now()
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_model_catalog.py -v`
Expected: FAIL with `ImportError: cannot import name 'CatalogEntry'` (or `'ensure_seeded'`)

- [x] **Step 3a: Move the persistence imports to the top of the module**

Ruff's `E402` forbids module-level imports below definitions, so **replace the entire top import block** of `backend/app/ai/model_catalog.py` with:

```python
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..clock import Clock
from ..models.ai import AiModelCatalog, AiModelCatalogSync

logger = logging.getLogger(__name__)
```

(The `LITELLM_CATALOG_URL` / `SUPPORTED_VENDORS` / `RECOMMENDED_MODELS` constants and everything from Task 3 stay immediately below this block, unchanged.)

- [x] **Step 3b: Append the persistence implementation**

Append the following **below** the Task 3 code (no import lines inside this block):

```python
MODEL_CATALOG_REFRESH_JOB_ID = "system-ai-model-catalog-refresh"
MODEL_CATALOG_REFRESH_CRON = "0 4 * * *"


@dataclass(frozen=True)
class CatalogSyncState:
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    source: str | None


async def replace_catalog_entries(session: AsyncSession, entries: list[CatalogEntry]) -> None:
    await session.execute(delete(AiModelCatalog))
    session.add_all(
        [
            AiModelCatalog(
                vendor=entry.vendor,
                model_id=entry.model_id,
                display_name=entry.display_name,
                mode=entry.mode,
                context_window=entry.context_window,
                max_output_tokens=entry.max_output_tokens,
                input_price_per_mtok=entry.input_price_per_mtok,
                output_price_per_mtok=entry.output_price_per_mtok,
                supports_vision=entry.supports_vision,
                supports_function_calling=entry.supports_function_calling,
            )
            for entry in entries
        ]
    )


async def ensure_seeded(
    session_factory: Callable[[], AsyncSession],
) -> None:
    async with session_factory() as session:
        count = (
            await session.execute(select(func.count()).select_from(AiModelCatalog))
        ).scalar_one()
        if count:
            return
    entries = load_bundled()
    async with session_factory() as session, session.begin():
        sync = await session.get(AiModelCatalogSync, 1)
        if sync is None:
            sync = AiModelCatalogSync(id=1)
            session.add(sync)
        await replace_catalog_entries(session, entries)
        sync.last_success_at = datetime.now(timezone.utc)
        sync.last_error = None
        sync.source = "bundled"


async def get_entries(
    session: AsyncSession, vendor: str | None, mode: str
) -> list[AiModelCatalog]:
    statement = select(AiModelCatalog).where(AiModelCatalog.mode == mode)
    if vendor is not None:
        statement = statement.where(AiModelCatalog.vendor == vendor)
    statement = statement.order_by(AiModelCatalog.vendor, AiModelCatalog.model_id)
    return list((await session.execute(statement)).scalars())


async def get_sync_state(session: AsyncSession) -> CatalogSyncState | None:
    row = await session.get(AiModelCatalogSync, 1)
    if row is None:
        return None
    return CatalogSyncState(
        last_attempt_at=row.last_attempt_at,
        last_success_at=row.last_success_at,
        last_error=row.last_error,
        source=row.source,
    )


async def refresh(
    session_factory: Callable[[], AsyncSession],
    http_client: httpx.AsyncClient,
    now: datetime,
) -> CatalogSyncState:
    entries: list[CatalogEntry] = []
    error: str | None = None
    try:
        response = await http_client.get(LITELLM_CATALOG_URL)
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict):
            raise ValueError("catalog payload is not an object")
        entries = parse_catalog(raw)
        if len(entries) < MIN_CATALOG_ENTRIES:
            raise ValueError(
                f"catalog payload yielded only {len(entries)} supported entries"
            )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.error("ai model catalog refresh failed: %s", error)
    async with session_factory() as session, session.begin():
        sync = await session.get(AiModelCatalogSync, 1)
        if sync is None:
            sync = AiModelCatalogSync(id=1)
            session.add(sync)
        sync.last_attempt_at = now
        if error is None:
            await replace_catalog_entries(session, entries)
            sync.last_success_at = now
            sync.last_error = None
            sync.source = "github"
        else:
            sync.last_error = error
        await session.flush()
        return CatalogSyncState(
            last_attempt_at=sync.last_attempt_at,
            last_success_at=sync.last_success_at,
            last_error=sync.last_error,
            source=sync.source,
        )


def make_refresh_job(
    session_factory: Callable[[], AsyncSession],
    http_client: httpx.AsyncClient,
    clock: Clock,
) -> Callable[[], Awaitable[None]]:
    async def job() -> None:
        state = await refresh(session_factory, http_client, clock.now())
        if state.last_error:
            logger.warning("ai model catalog refresh failed: %s", state.last_error)
        else:
            logger.info("ai model catalog refreshed: source=%s", state.source)

    return job
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ai_model_catalog.py -v`
Expected: PASS (14 passed)

- [x] **Step 5: Lint and typecheck**

Run: `uv run ruff check . ../plugins && uv run mypy .`
Expected: exit 0

- [x] **Step 6: Commit**

```bash
git add backend/app/ai/model_catalog.py backend/tests/test_ai_model_catalog.py
git commit -m "feat(ai): catalog seeding, refresh, and job factory (GFM-12)"
```

---

### Task 5: Catalog/preset API, write normalization, HTTP client

**Files:**
- Modify: `backend/app/schemas/ai_admin.py`
- Modify: `backend/app/routes/ai_admin.py`
- Modify: `backend/app/main.py` (create and close `app.state.catalog_http_client`)
- Test: `backend/tests/test_ai_admin_api.py`
- Docs: `backend/docs/api.md`, `backend/docs/data-model.md`

**Interfaces:**
- Consumes: `PROVIDER_PRESETS` (Task 1); `ensure_seeded`, `get_entries`, `get_sync_state`, `refresh`, `is_recommended` (Tasks 3–4); `normalize_provider_input` (Task 1).
- Produces: `ProviderPresetOut`, `ModelCatalogEntryOut`, `ModelCatalogSyncOut`, `ModelCatalogOut`; endpoints `GET /admin/ai/provider-presets`, `GET /admin/ai/model-catalog`, `POST /admin/ai/model-catalog/refresh`.

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_ai_admin_api.py`:

```python
@pytest.mark.asyncio
async def test_provider_presets_endpoint(admin_http):
    response = await admin_http.get("/admin/ai/provider-presets")
    assert response.status_code == 200
    keys = [preset["vendor_key"] for preset in response.json()]
    assert keys == ["openai", "anthropic", "google", "openrouter", "mistral", "groq", "custom"]
    custom = response.json()[-1]
    assert custom["requires_base_url"] is True
    assert custom["supports_catalog"] is False


@pytest.mark.asyncio
async def test_model_catalog_seeds_and_filters(settings_app, admin_http, monkeypatch):
    from app.ai import model_catalog

    app, _ = settings_app
    monkeypatch.setattr(model_catalog, "load_bundled", lambda: [
        model_catalog.CatalogEntry(
            vendor="openai", model_id="openai/gpt-4o", display_name="gpt-4o",
            mode="chat", context_window=128000, max_output_tokens=16384,
            input_price_per_mtok=Decimal("2.500000"),
            output_price_per_mtok=Decimal("10.000000"),
            supports_vision=True, supports_function_calling=True,
        ),
        model_catalog.CatalogEntry(
            vendor="anthropic", model_id="anthropic/claude", display_name="claude",
            mode="chat", context_window=200000, max_output_tokens=8192,
            input_price_per_mtok=None, output_price_per_mtok=None,
            supports_vision=False, supports_function_calling=True,
        ),
    ])
    response = await admin_http.get("/admin/ai/model-catalog", params={"vendor": "openai"})
    assert response.status_code == 200
    body = response.json()
    assert [entry["model_id"] for entry in body["entries"]] == ["openai/gpt-4o"]
    entry = body["entries"][0]
    assert entry["is_recommended"] is True
    assert entry["supports_vision"] is True
    assert body["sync"]["source"] == "bundled"


@pytest.mark.asyncio
async def test_model_catalog_refresh_endpoint(settings_app, admin_http, monkeypatch):
    from app.ai import model_catalog

    app, _ = settings_app
    entries = [
        model_catalog.CatalogEntry(
            vendor="openai", model_id=f"openai/model-{i}", display_name=f"model-{i}",
            mode="chat", context_window=1000, max_output_tokens=100,
            input_price_per_mtok=None, output_price_per_mtok=None,
            supports_vision=False, supports_function_calling=False,
        )
        for i in range(60)
    ]
    monkeypatch.setattr(model_catalog, "parse_catalog", lambda raw: entries)

    def handler(request):
        return httpx.Response(200, json={"ok": True})

    app.state.catalog_http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    response = await admin_http.post("/admin/ai/model-catalog/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "github"
    assert body["last_error"] is None


@pytest.mark.asyncio
async def test_create_provider_normalizes_legacy_type(settings_app, admin_http):
    _, factory = settings_app
    create = await admin_http.post("/admin/ai/providers", json={
        "name": "legacy", "provider_type": "openai_compatible",
        "base_url": "https://api.example.com/v1", "api_key": "k", "model": "gpt-4o-mini",
    })
    assert create.status_code == 201
    provider_id = create.json()["id"]
    async with factory() as session:
        row = await session.get(AiProviderConfig, provider_id)
        assert row.provider_type == "litellm"
        assert row.model == "openai/gpt-4o-mini"
```

Add `from decimal import Decimal` and `import httpx` to the imports at the top of `backend/tests/test_ai_admin_api.py`.

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_admin_api.py -v -k "presets or model_catalog or normalizes_legacy"`
Expected: FAIL with 404 (endpoints missing)

- [x] **Step 3: Add the schemas**

Append to `backend/app/schemas/ai_admin.py`:

```python
class ProviderPresetOut(BaseModel):
    vendor_key: str
    label: str
    model_prefix: str
    default_base_url: str
    requires_base_url: bool
    api_key_env_hint: str
    docs_url: str
    supports_catalog: bool


class ModelCatalogEntryOut(BaseModel):
    model_id: str
    vendor: str
    display_name: str
    context_window: int | None
    max_output_tokens: int | None
    input_price_per_mtok: Decimal | None
    output_price_per_mtok: Decimal | None
    supports_vision: bool
    supports_function_calling: bool
    is_recommended: bool


class ModelCatalogSyncOut(BaseModel):
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    source: str | None


class ModelCatalogOut(BaseModel):
    entries: list[ModelCatalogEntryOut]
    sync: ModelCatalogSyncOut
```

- [x] **Step 4: Add the routes and normalization**

In `backend/app/routes/ai_admin.py`, add to the imports:

```python
from dataclasses import asdict

from ..ai.model_catalog import (
    ensure_seeded,
    get_entries,
    get_sync_state,
    is_recommended,
    refresh,
)
from ..ai.presets import PROVIDER_PRESETS, normalize_provider_input
from ..schemas.ai_admin import (
    ModelCatalogEntryOut,
    ModelCatalogOut,
    ModelCatalogSyncOut,
    ProviderPresetOut,
)
```

Add the type alias next to the other aliases:

```python
CatalogMode = Annotated[str, Query(pattern="^(chat|completion)$")]
```

Add the normalization helper after `_is_deadlock`:

```python
def _normalize_provider(values: dict[str, Any]) -> dict[str, Any]:
    model = values.get("model")
    if model is None:
        return values
    provider_type, normalized = normalize_provider_input(
        model, str(values.get("provider_type", "litellm"))
    )
    values["provider_type"] = provider_type
    values["model"] = normalized
    return values
```

In `create_provider`, replace `row = AiProviderConfig(**payload.model_dump())` with:

```python
        row = AiProviderConfig(**_normalize_provider(payload.model_dump()))
```

In `update_provider`, replace `updates = payload.model_dump(exclude_unset=True)` with:

```python
        updates = _normalize_provider(payload.model_dump(exclude_unset=True))
```

Append the three endpoints at the end of the file:

```python
@router.get("/admin/ai/provider-presets", response_model=list[ProviderPresetOut])
async def list_provider_presets(_admin: AdminUser) -> list[ProviderPresetOut]:
    return [ProviderPresetOut(**asdict(preset)) for preset in PROVIDER_PRESETS]


@router.get("/admin/ai/model-catalog", response_model=ModelCatalogOut)
async def get_model_catalog(
    request: Request,
    _admin: AdminUser,
    db_session: DbSession,
    vendor: str | None = None,
    mode: CatalogMode = "chat",
) -> ModelCatalogOut:
    session = _require_db(db_session)
    factory = request.app.state.db_session_factory
    if factory is not None:
        await ensure_seeded(factory)
    rows = await get_entries(session, vendor=vendor, mode=mode)
    state = await get_sync_state(session)
    sync = ModelCatalogSyncOut(
        last_attempt_at=state.last_attempt_at if state else None,
        last_success_at=state.last_success_at if state else None,
        last_error=state.last_error if state else None,
        source=state.source if state else None,
    )
    return ModelCatalogOut(
        entries=[
            ModelCatalogEntryOut(
                model_id=row.model_id,
                vendor=row.vendor,
                display_name=row.display_name,
                context_window=row.context_window,
                max_output_tokens=row.max_output_tokens,
                input_price_per_mtok=row.input_price_per_mtok,
                output_price_per_mtok=row.output_price_per_mtok,
                supports_vision=row.supports_vision,
                supports_function_calling=row.supports_function_calling,
                is_recommended=is_recommended(row.vendor, row.model_id),
            )
            for row in rows
        ],
        sync=sync,
    )


@router.post("/admin/ai/model-catalog/refresh", response_model=ModelCatalogSyncOut)
async def refresh_model_catalog(
    request: Request,
    _admin: AdminUser,
    db_session: DbSession,
) -> ModelCatalogSyncOut:
    _require_db(db_session)
    factory = request.app.state.db_session_factory
    client = getattr(request.app.state, "catalog_http_client", None)
    if factory is None or client is None:
        raise HTTPException(status_code=503, detail="model catalog unavailable")
    state = await refresh(factory, client, request.app.state.clock.now())
    return ModelCatalogSyncOut(
        last_attempt_at=state.last_attempt_at,
        last_success_at=state.last_success_at,
        last_error=state.last_error,
        source=state.source,
    )
```

- [x] **Step 5: Wire the HTTP client lifecycle**

In `backend/app/main.py`, next to `app.state.image_http_client = image_http_client` (inside the `if app.state.db_session_factory is not None:` block), add:

```python
        app.state.catalog_http_client = httpx.AsyncClient()
```

In the `lifespan` shutdown section, next to the `image_http_client` close, add:

```python
        catalog_http_client = getattr(application.state, "catalog_http_client", None)
        if catalog_http_client is not None:
            await catalog_http_client.aclose()
```

- [x] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_admin_api.py -v`
Expected: PASS (all existing + 4 new)

- [x] **Step 7: Update the backend docs**

In `backend/docs/api.md`, after the existing provider bullets (around line 47), add:

```markdown
- `GET /admin/ai/provider-presets` — wizard presets `[{vendor_key, label, model_prefix, default_base_url, requires_base_url, api_key_env_hint, docs_url, supports_catalog}]`
- `GET /admin/ai/model-catalog?vendor=&mode=chat` — `{entries: [{model_id, vendor, display_name, context_window, max_output_tokens, input_price_per_mtok, output_price_per_mtok, supports_vision, supports_function_calling, is_recommended}], sync: {last_attempt_at, last_success_at, last_error, source}}`; lazily seeds from the installed LiteLLM price data when empty
- `POST /admin/ai/model-catalog/refresh` — fetch the upstream LiteLLM catalog; on failure keeps the last-good catalog and records `last_error` in the sync payload
- `POST /admin/ai/providers` / `PATCH /admin/ai/providers/{id}` — `provider_type` is normalized to `litellm` on write; a legacy `openai_compatible` payload with an unprefixed model is stored as `openai/<model>`
```

In `backend/docs/data-model.md`, after the `ai_provider_configs` table (around line 257), add the two table summaries:

```markdown
| `ai_model_catalog` | `vendor`, `model_id` (unique, LiteLLM `vendor/model`), `display_name`, `mode`, `context_window`, `max_output_tokens`, `input_price_per_mtok`, `output_price_per_mtok`, `supports_vision`, `supports_function_calling`; refresh-replaceable snapshot of the LiteLLM price catalog |
| `ai_model_catalog_sync` | Singleton (`id=1`) freshness state: `last_attempt_at`, `last_success_at`, `last_error`, `source` (`bundled` \| `github`) |
```

- [x] **Step 8: Lint and typecheck**

Run: `uv run ruff check . ../plugins && uv run mypy .`
Expected: exit 0

- [x] **Step 9: Commit**

```bash
git add backend/app/schemas/ai_admin.py backend/app/routes/ai_admin.py backend/app/main.py backend/tests/test_ai_admin_api.py backend/docs/api.md backend/docs/data-model.md
git commit -m "feat(ai): catalog and preset admin API, provider normalization (GFM-12)"
```

---

### Task 6: Scheduled catalog refresh job

**Files:**
- Modify: `backend/app/main.py` (register the job in `lifespan`)
- Test: `backend/tests/test_ai_admin_api.py` (append one job-registration test)
- Docs: `backend/docs/architecture.md`, `docs/decisions.md`

**Interfaces:**
- Consumes: `make_refresh_job`, `MODEL_CATALOG_REFRESH_JOB_ID`, `MODEL_CATALOG_REFRESH_CRON` (Task 4).
- Produces: no new API; the app registers `system-ai-model-catalog-refresh` at startup.

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_ai_admin_api.py`:

```python
@pytest.mark.asyncio
async def test_model_catalog_refresh_job_constants():
    from app.ai import model_catalog

    assert model_catalog.MODEL_CATALOG_REFRESH_JOB_ID == "system-ai-model-catalog-refresh"
    assert model_catalog.MODEL_CATALOG_REFRESH_CRON == "0 4 * * *"
```

- [x] **Step 2: Run test to verify it fails (or confirms Task 4)

Run: `uv run pytest tests/test_ai_admin_api.py::test_model_catalog_refresh_job_constants -v`
Expected: PASS once Task 4 is merged; if it fails, Task 4's constants are missing. The job's runtime behavior is covered by `test_refresh_job_runs` in `test_ai_model_catalog.py`; this test only pins the identifiers the lifespan registers.

- [x] **Step 3: Register the job in lifespan**

In `backend/app/main.py`, inside the `if scheduler_service is not None:` block, after the AI purge job registration, add:

```python
                from .ai.model_catalog import (
                    MODEL_CATALOG_REFRESH_CRON,
                    MODEL_CATALOG_REFRESH_JOB_ID,
                    make_refresh_job,
                )

                catalog_job = make_refresh_job(
                    application.state.db_session_factory,
                    application.state.catalog_http_client,
                    application.state.clock,
                )
                scheduler_service.register_system_job(
                    MODEL_CATALOG_REFRESH_JOB_ID, MODEL_CATALOG_REFRESH_CRON, catalog_job
                )
```

- [x] **Step 4: Run the backend suite**

Run: `uv run pytest tests/test_ai_admin_api.py tests/test_ai_model_catalog.py -v`
Expected: PASS

- [x] **Step 5: Update the docs**

In `backend/docs/architecture.md`, in the AI section near the router transport paragraph (around line 188), add:

```markdown
- **Model catalog**: `app/ai/model_catalog.py` snapshot of LiteLLM's `model_prices_and_context_window.json`. Lazy-seeds from the installed `litellm.model_cost` when empty, refreshed from the upstream raw JSON by the daily `system-ai-model-catalog-refresh` job (`0 4 * * *`) or `POST /admin/ai/model-catalog/refresh`. A failed refresh keeps the last-good catalog and records the error; the catalog never blocks provider use.
```

Append to `docs/decisions.md` (matching the existing Topic / Decision / Rationale format):

```markdown
## 2026-09-17 — AI provider wizard & model catalog (GFM-12)

**Topic:** Provider creation UX and the model list behind it.

**Decision:** Catalog seeds from the installed `litellm.model_cost` and refreshes daily from the upstream LiteLLM GitHub JSON (`0 4 * * *`) plus a manual admin trigger; refresh is fail-open and keeps the last-good catalog. `provider_type` is normalized to `litellm` on write (legacy `openai_compatible` mapped to `openai/<model>`), Router mapping unchanged. Azure preset / `api_version` deferred. `is_recommended` is a static per-vendor list matched at read, not a stored column. The wizard defers connection testing to Finish, which creates the provider and immediately calls the existing test endpoint.

**Rationale:** The bundled catalog works offline and matches the installed LiteLLM model strings exactly; GitHub refresh keeps it current without a new dependency. Dropping per-row freshness/recommended columns removes state that can drift. Reusing the existing test endpoint avoids a second probe path.
```

- [x] **Step 6: Lint and typecheck**

Run: `uv run ruff check . ../plugins && uv run mypy .`
Expected: exit 0

- [x] **Step 7: Commit**

```bash
git add backend/app/main.py backend/tests/test_ai_admin_api.py backend/docs/architecture.md docs/decisions.md
git commit -m "feat(ai): schedule model catalog refresh job (GFM-12)"
```

---

### Task 7: Frontend types, query keys, and catalog hooks

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/queryKeys.ts`
- Modify: `frontend/src/api/hooks.ts`
- Test: `frontend/src/api/aiCatalogHooks.test.tsx`

**Interfaces:**
- Consumes: backend endpoints from Task 5.
- Produces: `ProviderPreset`, `ModelCatalogEntry`, `ModelCatalogSync`, `ModelCatalog` types; `queryKeys.ai.providerPresets`, `queryKeys.ai.modelCatalog(vendor, mode)`; hooks `useProviderPresets()`, `useModelCatalog(vendor: string | null, mode?: 'chat' | 'completion')`, `useRefreshModelCatalog()`.

- [x] **Step 1: Write the failing test**

Create `frontend/src/api/aiCatalogHooks.test.tsx`:

```tsx
import { beforeAll, describe, expect, it } from 'vitest';
import { waitFor } from '@testing-library/react';
import i18n from '../i18n';
import { renderHook } from '../test/render';
import { stubFetch } from '../test/fetch';
import { useModelCatalog, useProviderPresets } from './hooks';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeAll(async () => {
  await i18n.loadNamespaces('admin');
});

describe('AI catalog hooks', () => {
  it('loads provider presets', async () => {
    stubFetch((url) => {
      if (url === '/admin/ai/provider-presets') {
        return jsonResponse([
          {
            vendor_key: 'openai', label: 'OpenAI', model_prefix: 'openai',
            default_base_url: '', requires_base_url: false,
            api_key_env_hint: 'OPENAI_API_KEY', docs_url: 'https://x', supports_catalog: true,
          },
        ]);
      }
      return jsonResponse({});
    });
    const { result } = renderHook(() => useProviderPresets());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].vendor_key).toBe('openai');
  });

  it('loads the model catalog for a vendor', async () => {
    stubFetch((url) => {
      if (url.startsWith('/admin/ai/model-catalog')) {
        return jsonResponse({
          entries: [
            {
              model_id: 'openai/gpt-4o', vendor: 'openai', display_name: 'gpt-4o',
              context_window: 128000, max_output_tokens: 16384,
              input_price_per_mtok: '2.500000', output_price_per_mtok: '10.000000',
              supports_vision: true, supports_function_calling: true, is_recommended: true,
            },
          ],
          sync: { last_attempt_at: null, last_success_at: null, last_error: null, source: 'bundled' },
        });
      }
      return jsonResponse({});
    });
    const { result } = renderHook(() => useModelCatalog('openai'));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.entries[0].model_id).toBe('openai/gpt-4o');
    expect(result.current.data?.sync.source).toBe('bundled');
  });

  it('does not fetch when vendor is null', () => {
    const fetchMock = stubFetch(() => jsonResponse({}));
    renderHook(() => useModelCatalog(null));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run from `frontend/`: `npm run test -- src/api/aiCatalogHooks.test.tsx`
Expected: FAIL — `useProviderPresets` is not exported

- [x] **Step 3: Add the types**

Append to `frontend/src/api/types.ts`:

```ts
export type ProviderPreset = {
  vendor_key: string;
  label: string;
  model_prefix: string;
  default_base_url: string;
  requires_base_url: boolean;
  api_key_env_hint: string;
  docs_url: string;
  supports_catalog: boolean;
};

export type ModelCatalogEntry = {
  model_id: string;
  vendor: string;
  display_name: string;
  context_window: number | null;
  max_output_tokens: number | null;
  input_price_per_mtok: string | null;
  output_price_per_mtok: string | null;
  supports_vision: boolean;
  supports_function_calling: boolean;
  is_recommended: boolean;
};

export type ModelCatalogSync = {
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  source: string | null;
};

export type ModelCatalog = {
  entries: ModelCatalogEntry[];
  sync: ModelCatalogSync;
};
```

- [x] **Step 4: Add the query keys**

In `frontend/src/api/queryKeys.ts`, inside the `ai` object, after `usageTimeseries`, add:

```ts
    providerPresets: ['ai', 'provider-presets'] as const,
    modelCatalog: (vendor: string | null, mode: string) =>
      ['ai', 'model-catalog', vendor, mode] as const,
```

- [x] **Step 5: Add the hooks**

In `frontend/src/api/hooks.ts`, add `ModelCatalog`, `ProviderPreset` to the `import type { ... } from './types'` list, then append after `useTestAiProvider`:

```ts
export function useProviderPresets() {
  return useQuery({
    queryKey: queryKeys.ai.providerPresets,
    queryFn: () => apiGet<ProviderPreset[]>('/admin/ai/provider-presets'),
  });
}

export function useModelCatalog(vendor: string | null, mode: 'chat' | 'completion' = 'chat') {
  return useQuery({
    queryKey: queryKeys.ai.modelCatalog(vendor, mode),
    queryFn: () =>
      apiGet<ModelCatalog>(`/admin/ai/model-catalog?vendor=${vendor}&mode=${mode}`),
    enabled: vendor !== null,
  });
}

export function useRefreshModelCatalog() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<ModelCatalogSync>('/admin/ai/model-catalog/refresh'),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['ai', 'model-catalog'] });
    },
  });
}
```

Add `ModelCatalogSync` to the same `import type` list.

Then widen the existing `useUpdateAiProvider` payload type so the wizard can pass the normalized `provider_type`. In its inline `mutationFn` parameter type (currently listing `id`, `api_key?`, `name?`, `base_url?`, `model?`, `input_price_per_mtok?`, `output_price_per_mtok?`, `max_concurrency?`, `timeout_s?`, `enabled?`, `tier?`), add one property:

```ts
      provider_type?: 'litellm' | 'openai_compatible';
```

- [x] **Step 6: Run test to verify it passes**

Run: `npm run test -- src/api/aiCatalogHooks.test.tsx`
Expected: PASS (3 passed)

- [x] **Step 7: Typecheck**

Run: `npm run typecheck`
Expected: exit 0

- [x] **Step 8: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/queryKeys.ts frontend/src/api/hooks.ts frontend/src/api/aiCatalogHooks.test.tsx
git commit -m "feat(api): AI provider preset and model catalog hooks (GFM-12)"
```

---

### Task 8: Provider wizard (create + edit)

**Files:**
- Create: `frontend/src/features/admin/ai/ProviderWizard.tsx`
- Modify: `frontend/src/features/admin/ai/ProvidersPage.tsx`
- Modify: `frontend/public/locales/en/admin.json`, `frontend/public/locales/de/admin.json`
- Test: `frontend/src/features/admin/ai/ProviderWizard.test.tsx`
- Test: `frontend/src/features/admin/ai/ProvidersPage.test.tsx` (rewrite create flow)

**Interfaces:**
- Consumes: `useProviderPresets`, `useModelCatalog`, `useCreateAiProvider`, `useUpdateAiProvider`, `useTestAiProvider` (Task 7); `ProviderPreset`, `ModelCatalogEntry` (Task 7).
- Produces: `ProviderWizard` component with props `{ opened: boolean; provider: AiProvider | null; presetKey: string; onClose: () => void }`.

- [x] **Step 1: Write the failing wizard test**

Create `frontend/src/features/admin/ai/ProviderWizard.test.tsx`:

```tsx
import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import { ProviderWizard } from './ProviderWizard';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const presets = [
  {
    vendor_key: 'openai', label: 'OpenAI', model_prefix: 'openai',
    default_base_url: '', requires_base_url: false,
    api_key_env_hint: 'OPENAI_API_KEY', docs_url: 'https://docs', supports_catalog: true,
  },
  {
    vendor_key: 'custom', label: 'OpenAI-kompatibel (custom)', model_prefix: 'openai',
    default_base_url: '', requires_base_url: true,
    api_key_env_hint: '', docs_url: '', supports_catalog: false,
  },
];

const catalog = {
  entries: [
    {
      model_id: 'openai/gpt-4o', vendor: 'openai', display_name: 'gpt-4o',
      context_window: 128000, max_output_tokens: 16384,
      input_price_per_mtok: '2.500000', output_price_per_mtok: '10.000000',
      supports_vision: true, supports_function_calling: true, is_recommended: true,
    },
  ],
  sync: { last_attempt_at: null, last_success_at: null, last_error: null, source: 'bundled' },
};

beforeAll(async () => {
  await i18n.loadNamespaces('admin');
});

beforeEach(() => {
  stubFetch((url, init) => {
    if (url === '/admin/ai/provider-presets') return jsonResponse(presets);
    if (url.startsWith('/admin/ai/model-catalog')) return jsonResponse(catalog);
    if (url === '/admin/ai/providers' && init?.method === 'POST') {
      return jsonResponse({ ...catalog.entries[0], id: 5, name: 'x', tier: 'bulk', enabled: true }, 201);
    }
    if (url === '/admin/ai/providers/5/test') {
      return jsonResponse({ status: 'ok', latency_ms: 12 });
    }
    return jsonResponse({});
  });
});

describe('ProviderWizard', () => {
  it('creates a provider in 3 steps and auto-tests it', async () => {
    const posts: unknown[] = [];
    stubFetch((url, init) => {
      if (url === '/admin/ai/provider-presets') return jsonResponse(presets);
      if (url.startsWith('/admin/ai/model-catalog')) return jsonResponse(catalog);
      if (url === '/admin/ai/providers' && init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)));
        return jsonResponse({ ...catalog.entries[0], id: 5 }, 201);
      }
      if (url === '/admin/ai/providers/5/test') {
        return jsonResponse({ status: 'ok', latency_ms: 12 });
      }
      return jsonResponse({});
    });

    render(<ProviderWizard opened provider={null} presetKey="openai" onClose={() => {}} />);
    fireEvent.click(await screen.findByTestId('ai-wizard-preset-openai'));
    fireEvent.click(screen.getByTestId('ai-wizard-next'));
    fireEvent.change(screen.getByTestId('ai-wizard-api-key'), { target: { value: 'sk-test' } });
    fireEvent.click(screen.getByTestId('ai-wizard-next'));
    await waitFor(() => expect(screen.getByTestId('ai-wizard-model-select')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('ai-wizard-finish'));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      provider_type: 'litellm',
      model: 'openai/gpt-4o',
      api_key: 'sk-test',
      tier: 'bulk',
    });
    await waitFor(() => expect(screen.getByTestId('ai-wizard-result')).toBeInTheDocument());
  });

  it('requires base_url and a free model for the custom preset', async () => {
    render(<ProviderWizard opened provider={null} presetKey="custom" onClose={() => {}} />);
    fireEvent.click(await screen.findByTestId('ai-wizard-preset-custom'));
    fireEvent.click(screen.getByTestId('ai-wizard-next'));
    fireEvent.change(screen.getByTestId('ai-wizard-api-key'), { target: { value: 'k' } });
    expect(screen.getByTestId('ai-wizard-next')).toBeDisabled();
    fireEvent.change(screen.getByTestId('ai-wizard-base-url'), {
      target: { value: 'http://localhost:11434/v1' },
    });
    fireEvent.click(screen.getByTestId('ai-wizard-next'));
    expect(await screen.findByTestId('ai-wizard-model-custom')).toBeInTheDocument();
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/features/admin/ai/ProviderWizard.test.tsx`
Expected: FAIL — cannot resolve `./ProviderWizard`

- [x] **Step 3: Add i18n keys**

In `frontend/public/locales/en/admin.json`, add a `wizard` object inside `ai`:

```json
"wizard": {
  "title": "Add AI provider",
  "editTitle": "Edit AI provider",
  "steps": { "provider": "Provider", "key": "API key", "model": "Model" },
  "docsHint": "Create an API key",
  "baseUrl": "Base URL",
  "modelHeading": "Choose a model",
  "modelCustom": "Model name",
  "sortBy": "Sort by",
  "sortPrice": "Price",
  "sortContext": "Context window",
  "recommended": "Recommended",
  "vision": "Vision",
  "tools": "Tools",
  "advanced": "Advanced options",
  "inputPrice": "Input price / Mtok",
  "outputPrice": "Output price / Mtok",
  "finish": "Create & test",
  "testOk": "Connection OK ({{latency}} ms)",
  "testFailed": "Test failed: {{code}}",
  "back": "Back",
  "next": "Next"
}
```

In `frontend/public/locales/de/admin.json`, add the same keys inside `ai`:

```json
"wizard": {
  "title": "AI-Anbieter hinzufügen",
  "editTitle": "AI-Anbieter bearbeiten",
  "steps": { "provider": "Anbieter", "key": "API-Key", "model": "Modell" },
  "docsHint": "API-Key erstellen",
  "baseUrl": "Base-URL",
  "modelHeading": "Modell wählen",
  "modelCustom": "Modellname",
  "sortBy": "Sortieren nach",
  "sortPrice": "Preis",
  "sortContext": "Kontextfenster",
  "recommended": "Empfohlen",
  "vision": "Vision",
  "tools": "Tools",
  "advanced": "Erweiterte Optionen",
  "inputPrice": "Input-Preis / Mtok",
  "outputPrice": "Output-Preis / Mtok",
  "finish": "Anlegen & testen",
  "testOk": "Verbindung OK ({{latency}} ms)",
  "testFailed": "Test fehlgeschlagen: {{code}}",
  "back": "Zurück",
  "next": "Weiter"
}
```

- [x] **Step 4: Write the wizard component**

Create `frontend/src/features/admin/ai/ProviderWizard.tsx`:

```tsx
import { useMemo, useState } from 'react';
import {
  Accordion, Alert, Anchor, Badge, Button, Card, Group, Modal, NumberInput,
  Radio, Select, Stack, Stepper, Switch, Text, TextInput,
} from '@mantine/core';
import { IconExternalLink } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import {
  useCreateAiProvider, useModelCatalog, useProviderPresets, useTestAiProvider,
  useUpdateAiProvider,
} from '../../../api/hooks';
import { notifyMutationError, notifySuccess } from '../../../app/notifications';
import type { AiProvider } from '../../../api/types';

type ProviderPayload = {
  name: string;
  provider_type: 'litellm';
  tier: 'bulk' | 'precision';
  base_url: string;
  model: string;
  max_concurrency: number;
  timeout_s: number;
  input_price_per_mtok: string | null;
  output_price_per_mtok: string | null;
  enabled: boolean;
  api_key?: string;
};

const CUSTOM = 'custom';

export function ProviderWizard({
  opened, provider, presetKey, onClose,
}: {
  opened: boolean;
  provider: AiProvider | null;
  presetKey: string;
  onClose: () => void;
}) {
  const { t } = useTranslation('admin');
  const presetsQuery = useProviderPresets();
  const createProvider = useCreateAiProvider();
  const updateProvider = useUpdateAiProvider();
  const testProvider = useTestAiProvider();

  const presets = presetsQuery.data ?? [];
  const [active, setActive] = useState(0);
  const [vendor, setVendor] = useState(presetKey);
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState(provider?.base_url ?? '');
  const [model, setModel] = useState(provider?.model ?? '');
  const [name, setName] = useState(provider?.name ?? '');
  const [tier, setTier] = useState<'bulk' | 'precision'>(provider?.tier ?? 'bulk');
  const [maxConcurrency, setMaxConcurrency] = useState(provider?.max_concurrency ?? 4);
  const [timeoutS, setTimeoutS] = useState(provider?.timeout_s ?? 30);
  const [inputPrice, setInputPrice] = useState<string | null>(provider?.input_price_per_mtok ?? null);
  const [outputPrice, setOutputPrice] = useState<string | null>(provider?.output_price_per_mtok ?? null);
  const [enabled, setEnabled] = useState(provider?.enabled ?? true);
  const [sortBy, setSortBy] = useState<'price' | 'context'>('price');
  const [testResult, setTestResult] = useState<string | null>(null);

  const preset = presets.find((item) => item.vendor_key === vendor);
  const isCustom = preset?.vendor_key === CUSTOM;
  const baseUrlRequired = preset?.requires_base_url ?? false;
  const catalogQuery = useModelCatalog(preset && preset.supports_catalog ? vendor : null);
  const entries = useMemo(() => catalogQuery.data?.entries ?? [], [catalogQuery.data]);

  const sortedEntries = useMemo(() => {
    const copy = [...entries];
    if (sortBy === 'price') {
      copy.sort(
        (a, b) => Number(a.input_price_per_mtok ?? 1e9) - Number(b.input_price_per_mtok ?? 1e9),
      );
    } else {
      copy.sort((a, b) => (b.context_window ?? 0) - (a.context_window ?? 0));
    }
    return copy;
  }, [entries, sortBy]);

  const recommended = useMemo(
    () => entries.find((entry) => entry.is_recommended) ?? entries[0] ?? null,
    [entries],
  );
  const effectiveModel = model || recommended?.model_id || '';
  const selectedEntry = entries.find((entry) => entry.model_id === effectiveModel) ?? null;
  const autoName =
    preset && effectiveModel
      ? `${preset.label} ${effectiveModel.split('/').pop()}`
      : '';
  const displayName = name || autoName;

  const canAdvance =
    active === 0
      ? Boolean(preset)
      : active === 1
        ? (apiKey !== '' || provider !== null) && (!baseUrlRequired || baseUrl !== '')
        : effectiveModel !== '';

  function submit() {
    const payload: ProviderPayload = {
      name: displayName || preset?.label || 'Provider',
      provider_type: 'litellm',
      tier,
      base_url: baseUrl,
      model: effectiveModel,
      max_concurrency: maxConcurrency,
      timeout_s: timeoutS,
      input_price_per_mtok: inputPrice,
      output_price_per_mtok: outputPrice,
      enabled,
      ...(apiKey !== '' ? { api_key: apiKey } : {}),
    };
    const runTest = (id: number) =>
      testProvider.mutate(id, {
        onSuccess: (result) =>
          setTestResult(
            result.status === 'ok'
              ? t('ai.wizard.testOk', { latency: result.latency_ms ?? 0 })
              : t('ai.wizard.testFailed', { code: result.error_code ?? 'unknown' }),
          ),
      });
    if (provider) {
      updateProvider.mutate(
        { id: provider.id, ...payload },
        {
          onSuccess: () => {
            notifySuccess(t('ai.saved'));
            runTest(provider.id);
          },
          onError: (error) => notifyMutationError(error, t('ai.saveFailed')),
        },
      );
    } else {
      createProvider.mutate(payload, {
        onSuccess: (created) => {
          notifySuccess(t('ai.saved'));
          runTest(created.id);
        },
        onError: (error) => notifyMutationError(error, t('ai.saveFailed')),
      });
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="lg"
      title={provider ? t('ai.wizard.editTitle') : t('ai.wizard.title')}
    >
      <Stepper active={active} onStepClick={setActive} data-testid="ai-wizard">
        <Stepper.Step label={t('ai.wizard.steps.provider')}>
          <Radio.Group value={vendor} onChange={setVendor} mt="md">
            <Stack>
              {presets.map((item) => (
                <Card
                  key={item.vendor_key}
                  withBorder
                  data-testid={`ai-wizard-preset-${item.vendor_key}`}
                  onClick={() => setVendor(item.vendor_key)}
                  style={{ cursor: 'pointer' }}
                >
                  <Group justify="space-between">
                    <Radio value={item.vendor_key} label={item.label} />
                    {item.docs_url ? (
                      <Anchor href={item.docs_url} target="_blank" onClick={(e) => e.stopPropagation()}>
                        {t('ai.wizard.docsHint')} <IconExternalLink size={14} />
                      </Anchor>
                    ) : null}
                  </Group>
                </Card>
              ))}
            </Stack>
          </Radio.Group>
        </Stepper.Step>

        <Stepper.Step label={t('ai.wizard.steps.key')}>
          <Stack mt="md">
            <TextInput
              type="password"
              label={t('ai.apiKey')}
              placeholder={provider ? t('ai.apiKeyUnchanged') : ''}
              value={apiKey}
              onChange={(event) => setApiKey(event.currentTarget.value)}
              data-testid="ai-wizard-api-key"
            />
            {baseUrlRequired ? (
              <TextInput
                label={t('ai.wizard.baseUrl')}
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.currentTarget.value)}
                data-testid="ai-wizard-base-url"
              />
            ) : null}
          </Stack>
        </Stepper.Step>

        <Stepper.Step label={t('ai.wizard.steps.model')}>
          <Stack mt="md">
            {isCustom ? (
              <TextInput
                label={t('ai.wizard.modelCustom')}
                value={model}
                onChange={(event) => setModel(event.currentTarget.value)}
                data-testid="ai-wizard-model-custom"
              />
            ) : (
              <>
                <Select
                  searchable
                  label={t('ai.wizard.modelHeading')}
                  data={sortedEntries.map((entry) => ({
                    value: entry.model_id,
                    label: entry.display_name,
                  }))}
                  value={effectiveModel || null}
                  onChange={(value) => setModel(value ?? '')}
                  data-testid="ai-wizard-model-select"
                />
                <Select
                  label={t('ai.wizard.sortBy')}
                  value={sortBy}
                  onChange={(value) => setSortBy(value === 'context' ? 'context' : 'price')}
                  data={[
                    { value: 'price', label: t('ai.wizard.sortPrice') },
                    { value: 'context', label: t('ai.wizard.sortContext') },
                  ]}
                />
              </>
            )}
            {selectedEntry ? (
              <Group gap="xs">
                {selectedEntry.is_recommended ? (
                  <Badge color="green">{t('ai.wizard.recommended')}</Badge>
                ) : null}
                {selectedEntry.supports_vision ? (
                  <Badge variant="light">{t('ai.wizard.vision')}</Badge>
                ) : null}
                {selectedEntry.supports_function_calling ? (
                  <Badge variant="light">{t('ai.wizard.tools')}</Badge>
                ) : null}
                {selectedEntry.context_window ? (
                  <Text size="xs">{selectedEntry.context_window.toLocaleString()} tokens</Text>
                ) : null}
              </Group>
            ) : null}
          </Stack>
        </Stepper.Step>
      </Stepper>

      <Accordion variant="separated" mt="md" data-testid="ai-wizard-advanced">
        <Accordion.Item value="advanced">
          <Accordion.Control>{t('ai.wizard.advanced')}</Accordion.Control>
          <Accordion.Panel>
            <Stack>
              <TextInput
                label={t('ai.columns.name')}
                value={displayName}
                onChange={(event) => setName(event.currentTarget.value)}
                data-testid="ai-wizard-name"
              />
              <Select
                label={t('ai.columns.tier')}
                value={tier}
                onChange={(value) =>
                  setTier(value === 'precision' ? 'precision' : 'bulk')
                }
                data={[
                  { value: 'bulk', label: t('ai.tier.bulk') },
                  { value: 'precision', label: t('ai.tier.precision') },
                ]}
              />
              <NumberInput
                label={t('ai.maxConcurrency')}
                value={maxConcurrency}
                min={1}
                max={64}
                onChange={(value) => setMaxConcurrency(typeof value === 'number' ? value : 4)}
              />
              <NumberInput
                label={t('ai.timeoutS')}
                value={timeoutS}
                min={1}
                max={600}
                onChange={(value) => setTimeoutS(typeof value === 'number' ? value : 30)}
              />
              <NumberInput
                label={t('ai.wizard.inputPrice')}
                value={inputPrice ?? ''}
                min={0}
                decimalScale={6}
                onChange={(value) => setInputPrice(value === '' || value === undefined ? null : String(value))}
              />
              <NumberInput
                label={t('ai.wizard.outputPrice')}
                value={outputPrice ?? ''}
                min={0}
                decimalScale={6}
                onChange={(value) => setOutputPrice(value === '' || value === undefined ? null : String(value))}
              />
              <Switch
                label={t('ai.columns.enabled')}
                checked={enabled}
                onChange={(event) => setEnabled(event.currentTarget.checked)}
              />
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>

      <Group justify="space-between" mt="md">
        <Button variant="default" disabled={active === 0} onClick={() => setActive((step) => step - 1)}>
          {t('ai.wizard.back')}
        </Button>
        {active < 2 ? (
          <Button disabled={!canAdvance} onClick={() => setActive((step) => step + 1)} data-testid="ai-wizard-next">
            {t('ai.wizard.next')}
          </Button>
        ) : (
          <Button
            loading={createProvider.isPending || updateProvider.isPending}
            disabled={!canAdvance}
            onClick={submit}
            data-testid="ai-wizard-finish"
          >
            {t('ai.wizard.finish')}
          </Button>
        )}
      </Group>

      {testResult ? (
        <Alert mt="md" data-testid="ai-wizard-result">
          {testResult}
        </Alert>
      ) : null}
    </Modal>
  );
}
```

- [x] **Step 5: Wire the wizard into ProvidersPage**

Rewrite `frontend/src/features/admin/ai/ProvidersPage.tsx` to drop `ProviderModal` and use `ProviderWizard`. Keep the table, the test-result line, and the existing actions. Replace the state and modal section with:

```tsx
import { useState } from 'react';
import {
  ActionIcon, Badge, Button, Group, Stack, Switch, Table, Title,
} from '@mantine/core';
import { IconBolt, IconPencil, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import {
  useAiProviders, useDeleteAiProvider, useTestAiProvider, useUpdateAiProvider,
} from '../../../api/hooks';
import { notifyMutationError, notifySuccess } from '../../../app/notifications';
import { EmptyState, ErrorState, LoadingState } from '../../../components/StateViews';
import type { AiProvider } from '../../../api/types';
import { ProviderWizard } from './ProviderWizard';

function presetForProvider(provider: AiProvider): string {
  if (provider.provider_type === 'openai_compatible') return 'custom';
  if (provider.model.startsWith('anthropic/')) return 'anthropic';
  if (provider.model.startsWith('gemini/')) return 'google';
  if (provider.model.startsWith('openrouter/')) return 'openrouter';
  if (provider.model.startsWith('mistral/')) return 'mistral';
  if (provider.model.startsWith('groq/')) return 'groq';
  return 'openai';
}

export function ProvidersPage() {
  const { t } = useTranslation('admin');
  const providersQuery = useAiProviders();
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

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={4}>{t('ai.providersTitle')}</Title>
        <Button
          leftSection={<IconPlus size={16} />}
          data-testid="ai-add-provider"
          onClick={() => setCreating(true)}
        >
          {t('ai.add')}
        </Button>
      </Group>
      {providers.length === 0 ? (
        <EmptyState message={t('ai.empty')} />
      ) : (
        <Table data-testid="ai-providers-table" striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('ai.columns.name')}</Table.Th>
              <Table.Th>{t('ai.columns.model')}</Table.Th>
              <Table.Th>{t('ai.columns.tier')}</Table.Th>
              <Table.Th>{t('ai.columns.enabled')}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {providers.map((provider) => (
              <Table.Tr key={provider.id} data-testid={`ai-provider-row-${provider.id}`}>
                <Table.Td>{provider.name}</Table.Td>
                <Table.Td>{provider.model}</Table.Td>
                <Table.Td>
                  <Badge variant="light" color={provider.tier === 'precision' ? 'grape' : 'blue'}>
                    {t(`ai.tier.${provider.tier}`)}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Switch
                    aria-label={t('ai.columns.enabled')}
                    checked={provider.enabled}
                    onChange={(event) =>
                      updateProvider.mutate(
                        { id: provider.id, enabled: event.currentTarget.checked },
                        { onError: (error) => notifyMutationError(error, t('ai.saveFailed')) },
                      )
                    }
                  />
                </Table.Td>
                <Table.Td>
                  <Group gap="xs" wrap="nowrap">
                    <ActionIcon
                      variant="subtle"
                      aria-label={t('ai.test')}
                      onClick={() => {
                        testProvider.mutate(provider.id, {
                          onSuccess: (result) =>
                            setTestResult(
                              result.status === 'ok'
                                ? t('ai.testOk', { latency: result.latency_ms ?? 0 })
                                : t('ai.testFailed', { code: result.error_code ?? 'unknown' }),
                            ),
                        });
                      }}
                    >
                      <IconBolt size={16} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      aria-label={t('ai.edit')}
                      onClick={() => setEditing(provider)}
                    >
                      <IconPencil size={16} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={t('ai.delete')}
                      onClick={() =>
                        deleteProvider.mutate(provider.id, {
                          onSuccess: () => notifySuccess(t('ai.deleted')),
                          onError: (error) => notifyMutationError(error, t('ai.deleteFailed')),
                        })
                      }
                    >
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {testResult ? <div data-testid="ai-test-result">{testResult}</div> : null}
      <ProviderWizard
        key={editing?.id ?? (creating ? 'create' : 'closed')}
        opened={creating || editing !== null}
        provider={editing}
        presetKey={editing ? presetForProvider(editing) : 'openai'}
        onClose={() => {
          setCreating(false);
          setEditing(null);
        }}
      />
    </Stack>
  );
}
```

- [x] **Step 6: Rewrite the ProvidersPage test**

Replace `frontend/src/features/admin/ai/ProvidersPage.test.tsx` with:

```tsx
import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import { ProvidersPage } from './ProvidersPage';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const providers = [
  {
    id: 1, name: 'primary', provider_type: 'litellm',
    base_url: '', model: 'openai/gpt-4o-mini',
    input_price_per_mtok: null, output_price_per_mtok: null,
    max_concurrency: 4, timeout_s: 30, enabled: true, tier: 'bulk',
  },
];

const presets = [
  {
    vendor_key: 'openai', label: 'OpenAI', model_prefix: 'openai',
    default_base_url: '', requires_base_url: false,
    api_key_env_hint: 'OPENAI_API_KEY', docs_url: 'https://docs', supports_catalog: true,
  },
];

const catalog = {
  entries: [
    {
      model_id: 'openai/gpt-4o', vendor: 'openai', display_name: 'gpt-4o',
      context_window: 128000, max_output_tokens: 16384,
      input_price_per_mtok: '2.500000', output_price_per_mtok: '10.000000',
      supports_vision: true, supports_function_calling: true, is_recommended: true,
    },
  ],
  sync: { last_attempt_at: null, last_success_at: null, last_error: null, source: 'bundled' },
};

beforeAll(async () => {
  await i18n.loadNamespaces('admin');
});

beforeEach(() => {
  stubFetch((url) => {
    if (url === '/admin/ai/providers') return jsonResponse(providers);
    if (url === '/admin/ai/provider-presets') return jsonResponse(presets);
    if (url.startsWith('/admin/ai/model-catalog')) return jsonResponse(catalog);
    return jsonResponse({});
  });
});

describe('ProvidersPage', () => {
  it('renders the provider table', async () => {
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByTestId('ai-providers-table')).toBeInTheDocument());
    expect(screen.getByText('primary')).toBeInTheDocument();
    expect(screen.getByTestId('ai-provider-row-1')).toHaveTextContent('Bulk');
  });

  it('shows empty state when no providers exist', async () => {
    stubFetch((url) => {
      if (url === '/admin/ai/providers') return jsonResponse([]);
      if (url === '/admin/ai/provider-presets') return jsonResponse(presets);
      return jsonResponse({});
    });
    render(<ProvidersPage />);
    await waitFor(() =>
      expect(screen.getByText('No AI providers configured')).toBeInTheDocument(),
    );
  });

  it('creates a provider through the wizard', async () => {
    const posts: unknown[] = [];
    stubFetch((url, init) => {
      if (url === '/admin/ai/providers' && init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)));
        return jsonResponse({ ...providers[0], id: 2, model: 'openai/gpt-4o' }, 201);
      }
      if (url === '/admin/ai/providers/2/test') return jsonResponse({ status: 'ok', latency_ms: 9 });
      if (url === '/admin/ai/providers') return jsonResponse(providers);
      if (url === '/admin/ai/provider-presets') return jsonResponse(presets);
      if (url.startsWith('/admin/ai/model-catalog')) return jsonResponse(catalog);
      return jsonResponse({});
    });
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByTestId('ai-providers-table')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('ai-add-provider'));
    fireEvent.click(await screen.findByTestId('ai-wizard-preset-openai'));
    fireEvent.click(screen.getByTestId('ai-wizard-next'));
    fireEvent.change(screen.getByTestId('ai-wizard-api-key'), { target: { value: 'sk-test' } });
    fireEvent.click(screen.getByTestId('ai-wizard-next'));
    await waitFor(() => expect(screen.getByTestId('ai-wizard-model-select')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('ai-wizard-finish'));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ model: 'openai/gpt-4o', provider_type: 'litellm' });
  });
});
```

- [x] **Step 7: Run tests to verify they pass**

Run: `npm run test -- src/features/admin/ai/`
Expected: PASS

- [x] **Step 8: Typecheck and build**

Run: `npm run typecheck`
Expected: exit 0

- [x] **Step 9: Commit**

```bash
git add frontend/src/features/admin/ai/ProviderWizard.tsx frontend/src/features/admin/ai/ProvidersPage.tsx frontend/src/features/admin/ai/ProviderWizard.test.tsx frontend/src/features/admin/ai/ProvidersPage.test.tsx frontend/public/locales/en/admin.json frontend/public/locales/de/admin.json
git commit -m "feat(admin): 3-step AI provider wizard (GFM-12)"
```

---

### Task 9: Legacy badge, catalog status, and edit mapping

**Files:**
- Modify: `frontend/src/features/admin/ai/ProvidersPage.tsx`
- Modify: `frontend/public/locales/en/admin.json`, `frontend/public/locales/de/admin.json`
- Test: `frontend/src/features/admin/ai/ProvidersPage.test.tsx` (append)
- Docs: `frontend/docs/architecture.md`

**Interfaces:**
- Consumes: `useRefreshModelCatalog`, `useModelCatalog` (Task 7); `ProviderWizard` (Task 8).
- Produces: catalog status line with a Refresh button; a Legacy badge on `openai_compatible` rows.

- [x] **Step 1: Write the failing test**

Append to `frontend/src/features/admin/ai/ProvidersPage.test.tsx`:

```tsx
const legacyProviders = [
  {
    id: 9, name: 'legacy', provider_type: 'openai_compatible',
    base_url: 'http://localhost:11434/v1', model: 'llama3',
    input_price_per_mtok: null, output_price_per_mtok: null,
    max_concurrency: 4, timeout_s: 30, enabled: true, tier: 'bulk',
  },
];

it('marks legacy providers and opens the wizard with the custom preset', async () => {
  stubFetch((url) => {
    if (url === '/admin/ai/providers') return jsonResponse(legacyProviders);
    if (url === '/admin/ai/provider-presets') return jsonResponse([
      ...presets,
      {
        vendor_key: 'custom', label: 'OpenAI-kompatibel (custom)', model_prefix: 'openai',
        default_base_url: '', requires_base_url: true,
        api_key_env_hint: '', docs_url: '', supports_catalog: false,
      },
    ]);
    if (url.startsWith('/admin/ai/model-catalog')) return jsonResponse(catalog);
    return jsonResponse({});
  });
  render(<ProvidersPage />);
  await waitFor(() => expect(screen.getByTestId('ai-legacy-badge-9')).toBeInTheDocument());

  fireEvent.click(screen.getByLabelText('Edit'));
  await waitFor(() => expect(screen.getByTestId('ai-wizard')).toBeInTheDocument());
  fireEvent.click(screen.getByTestId('ai-wizard-next'));
  fireEvent.click(screen.getByTestId('ai-wizard-next'));
  expect(await screen.findByTestId('ai-wizard-model-custom')).toBeInTheDocument();
});

it('renders the catalog status and triggers a refresh', async () => {
  const refreshes: string[] = [];
  stubFetch((url, init) => {
    if (url === '/admin/ai/providers') return jsonResponse(providers);
    if (url === '/admin/ai/provider-presets') return jsonResponse(presets);
    if (url === '/admin/ai/model-catalog/refresh' && init?.method === 'POST') {
      refreshes.push(url);
      return jsonResponse({ last_attempt_at: null, last_success_at: null, last_error: null, source: 'github' });
    }
    if (url.startsWith('/admin/ai/model-catalog')) {
      return jsonResponse({
        entries: [], sync: { last_attempt_at: null, last_success_at: null, last_error: 'boom', source: 'bundled' },
      });
    }
    return jsonResponse({});
  });
  render(<ProvidersPage />);
  await waitFor(() => expect(screen.getByTestId('ai-catalog-status')).toBeInTheDocument());
  expect(screen.getByTestId('ai-catalog-status')).toHaveTextContent('Catalog refresh failed');
  fireEvent.click(screen.getByTestId('ai-catalog-refresh'));
  await waitFor(() => expect(refreshes).toHaveLength(1));
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/features/admin/ai/ProvidersPage.test.tsx`
Expected: FAIL — `ai-legacy-badge-9` not found

- [x] **Step 3: Add i18n keys**

Inside `ai` in both locale files, add:

```json
"legacy": "Legacy",
"catalogStatus": "Catalog updated {{when}}",
"catalogNeverSynced": "Catalog not synced yet",
"catalogError": "Catalog refresh failed",
"catalogRefresh": "Refresh catalog"
```

German:

```json
"legacy": "Legacy",
"catalogStatus": "Katalog aktualisiert {{when}}",
"catalogNeverSynced": "Katalog noch nicht synchronisiert",
"catalogError": "Katalog-Refresh fehlgeschlagen",
"catalogRefresh": "Katalog aktualisieren"
```

- [x] **Step 4: Add the badge and status line**

In `frontend/src/features/admin/ai/ProvidersPage.tsx`:

Add imports:

```tsx
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '../../../api/client';
import { useRefreshModelCatalog } from '../../../api/hooks';
import type { AiProvider, ModelCatalog } from '../../../api/types';
```

Add state/hooks at the top of the component:

```tsx
  const refreshCatalog = useRefreshModelCatalog();
  const catalogStatusQuery = useQuery({
    queryKey: ['ai', 'model-catalog', 'status'],
    queryFn: () => apiGet<ModelCatalog>('/admin/ai/model-catalog?mode=chat'),
  });
```

Add the status line just above the `{providers.length === 0 ? ...}` block:

```tsx
      <Group data-testid="ai-catalog-status" gap="xs">
        <Text size="sm" c={catalogStatusQuery.data?.sync.last_error ? 'red' : 'dimmed'}>
          {catalogStatusQuery.data?.sync.last_error
            ? t('ai.catalogError')
            : catalogStatusQuery.data?.sync.last_success_at
              ? t('ai.catalogStatus', { when: catalogStatusQuery.data.sync.last_success_at })
              : t('ai.catalogNeverSynced')}
        </Text>
        <Button
          size="compact-xs"
          variant="subtle"
          data-testid="ai-catalog-refresh"
          loading={refreshCatalog.isPending}
          onClick={() => refreshCatalog.mutate()}
        >
          {t('ai.catalogRefresh')}
        </Button>
      </Group>
```

Add the Legacy badge in the model cell:

```tsx
                <Table.Td>
                  {provider.model}
                  {provider.provider_type === 'openai_compatible' ? (
                    <Badge
                      ml="xs"
                      variant="outline"
                      color="gray"
                      data-testid={`ai-legacy-badge-${provider.id}`}
                    >
                      {t('ai.legacy')}
                    </Badge>
                  ) : null}
                </Table.Td>
```

Replace the existing `<Table.Td>{provider.model}</Table.Td>` with the block above. Add `Text` to the `@mantine/core` import.

- [x] **Step 5: Run tests to verify they pass**

Run: `npm run test -- src/features/admin/ai/ProvidersPage.test.tsx`
Expected: PASS

- [x] **Step 6: Update the frontend docs**

In `frontend/docs/architecture.md`, add a short subsection under the admin area:

```markdown
### AI provider wizard

`features/admin/ai/ProviderWizard.tsx` is a 3-step Mantine `Stepper` (provider preset → API key → model) backed by `useProviderPresets()` and `useModelCatalog(vendor)`; advanced fields sit in a collapsed accordion. `ProvidersPage.tsx` keeps the provider table (Legacy badge for `openai_compatible` rows) and shows the catalog sync status with a manual refresh button. Provider presets and the model catalog are server state and live only in TanStack Query.
```

- [x] **Step 7: Full frontend gate**

Run: `npm run test && npm run build`
Expected: tests pass; typecheck + production build succeed

- [x] **Step 8: Commit**

```bash
git add frontend/src/features/admin/ai/ProvidersPage.tsx frontend/src/features/admin/ai/ProvidersPage.test.tsx frontend/public/locales/en/admin.json frontend/public/locales/de/admin.json frontend/docs/architecture.md
git commit -m "feat(admin): legacy badge and catalog status (GFM-12)"
```

---

### Task 10: Full verification

**Files:** none (verification only)

- [x] **Step 1: Backend gate**

Run from `backend/`:

```bash
uv run ruff check . ../plugins
uv run mypy .
uv run alembic check
uv run pytest --report-log=.report.jsonl
```

Expected: ruff/mypy exit 0; alembic reports no new operations; pytest has no failures. Check failures with:

```bash
jq -c 'select(.["$report_type"]=="TestReport" and .when=="call" and .outcome=="failed")' .report.jsonl | wc -l
```

Expected: `0`

- [x] **Step 2: Frontend gate**

Run from `frontend/`:

```bash
npm run test
npm run build
```

Expected: all tests pass; build succeeds

- [x] **Step 3: Regression sanity**

Run: `uv run pytest tests/test_ai_router.py -v`
Expected: PASS (legacy `openai_compatible` deployment, no double prefix, disabled-row skip unchanged)

- [x] **Step 4: Docs check**

Confirm each of these was updated in the same commit chain: `backend/docs/data-model.md`, `backend/docs/api.md`, `backend/docs/architecture.md`, `docs/decisions.md`, `frontend/docs/architecture.md`.

- [x] **Step 5: Final commit (only if verification required doc fixes)**

```bash
git add -A
git commit -m "test: GFM-12 verification fixes"
```
