# AI Core Cleanup — Phase D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the retired AI transport/cache modules and drop the now-unused `ai_result_cache` table, `ai_provider_configs.is_default` column, and `global_settings.ai_cache_retention_days` column.

**Architecture:** Pure removal. Phase A retired these in favor of LiteLLM Router/Instructor/native cache but kept them referenced until now; Phase C removed the last live reader (the cache path). Deletion order is chosen so every commit stays green: modules first, then persistence + migration (with the tests that enumerate tables/columns), then docs.

**Tech Stack:** Python 3.10+, SQLAlchemy 2.0 async, Alembic, pytest.

**Status:** Phase D of `docs/superpowers/specs/2026-09-16-litellm-instructor-ai-core-design.md` (A `bef098d`, B `5d4d28f`, C `8a88854`). Current Alembic head: `2e9e790582c3`.

## Global Constraints

- Run backend commands from `backend/`; export `DATABASE_URL` from the repo `.env` (Postgres on port **5434**):
  ```bash
  export DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2- | sed 's#^postgresql://#postgresql+asyncpg://#')"
  ```
  `uv run pytest` needs `TEST_DATABASE_URL` and `DATABASE_URL` unset: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest`.
- Gates each task: `uv run ruff check .` must stay at **490** (zero new), `uv run mypy .` exit 0, `uv run pytest`.
- Migrations are Alembic-only; hand-write them (do NOT autogenerate — HEAD already has unrelated `feed_sources`/`staging_products` index drift that autogenerate would sweep in).
- Do not remove `AiResponse` (chat DTO) or `UsageLogWriter`/`UsageRecord`/`aggregate_usage`/`summarize_usage` (live).
- Docs change in the same commits as behavior.

---

## File Structure

| File | Action |
|---|---|
| `app/ai/openai_compat.py`, `app/ai/resilience.py`, `tests/test_ai_openai_compat.py`, `tests/test_ai_resilience.py` | delete |
| `app/ai/provider.py` | trim to `AiResponse` only |
| `app/ai/__init__.py` | trim exports |
| `app/ai/usage.py` | delete dead `estimate_cost` |
| `tests/test_ai_cache_usage.py` | remove DB-cache-store + `estimate_cost` tests |
| `app/ai/cache.py` | delete |
| `app/models/ai.py`, `app/models/__init__.py` | remove `AiResultCache`; remove `is_default` |
| `app/ai/purge.py`, `app/main.py` | usage-only purge |
| `app/models/global_setting.py`, `app/schemas/admin.py`, `app/routes/admin.py`, `app/routes/ai_admin.py` | remove `ai_cache_retention_days` |
| `alembic/versions/20260916_0002_m16_ai_cleanup.py` | new migration |
| `tests/test_migrations.py`, `tests/test_m1_acceptance.py`, `tests/test_m2_acceptance.py`, `tests/test_models.py`, `tests/test_ai_models.py`, `tests/test_ai_purge.py`, `tests/test_admin_settings_api.py`, `tests/test_ai_cache_usage.py` | update |
| `backend/docs/{architecture,data-model,api}.md`, `docs/decisions.md`, `docs/decisions/0010-*.md`, `TODO.md`, spec/plan status | docs |

---

### Task 1: Delete the retired transport and dead helper

**Files:**
- Delete: `app/ai/openai_compat.py`, `app/ai/resilience.py`, `tests/test_ai_openai_compat.py`, `tests/test_ai_resilience.py`
- Modify: `app/ai/provider.py`, `app/ai/__init__.py`, `app/ai/usage.py`, `tests/test_ai_cache_usage.py`

**Interfaces:**
- Produces: `app/ai/provider.py` exports only `AiResponse`.
- Consumes: nothing new.

- [ ] **Step 1: Confirm nothing live imports the doomed symbols**

Run:
```bash
rg -n "openai_compat|resilience|AIProvider|CircuitBreaker|RetryPolicy|CallOutcome|AiRequest" app plugins
```
Expected: only `app/ai/provider.py`, `app/ai/resilience.py`, `app/ai/__init__.py` (all edited/removed here). If something else appears, stop and reassess.

- [ ] **Step 2: Delete the modules and their tests**

```bash
git rm backend/app/ai/openai_compat.py backend/app/ai/resilience.py \
       backend/tests/test_ai_openai_compat.py backend/tests/test_ai_resilience.py
```

- [ ] **Step 3: Trim `app/ai/provider.py` to `AiResponse` only**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AiResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    latency_ms: int
    tool_calls: list[dict[str, Any]] | None = None
    finish_reason: str = "stop"
```

- [ ] **Step 4: Trim `app/ai/__init__.py` exports**

```python
from .provider import AiResponse
from .service import AiChatUnavailable, AiResult, AiService
from .tasks import CANONICAL_VARIABLES, TASK_SPECS, TaskSpec
from .templates import TaskSpecError

__all__ = [
    "CANONICAL_VARIABLES",
    "TASK_SPECS",
    "AiChatUnavailable",
    "AiResponse",
    "AiResult",
    "AiService",
    "TaskSpec",
    "TaskSpecError",
]
```

- [ ] **Step 5: Delete dead `estimate_cost` from `app/ai/usage.py`**

Remove the `estimate_cost` function (lines ~58-69). Leave `UsageLogWriter`, `UsageRecord`, `aggregate_usage`, and `summarize_usage` untouched.

- [ ] **Step 6: Update `tests/test_ai_cache_usage.py`**

- Change the import line to drop `estimate_cost`:
  ```python
  from app.ai.usage import UsageLogWriter, UsageRecord, aggregate_usage
  ```
- Delete `test_estimate_cost_with_prices` and `test_estimate_cost_without_prices_is_none`.
- Keep every other test (`test_usage_writer_*`, `test_aggregate_usage_group_by_client`, `test_summarize_usage_totals_and_savings`).

- [ ] **Step 7: Run gates**

```bash
uv run ruff check .
uv run mypy .
env -u DATABASE_URL TEST_DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2- | sed 's#^postgresql://#postgresql+asyncpg://#')" \
  uv run pytest tests/test_ai_cache_usage.py tests/test_ai_service.py tests/test_chat_api.py -q
```
Expected: ruff 490; mypy exit 0; tests PASS.

- [ ] **Step 8: Commit**

```bash
git add -A backend/app/ai backend/tests
git commit -m "refactor(ai): delete retired httpx provider, resilience, and dead cost helper"
```

---

### Task 2: Drop dead persistence (table + two columns)

**Files:**
- Delete: `app/ai/cache.py`
- Modify: `app/models/ai.py`, `app/models/__init__.py`, `app/ai/purge.py`, `app/main.py`, `app/models/global_setting.py`, `app/schemas/admin.py`, `app/routes/admin.py`, `app/routes/ai_admin.py`
- Create: `alembic/versions/20260916_0002_m16_ai_cleanup.py`
- Modify tests: `tests/test_ai_cache_usage.py`, `tests/test_ai_models.py`, `tests/test_ai_purge.py`, `tests/test_admin_settings_api.py`, `tests/test_migrations.py`, `tests/test_m1_acceptance.py`, `tests/test_m2_acceptance.py`, `tests/test_models.py`

**Interfaces:**
- Produces: `AiPurgeCounts(usage_rows: int)`; `purge_expired_ai` usage-only; models without `AiResultCache`/`is_default`/`ai_cache_retention_days`.

- [ ] **Step 1: Delete the DB cache store and its tests' usage**

```bash
git rm backend/app/ai/cache.py
```
In `tests/test_ai_cache_usage.py`:
- Remove the `from app.ai.cache import AiResultCacheStore` import.
- Delete `config_id` fixture, `test_cache_store_and_lookup_round_trip`, `test_cache_lookup_misses_on_different_template_version`, `test_cache_store_duplicate_key_does_not_raise`.
- Remove the `AiProviderConfig` import if now unused.

- [ ] **Step 2: Remove the model and its exports**

`app/models/ai.py` — delete the entire `AiResultCache` class; in `AiProviderConfig` delete:
```python
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

`app/models/__init__.py` — drop `AiResultCache` from the import and `__all__`:
```python
from .ai import AiProviderConfig, AiUsageLog, PromptTemplate
```
(and the matching `__all__` entry).

- [ ] **Step 3: Rewrite `app/ai/purge.py` to usage-only**

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.ai import AiUsageLog

AI_PURGE_JOB_ID = "system-ai-purge"

DEFAULT_AI_USAGE_RETENTION_DAYS = 90


@dataclass(frozen=True)
class AiPurgeCounts:
    usage_rows: int


async def _retention(session: AsyncSession) -> int:
    from ..models.global_setting import GlobalSetting

    row = await session.get(GlobalSetting, 1)
    if row is None:
        return DEFAULT_AI_USAGE_RETENTION_DAYS
    return row.ai_usage_retention_days


async def purge_expired_ai(
    session_factory: Callable[[], AsyncSession],
    now: datetime,
) -> AiPurgeCounts:
    async with session_factory() as session, session.begin():
        usage_days = await _retention(session)
        usage = await session.execute(
            delete(AiUsageLog).where(
                AiUsageLog.created_at < now - timedelta(days=usage_days)
            )
        )
        return AiPurgeCounts(usage_rows=usage.rowcount)
```

- [ ] **Step 4: Fix the purge log in `app/main.py`**

Replace the two-argument log (around line 170) with:
```python
                        "ai purge: %s usage rows",
                        counts.usage_rows,
```

- [ ] **Step 5: Drop `ai_cache_retention_days` from settings**

- `app/models/global_setting.py`: delete the `ai_cache_retention_days` column.
- `app/schemas/admin.py`: delete `ai_cache_retention_days` from `GlobalSettingsOut`.
- `app/routes/admin.py`: delete `ai_cache_retention_days=90` from both seed `GlobalSetting(...)` blocks and the assignment line in `put_settings_row`.
- `app/routes/ai_admin.py`: delete `ai_cache_retention_days=90` from `_seed_settings`.

- [ ] **Step 6: Update the tests that enumerate tables/columns**

- `tests/test_migrations.py`, `tests/test_m1_acceptance.py`, `tests/test_m2_acceptance.py`, `tests/test_models.py`: remove `"ai_result_cache"` from each table-name list.
- `tests/test_ai_models.py`: delete `test_ai_result_cache_unique_key`; remove `is_default=True` from `AiProviderConfig(...)` calls and the `assert row.is_default is True` line (keep `assert row.tier == "bulk"`).
- `tests/test_ai_purge.py`: rewrite to usage-only — drop the `AiResultCache` import/seed/assertions and the `AiProviderConfig` config seed (the FK is gone), remove `ai_cache_retention_days=days` from the `GlobalSetting(...)` seed, and assert `AiPurgeCounts(usage_rows=...)`:
  ```python
  counts = await purge_expired_ai(session_factory, NOW)
  assert counts == AiPurgeCounts(usage_rows=1)
  ```
  and for the 200-day case `AiPurgeCounts(usage_rows=0)`.
- `tests/test_admin_settings_api.py`: remove `"ai_cache_retention_days": ...` from the two PUT payloads and the `follow_up.json()["ai_cache_retention_days"] == 20` assertion.

- [ ] **Step 7: Write the migration**

Create `alembic/versions/20260916_0002_m16_ai_cleanup.py`:
```python
"""m16 ai cleanup

Revision ID: b1a2c3d4e5f6
Revises: 2e9e790582c3
Create Date: 2026-09-16
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b1a2c3d4e5f6"
down_revision: str | Sequence[str] | None = "2e9e790582c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("ai_result_cache")
    op.drop_column("ai_provider_configs", "is_default")
    op.drop_column("global_settings", "ai_cache_retention_days")


def downgrade() -> None:
    op.add_column(
        "global_settings",
        sa.Column("ai_cache_retention_days", sa.Integer(), server_default="90", nullable=False),
    )
    op.add_column(
        "ai_provider_configs",
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_table(
        "ai_result_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column(
            "provider_config_id", sa.Integer(),
            sa.ForeignKey("ai_provider_configs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("template_version", sa.String(length=100), server_default="builtin", nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "task_type", "provider_config_id", "model", "template_version", "input_hash",
            name="uq_ai_result_cache_key",
        ),
    )
    op.create_index("ix_ai_result_cache_input_hash", "ai_result_cache", ["input_hash"])
```

- [ ] **Step 8: Apply and verify**

```bash
uv run alembic upgrade head
uv run alembic current
uv run python -c "import asyncio, asyncpg
async def main():
    c = await asyncpg.connect('postgresql://postgres:postgres@localhost:5434/gmc_feed')
    tables = {r['tablename'] for r in await c.fetch(\"select tablename from pg_tables where schemaname='public'\")}
    cols = {r['column_name'] for r in await c.fetch(\"select column_name from information_schema.columns where table_name='ai_provider_configs'\")}
    gcols = {r['column_name'] for r in await c.fetch(\"select column_name from information_schema.columns where table_name='global_settings'\")}
    print('ai_result_cache gone:', 'ai_result_cache' not in tables)
    print('is_default gone:', 'is_default' not in cols)
    print('ai_cache_retention_days gone:', 'ai_cache_retention_days' not in gcols)
    await c.close()
asyncio.run(main())"
```
Expected: current = `b1a2c3d4e5f6`; all three prints `True`.

- [ ] **Step 9: Run the suite and gates**

```bash
uv run ruff check .
uv run mypy .
env -u DATABASE_URL TEST_DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2- | sed 's#^postgresql://#postgresql+asyncpg://#')" uv run pytest -q
```
Expected: ruff 490; mypy exit 0; all tests pass.

- [ ] **Step 10: Commit**

```bash
git add -A backend
git commit -m "refactor(ai): drop ai_result_cache, is_default, and ai_cache_retention_days (m16)"
```

---

### Task 3: Docs and final gates

**Files:**
- Modify: `backend/docs/architecture.md`, `backend/docs/data-model.md`, `backend/docs/api.md`, `docs/decisions.md`, `docs/decisions/0010-litellm-instructor-ai-transport.md`, `TODO.md`, spec/plan status

- [ ] **Step 1: Remove the "legacy, retained until cleanup" passages**

- `backend/docs/architecture.md`: delete the *"Legacy, no longer used by `AiService`, retained until the cleanup phase…"* paragraph.
- `backend/docs/data-model.md`: delete the `AiResultCache` table section and the *"Legacy, unused…"* note; remove the `is_default` row (AiProviderConfig table) and the `ai_cache_retention_days` row (GlobalSetting table); update the AiProviderConfig line that says `is_default` is "kept until the cleanup phase".
- `backend/docs/api.md`: no endpoint changes expected — confirm no mention of `is_default` remains.

- [ ] **Step 2: Amend ADR-0010 and the decision log**

- `docs/decisions/0010-litellm-instructor-ai-transport.md`: update the Consequences bullet that says the physical drops / module deletions "move to the cleanup phase" to state they are done (m16).
- `docs/decisions.md`: append a dated entry for phase D (deletions, drops, and the removal of `estimate_cost`).

- [ ] **Step 3: TODO cycle-log entry + spec/plan status**

- `TODO.md`: prepend a cycle-log entry for phase D (deletions, m16 drops, test counts).
- Spec `2026-09-16-litellm-instructor-ai-core-design.md`: append phase D to the Status line.
- `docs/superpowers/plans/2026-09-16-ai-core-replacement-litellm-instructor.md`: note phases B–D are done (its status covers phase A only).

- [ ] **Step 4: Full gates**

```bash
uv run ruff check .          # "Found 490 errors"
uv run mypy .                # "Success: no issues found"
env -u DATABASE_URL TEST_DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2- | sed 's#^postgresql://#postgresql+asyncpg://#')" uv run pytest -q
cd ../frontend && npm run test && npm run typecheck
```
Expected: all green; ruff 490 (zero new).

- [ ] **Step 5: Commit**

```bash
git add backend/docs docs TODO.md
git commit -m "docs(ai): phase D cleanup — remove legacy AI references"
```

---

## Self-Review

**Spec coverage (phase D):** delete `openai_compat.py`/`cache.py`/`resilience.py` → Tasks 1–2; retire `AIProvider`/`default_provider_factory` and `AiRequest` (keep `AiResponse`) → Task 1; drop `ai_result_cache`/`is_default`/`ai_cache_retention_days` → Task 2 + m16; docs/ADR → Task 3.

**Placeholder scan:** complete code/commands in every step; no TBD.

**Type consistency:** `AiPurgeCounts(usage_rows)` matches its only caller (`app/main.py`) and the rewritten `test_ai_purge.py`; `AiResponse` field set is unchanged from the pre-cleanup definition (chat path unaffected); migration revision `b1a2c3d4e5f6` chains from the live head `2e9e790582c3`.

**Ordering note:** deleting `app/ai/cache.py` (Task 2) and `AiResultCache` in the same commit as the table-list tests + migration keeps the table-enumerating tests and the DB in sync; Task 1 is module/test deletion only and touches no schema.
