# AI Core Replacement — Phase A (LiteLLM + Instructor) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bespoke AI transport, loose JSON validators, and DB result cache with a LiteLLM Router + Instructor structured-output core and LiteLLM's native cache, behind the unchanged `AiService` public API.

**Architecture:** `AiService` remains the seam. A `router.py` builds a `litellm.Router` from `ai_provider_configs` rows grouped into `bulk`/`precision` tiers and wires `instructor.from_litellm(router.acompletion, async_client=True)`. `schemas.py` supplies one Pydantic `response_model` per task type. `cache_config.py` wraps `litellm.Cache` with per-task namespaces and TTLs and performs validated-only caching. Teardown of the old modules happens in phase D.

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.0 async, PostgreSQL, Alembic, `litellm`, `instructor`, pytest (`asyncio_mode` not global — mark `@pytest.mark.asyncio` explicitly).

## Global Constraints

- Run everything from `backend/`.
- DB URL: export `DATABASE_URL` from the repo `.env` (local Postgres is on host port **5434**):
  ```bash
  export DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2- | sed 's#^postgresql://#postgresql+asyncpg://#')"
  ```
  `uv run pytest` additionally needs `TEST_DATABASE_URL` exported (same server, `postgresql+asyncpg://` dialect, no query params).
- Gates, in order, must pass each task: `uv run ruff check .` (exact count vs `backend/ruff-baseline.txt`), `uv run mypy .` (exit 0, hard), `uv run pytest`.
- Alembic only: `uv run alembic revision --autogenerate -m "..."`; never `create_all`; `alembic check` clean before merge.
- Dependencies only via `uv add`; never hand-edit `uv.lock`.
- No provider SDK imports (openai/anthropic/google) anywhere — LiteLLM only.
- `AiService` public API and `AiResult.status` values (`ok` / `cache_hit` / `fallback`) are preserved.
- Callers that must not change: `app/qc/ai_rules.py`, `plugins/core/enrichment/plugin.py`, `app/routes/chat.py`.
- Cache TTL defaults: taxonomy `2592000`, content `604800`; namespace default `gmc-ai`; disk path from `AI_CACHE_DIR`.
- `provider_type` accepts `litellm` and legacy `openai_compatible`; legacy rows map to `openai/<model>` + `api_base`.
- Fail-open: no cache or AI failure may abort a pipeline run.
- Do not modify `app/plugins/{contract,manifest,discovery,loader,runtime}.py`.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/ai/constraints.py` | new — registry-sourced field constraints (max length, enum values) |
| `app/ai/taxonomy.py` | new — cached taxonomy-ID set from the category plugin CSV |
| `app/ai/schemas.py` | new — Pydantic `response_model` per task type |
| `app/ai/router.py` | new — `Router` + Instructor builder; settings loader |
| `app/ai/cache_config.py` | new — native cache build, namespaces, TTLs, status/stats/clear |
| `app/ai/tasks.py` | rewrite — `TaskSpec.response_model`, `description_optimization`, prompts |
| `app/ai/service.py` | rewrite internals — Router + Instructor + native cache |
| `app/ai/purge.py` | edit — stop purging the dropped `ai_result_cache` |
| `app/ai/provider.py` | keep DTOs; Protocol/factory removed in phase D |
| `app/models/ai.py` | edit — provider `tier`, drop `is_default`, usage telemetry columns |
| `app/models/global_setting.py` | edit — AI settings columns; drop `ai_cache_retention_days` |
| `app/schemas/ai_admin.py` | edit — provider `tier`, drop `is_default` |
| `app/routes/admin.py` | edit — drop `ai_cache_retention_days` from settings schema/route |
| `alembic/versions/<rev>_m15_ai_litellm_core.py` | new — migration |
| `frontend/src/features/admin/ai/ProvidersPage.tsx` | edit — tier, remove default |
| `frontend/src/api/types.ts`, `hooks.ts`, i18n | edit — provider type/hooks |
| `backend/docs/{architecture,data-model,api}.md`, `docs/decisions/0010-*.md` | edit/new — docs |

---

### Task 1: Dependencies, mypy override, and API spike

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/tests/test_ai_core_spike.py` (deleted after verification)

**Interfaces:**
- Consumes: nothing.
- Produces: pinned `litellm`/`instructor` versions and the confirmed call shapes used by Tasks 7–9.

- [ ] **Step 1: Add the dependencies**

Run from `backend/`:
```bash
uv add litellm instructor
```

- [ ] **Step 2: Record the resolved versions**

Run: `uv run python -c "import litellm, instructor; print(litellm.__version__, instructor.__version__)"`
Expected: prints two versions. Pin both exactly in `pyproject.toml` `dependencies` (replace the caret/`>=` spec `uv` wrote with `==<version>`).

- [ ] **Step 3: Add mypy overrides**

In `backend/pyproject.toml`, after the existing `asyncpg` override, add:
```toml
[[tool.mypy.overrides]]
module = ["litellm.*", "litellm", "instructor.*", "instructor"]
ignore_missing_imports = true
```

- [ ] **Step 4: Write the spike test that pins the call shapes**

```python
# backend/tests/test_ai_core_spike.py
from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import instructor
import litellm
from litellm import Router


def test_router_accepts_phase_a_kwargs() -> None:
    params = inspect.signature(Router.__init__).parameters
    for name in ("model_list", "fallbacks", "num_retries", "allowed_fails", "cooldown_time", "timeout"):
        assert name in params, f"Router missing {name}"


def test_router_exposes_async_completion() -> None:
    assert hasattr(Router, "acompletion")


def test_instructor_from_litellm_accepts_async_client_flag() -> None:
    params = inspect.signature(instructor.from_litellm).parameters
    assert "async_client" in params
    assert "mode" in params


def test_cache_exposes_async_get_and_add() -> None:
    from litellm.caching.caching import Cache

    assert hasattr(Cache, "async_get_cache")
    assert hasattr(Cache, "async_add_cache")
```

- [ ] **Step 5: Run the spike**

Run: `uv run pytest tests/test_ai_core_spike.py -v`
Expected: PASS. If any assertion fails, the library version differs from the spec's assumption — record the actual signature in `docs/decisions/0010-litellm-instructor-ai-transport.md` and adjust Tasks 7–9 accordingly before proceeding.

- [ ] **Step 6: Verify gates**

Run: `uv run ruff check . && uv run mypy .`
Expected: ruff count unchanged from `ruff-baseline.txt`; mypy exit 0.

- [ ] **Step 7: Delete the spike and commit**

```bash
rm backend/tests/test_ai_core_spike.py
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore(ai): add litellm + instructor deps and mypy overrides"
```

---

### Task 2: Registry-sourced constraints helper

**Files:**
- Create: `app/ai/constraints.py`
- Test: `tests/test_ai_constraints.py`

**Interfaces:**
- Produces: `max_length(attr: str) -> int | None`, `enum_values(attr: str) -> tuple[str, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ai_constraints.py
from __future__ import annotations

from app.ai import constraints


def test_title_max_length_matches_registry() -> None:
    assert constraints.max_length("title") == 150


def test_description_max_length_matches_registry() -> None:
    assert constraints.max_length("description") == 5000


def test_unknown_attribute_has_no_constraints() -> None:
    assert constraints.max_length("does_not_exist") is None
    assert constraints.enum_values("does_not_exist") == ()


def test_gender_and_age_group_enums_come_from_registry() -> None:
    assert constraints.enum_values("gender") == ("male", "female", "unisex")
    assert constraints.enum_values("age_group") == (
        "newborn", "infant", "toddler", "kids", "adult",
    )


def test_custom_label_max_length() -> None:
    assert constraints.max_length("custom_label_0") == 100
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_ai_constraints.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ai.constraints'`.

- [ ] **Step 3: Implement**

```python
# backend/app/ai/constraints.py
from __future__ import annotations

from functools import lru_cache
from typing import Any

from registry.loader import load_registry


@lru_cache(maxsize=1)
def _attributes() -> dict[str, Any]:
    return load_registry().attributes


def max_length(attr: str) -> int | None:
    info = _attributes().get(attr)
    constraints = getattr(info, "constraints", None)
    return getattr(constraints, "max_length", None)


def enum_values(attr: str) -> tuple[str, ...]:
    info = _attributes().get(attr)
    values = getattr(info, "enum_values", None)
    return tuple(values) if values else ()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_ai_constraints.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/constraints.py backend/tests/test_ai_constraints.py
git commit -m "feat(ai): registry-sourced field constraints helper"
```

---

### Task 3: Taxonomy ID loader

**Files:**
- Create: `app/ai/taxonomy.py`
- Test: `tests/test_ai_taxonomy.py`

**Interfaces:**
- Produces: `known_taxonomy_ids() -> frozenset[int]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ai_taxonomy.py
from __future__ import annotations

from app.ai.taxonomy import TAXONOMY_CSV, known_taxonomy_ids


def test_taxonomy_csv_exists() -> None:
    assert TAXONOMY_CSV.exists(), f"missing {TAXONOMY_CSV}"


def test_known_ids_non_empty_and_integer() -> None:
    ids = known_taxonomy_ids()
    assert len(ids) > 1000
    assert all(isinstance(i, int) for i in ids)


def test_known_id_from_google_taxonomy() -> None:
    assert 2271 in known_taxonomy_ids()


def test_unknown_id_is_absent() -> None:
    assert 999999999 not in known_taxonomy_ids()


def test_result_is_cached() -> None:
    assert known_taxonomy_ids() is known_taxonomy_ids()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_ai_taxonomy.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/app/ai/taxonomy.py
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

TAXONOMY_CSV = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "core"
    / "category"
    / "taxonomy-with-ids.en-US.csv"
)


@lru_cache(maxsize=1)
def known_taxonomy_ids() -> frozenset[int]:
    if not TAXONOMY_CSV.exists():
        return frozenset()
    ids: set[int] = set()
    with TAXONOMY_CSV.open(encoding="utf-8") as handle:
        for line in handle:
            head = line.split(",", 1)[0].strip()
            if head.isdigit():
                ids.add(int(head))
    return frozenset(ids)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_ai_taxonomy.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/taxonomy.py backend/tests/test_ai_taxonomy.py
git commit -m "feat(ai): taxonomy id loader for category validation"
```

---

### Task 4: Pydantic response schemas

**Files:**
- Create: `app/ai/schemas.py`
- Test: `tests/test_ai_schemas.py`

**Interfaces:**
- Consumes: `constraints.max_length`, `constraints.enum_values`, `taxonomy.known_taxonomy_ids`.
- Produces: `OptimizedTitle`, `OptimizedDescription`, `Violation`, `PolicyCheckResult`, `CategoryAssignment`, `EnrichedAttributes`, `ImageQualityResult`, and `RESPONSE_MODELS: dict[str, type[BaseModel]]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ai_schemas.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai import schemas


def test_optimized_title_accepts_valid() -> None:
    assert schemas.OptimizedTitle(title="Acme Wool Socks").title == "Acme Wool Socks"


def test_optimized_title_rejects_over_150_chars() -> None:
    with pytest.raises(ValidationError):
        schemas.OptimizedTitle(title="x" * 151)


def test_optimized_title_rejects_promotional_text() -> None:
    with pytest.raises(ValidationError):
        schemas.OptimizedTitle(title="Acme Socks FREE SHIPPING best price")


def test_optimized_title_rejects_all_caps() -> None:
    with pytest.raises(ValidationError):
        schemas.OptimizedTitle(title="ACME WOOL SOCKS")


def test_optimized_description_max_5000() -> None:
    assert len(schemas.OptimizedDescription(description="d" * 5000).description) == 5000
    with pytest.raises(ValidationError):
        schemas.OptimizedDescription(description="d" * 5001)


def test_category_assignment_accepts_known_id() -> None:
    assert schemas.CategoryAssignment(google_product_category=2271).google_product_category == 2271


def test_category_assignment_rejects_unknown_id() -> None:
    with pytest.raises(ValidationError):
        schemas.CategoryAssignment(google_product_category=999999999)


def test_enriched_attributes_enums_and_optional_fields() -> None:
    model = schemas.EnrichedAttributes(color="red", gender="unisex", age_group="adult")
    assert model.color == "red"
    assert model.size is None
    with pytest.raises(ValidationError):
        schemas.EnrichedAttributes(gender="robot")


def test_enriched_attributes_custom_label_max_length() -> None:
    schemas.EnrichedAttributes(custom_label_0="x" * 100)
    with pytest.raises(ValidationError):
        schemas.EnrichedAttributes(custom_label_0="x" * 101)


def test_policy_check_result_shape() -> None:
    result = schemas.PolicyCheckResult(
        violations=[schemas.Violation(rule="misleading", reason="unverified claim")],
        confidence=0.8,
    )
    assert result.violations[0].rule == "misleading"


def test_policy_check_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        schemas.PolicyCheckResult(violations=[], confidence=1.5)


def test_image_quality_requires_core_fields() -> None:
    result = schemas.ImageQualityResult(
        watermark=False, text_overlay=True, background="white", confidence=0.9,
    )
    assert result.text_overlay is True


def test_response_models_registry_covers_all_tasks() -> None:
    assert set(schemas.RESPONSE_MODELS) == {
        "title_optimization",
        "description_optimization",
        "category_classification",
        "policy_check",
        "attribute_enrichment",
        "image_quality",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_ai_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/app/ai/schemas.py
from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from .constraints import enum_values, max_length
from .taxonomy import known_taxonomy_ids

_PROMO_WORDS = (
    "free shipping", "best price", "sale", "discount", "cheap", "buy now",
    "lowest price", "hot deal", "limited offer",
)
_LETTER_RE = re.compile(r"[A-Za-z]")


class OptimizedTitle(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=max_length("title") or 150)]

    @field_validator("title")
    @classmethod
    def _no_promotional_text(cls, value: str) -> str:
        lowered = value.lower()
        for word in _PROMO_WORDS:
            if word in lowered:
                raise ValueError(f"title contains promotional text: {word!r}")
        return value

    @field_validator("title")
    @classmethod
    def _no_all_caps(cls, value: str) -> str:
        letters = _LETTER_RE.findall(value)
        if len(letters) >= 4 and all(ch.isupper() for ch in letters):
            raise ValueError("title must not be all caps")
        return value


class OptimizedDescription(BaseModel):
    description: Annotated[
        str, Field(min_length=1, max_length=max_length("description") or 5000)
    ]


class Violation(BaseModel):
    rule: str
    reason: str


class PolicyCheckResult(BaseModel):
    violations: list[Violation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class CategoryAssignment(BaseModel):
    google_product_category: int

    @field_validator("google_product_category")
    @classmethod
    def _known_taxonomy_id(cls, value: int) -> int:
        known = known_taxonomy_ids()
        if known and value not in known:
            raise ValueError(f"unknown taxonomy id {value}")
        return value


_Gender = Literal["male", "female", "unisex"]
_AgeGroup = Literal["newborn", "infant", "toddler", "kids", "adult"]


class EnrichedAttributes(BaseModel):
    color: str | None = None
    size: str | None = None
    material: str | None = None
    gtin: str | None = None
    gender: _Gender | None = None
    age_group: _AgeGroup | None = None
    custom_label_0: Annotated[str | None, Field(max_length=100)] = None
    custom_label_1: Annotated[str | None, Field(max_length=100)] = None
    custom_label_2: Annotated[str | None, Field(max_length=100)] = None
    custom_label_3: Annotated[str | None, Field(max_length=100)] = None
    custom_label_4: Annotated[str | None, Field(max_length=100)] = None


class ImageQualityResult(BaseModel):
    watermark: bool
    text_overlay: bool
    background: str
    confidence: float = Field(ge=0.0, le=1.0)


RESPONSE_MODELS: dict[str, type[BaseModel]] = {
    "title_optimization": OptimizedTitle,
    "description_optimization": OptimizedDescription,
    "category_classification": CategoryAssignment,
    "policy_check": PolicyCheckResult,
    "attribute_enrichment": EnrichedAttributes,
    "image_quality": ImageQualityResult,
}

# Keep the registry in sync with literals used above.
assert enum_values("gender") == ("male", "female", "unisex"), "gender enum drift"
assert enum_values("age_group") == ("newborn", "infant", "toddler", "kids", "adult"), "age_group enum drift"
```

Note: `Literal` is used instead of `enum_values(...)` because Pydantic needs a static type for IDE/schema generation; the two `assert`s guard against registry drift. `max_length(...) or 150` keeps a sensible fallback if the registry is unavailable.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_ai_schemas.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/schemas.py backend/tests/test_ai_schemas.py
git commit -m "feat(ai): instructor response schemas for enrichment tasks"
```

---

### Task 5: Task registry rewrite

**Files:**
- Modify: `app/ai/tasks.py`
- Test: `tests/test_ai_tasks.py` (rewrite)

**Interfaces:**
- Consumes: `schemas.RESPONSE_MODELS`.
- Produces: `CANONICAL_VARIABLES` (with `description_optimization`), `TaskSpec(system, user, response_model)`, `TASK_SPECS`, `input_hash(task_type, variables) -> str`. `validate_task` is removed.

- [ ] **Step 1: Rewrite the test**

```python
# backend/tests/test_ai_tasks.py
from __future__ import annotations

from app.ai import schemas
from app.ai.tasks import CANONICAL_VARIABLES, TASK_SPECS, input_hash


def test_canonical_variables_cover_all_task_specs() -> None:
    assert set(CANONICAL_VARIABLES) == set(TASK_SPECS)


def test_description_optimization_registered() -> None:
    assert CANONICAL_VARIABLES["description_optimization"] == ["title", "description"]
    assert TASK_SPECS["description_optimization"].response_model is schemas.OptimizedDescription


def test_each_task_spec_has_a_response_model() -> None:
    for task_type, spec in TASK_SPECS.items():
        assert spec.response_model is schemas.RESPONSE_MODELS[task_type], task_type


def test_category_prompt_requests_numeric_id() -> None:
    spec = TASK_SPECS["category_classification"]
    assert "taxonomy id" in spec.system.lower()
    assert "path" not in spec.system.lower()


def test_attribute_prompt_requests_new_fields() -> None:
    prompt = TASK_SPECS["attribute_enrichment"].system.lower()
    for field in ("gender", "age_group", "custom_label"):
        assert field in prompt


def test_input_hash_is_stable_and_order_insensitive() -> None:
    assert input_hash("title_optimization", {"a": 1, "b": 2}) == input_hash(
        "title_optimization", {"b": 2, "a": 1}
    )
    assert input_hash("title_optimization", {"a": 1}) != input_hash(
        "title_optimization", {"a": 2}
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_ai_tasks.py -v`
Expected: FAIL (no `description_optimization`, `spec.response_model` missing).

- [ ] **Step 3: Implement**

```python
# backend/app/ai/tasks.py
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from ..staging.hashing import canonical_json
from . import schemas

# The authoritative variable set per task type. Templates (DB or builtin)
# may only reference these; anything else fails validation at write time.
CANONICAL_VARIABLES: dict[str, list[str]] = {
    "title_optimization": ["brand", "title"],
    "description_optimization": ["title", "description"],
    "category_classification": ["title", "description"],
    "policy_check": ["title", "description"],
    "attribute_enrichment": ["title", "description"],
    "image_quality": ["image_link"],
}


@dataclass(frozen=True)
class TaskSpec:
    system: str
    user: str
    response_model: type[BaseModel]


TASK_SPECS: dict[str, TaskSpec] = {
    "title_optimization": TaskSpec(
        system=(
            "You rewrite product titles for Google Merchant Center. "
            "Reply with the optimized title only, no explanations. "
            "Do not use promotional language or all capital letters."
        ),
        user=(
            "Brand: {{brand}}\nCurrent title: {{title}}\n"
            "Rewrite the title to be concise and search-friendly."
        ),
        response_model=schemas.OptimizedTitle,
    ),
    "description_optimization": TaskSpec(
        system=(
            "You rewrite product descriptions for Google Merchant Center. "
            "Reply with the optimized description only, no explanations."
        ),
        user=(
            "Title: {{title}}\nCurrent description: {{description}}\n"
            "Rewrite the description to be clear and complete."
        ),
        response_model=schemas.OptimizedDescription,
    ),
    "category_classification": TaskSpec(
        system=(
            "You classify products into Google product categories. "
            "Reply with the numeric taxonomy id only. "
            "Example: 2271 for Apparel & Accessories > Clothing > Dresses."
        ),
        user="Title: {{title}}\nDescription: {{description}}\nClassify.",
        response_model=schemas.CategoryAssignment,
    ),
    "policy_check": TaskSpec(
        system=(
            "You check product data against Google Merchant Center policies. "
            "Return the list of violations and a confidence between 0 and 1."
        ),
        user="Title: {{title}}\nDescription: {{description}}\nCheck for policy violations.",
        response_model=schemas.PolicyCheckResult,
    ),
    "attribute_enrichment": TaskSpec(
        system=(
            "You extract product attributes from free text. Extract color, "
            "size, material, gtin, gender, age_group, and up to five custom labels. "
            "gender is one of male, female, unisex. "
            "age_group is one of newborn, infant, toddler, kids, adult. "
            "Use custom_label_0 through custom_label_4. Omit anything unknown."
        ),
        user="Title: {{title}}\nDescription: {{description}}\nExtract the attributes.",
        response_model=schemas.EnrichedAttributes,
    ),
    "image_quality": TaskSpec(
        system=(
            "You assess product images for Google Merchant Center. "
            "Report watermark, text overlay, background, and confidence between 0 and 1."
        ),
        user="Image URL: {{image_link}}\nAssess the image.",
        response_model=schemas.ImageQualityResult,
    ),
}


def input_hash(task_type: str, variables: dict[str, Any]) -> str:
    payload = canonical_json({"task_type": task_type, "variables": variables})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

Confirm `schemas` is importable without a circular import: `schemas.py` imports only `constraints`/`taxonomy`, so no cycle.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_ai_tasks.py -v`
Expected: PASS.

- [ ] **Step 5: Confirm no remaining `validate_task` importers**

Run: `rg -n "validate_task|_validate_json|_validate_text" backend/`
Expected: only `app/ai/service.py` (rewritten in Task 9). Do not fix it here.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai/tasks.py backend/tests/test_ai_tasks.py
git commit -m "feat(ai): task registry carries instructor response models"
```

---

### Task 6: Data model and migration

**Files:**
- Modify: `app/models/ai.py`, `app/models/global_setting.py`
- Modify: `app/schemas/admin.py`, `app/routes/admin.py`, `app/ai/purge.py`
- Create: `alembic/versions/<rev>_m15_ai_litellm_core.py` (via autogenerate, then edited)
- Test: `tests/test_ai_models.py`, `tests/test_admin_settings_api.py`, `tests/test_ai_purge.py`

**Interfaces:**
- Produces: `AiProviderConfig.tier: str` (no `is_default`); `GlobalSetting` AI columns; `AiUsageLog.provider/tier/fallback_used`; `ai_result_cache` table dropped.

- [ ] **Step 1: Edit the models**

In `app/models/ai.py`:
- `AiProviderConfig`: replace `is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)` with `tier: Mapped[str] = mapped_column(String(20), nullable=False, default="bulk", server_default="bulk")`.
- Delete the `AiResultCache` class entirely.
- `AiUsageLog`: add after `model`:
```python
    provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
```

In `app/models/global_setting.py`, add:
```python
    ai_cache_type: Mapped[str] = mapped_column(String(20), nullable=False, default="local", server_default="local")
    ai_cache_namespace: Mapped[str] = mapped_column(String(100), nullable=False, default="gmc-ai", server_default="gmc-ai")
    ai_cache_ttl_taxonomy_s: Mapped[int] = mapped_column(Integer, nullable=False, default=2592000, server_default="2592000")
    ai_cache_ttl_content_s: Mapped[int] = mapped_column(Integer, nullable=False, default=604800, server_default="604800")
    ai_router_timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    ai_router_num_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    ai_router_allowed_fails: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    ai_router_cooldown_s: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    ai_instructor_max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
```
and delete `ai_cache_retention_days`.

Add `from sqlalchemy import String` to the global_setting imports.

- [ ] **Step 2: Autogenerate the migration**

Run (from `backend/`, with `DATABASE_URL` exported per Global Constraints):
```bash
uv run alembic revision --autogenerate -m "m15 ai litellm core"
```
Expected: a new file named `*_m15_ai_litellm_core.py`.

- [ ] **Step 3: Edit the migration to preserve data**

Open the generated file. Before the `drop_column("ai_provider_configs", "is_default")`, insert a data step that maps legacy defaults:
```python
    op.execute("UPDATE ai_provider_configs SET tier = 'bulk' WHERE is_default = true")
```
Confirm the generated `drop_table("ai_result_cache")` and `drop_column("global_settings", "ai_cache_retention_days")` are present. Ensure `downgrade()` recreates them.

- [ ] **Step 4: Update admin settings schema and route**

In `app/schemas/admin.py`, remove `ai_cache_retention_days` from `GlobalSettingsOut` (and thus `GlobalSettingsUpdate`).

In `app/routes/admin.py`:
- `get_settings_row`: drop `ai_cache_retention_days=90` from the seed `GlobalSetting(...)`.
- `put_settings_row`: drop `ai_cache_retention_days=90` from the seed and the assignment line.

- [ ] **Step 5: Update the AI purge**

In `app/ai/purge.py`:
- Remove the `AiResultCache` import and use.
- `AiPurgeCounts` keeps `usage_rows`; change `cache_rows` to always `0` for response compatibility, or (preferred) rename the field to `usage_rows` only and update the `main.py` log line at `main.py:170` (`"ai purge: %s usage rows, %s cache rows"`). Choose the rename and update the log to `"ai purge: %s usage rows"`.
- `_retention` returns only `ai_usage_retention_days`.
- Delete the cache delete statement.

- [ ] **Step 6: Update the affected tests**

- `tests/test_ai_models.py`: remove `AiResultCache` assertions; assert `AiProviderConfig.tier` defaults to `"bulk"` and `is_default` no longer exists; assert new `AiUsageLog` columns.
- `tests/test_admin_settings_api.py`: remove `ai_cache_retention_days` from payloads/assertions; add a rejection test that sending it is ignored (`extra="ignore"`) or absent.
- `tests/test_ai_purge.py`: assert `AiPurgeCounts` has no `cache_rows` and only usage rows are purged.

- [ ] **Step 7: Apply and verify**

Run (from `backend/`, with `DATABASE_URL` exported):
```bash
uv run alembic upgrade head
uv run alembic check
uv run pytest tests/test_ai_models.py tests/test_admin_settings_api.py tests/test_ai_purge.py -v
```
Expected: `alembic check` reports no pending changes; tests PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/ai.py backend/app/models/global_setting.py backend/app/schemas/admin.py backend/app/routes/admin.py backend/app/ai/purge.py backend/alembic/versions backend/tests
git commit -m "feat(ai): provider tier, AI settings columns, drop DB result cache (m15)"
```

---

### Task 7: Router and Instructor builder

**Files:**
- Create: `app/ai/router.py`
- Test: `tests/test_ai_router.py`

**Interfaces:**
- Consumes: `AiProviderConfig` rows.
- Produces:
  - `@dataclass(frozen=True) RouterSettings(timeout_s, num_retries, allowed_fails, cooldown_s, instructor_max_retries)`
  - `async def load_router_settings(session_factory) -> RouterSettings`
  - `def deployment_for(row: AiProviderConfig) -> dict`
  - `def build_router(rows: Sequence[AiProviderConfig], cfg: RouterSettings) -> Router`
  - `def build_instructor(router: Router) -> Any`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ai_router.py
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai import router as ai_router


def _row(**kw):
    base = dict(
        id=1, name="bulk-1", provider_type="litellm", base_url="", api_key="",
        model="openai/gpt-4o-mini", tier="bulk", max_concurrency=4, timeout_s=30,
        enabled=True,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_deployment_for_litellm_row() -> None:
    dep = ai_router.deployment_for(_row())
    assert dep["model_name"] == "bulk"
    assert dep["litellm_params"]["model"] == "openai/gpt-4o-mini"
    assert dep["litellm_params"]["timeout"] == 30


def test_deployment_for_legacy_openai_compatible_row() -> None:
    dep = ai_router.deployment_for(
        _row(provider_type="openai_compatible", model="gpt-4o-mini",
             base_url="https://api.example.com/v1", api_key="sk-x")
    )
    assert dep["litellm_params"]["model"] == "openai/gpt-4o-mini"
    assert dep["litellm_params"]["api_base"] == "https://api.example.com/v1"
    assert dep["litellm_params"]["api_key"] == "sk-x"


def test_deployment_does_not_double_prefix_already_prefixed_model() -> None:
    dep = ai_router.deployment_for(
        _row(provider_type="openai_compatible", model="openai/gpt-4o-mini")
    )
    assert dep["litellm_params"]["model"] == "openai/gpt-4o-mini"


def test_build_router_skips_disabled_rows(monkeypatch) -> None:
    captured = {}

    class FakeRouter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(ai_router, "Router", FakeRouter)
    cfg = ai_router.RouterSettings(30, 2, 3, 30, 2)
    ai_router.build_router([_row(enabled=True), _row(id=2, enabled=False)], cfg)
    assert [d["model_name"] for d in captured["model_list"]] == ["bulk"]
    assert captured["fallbacks"] == [{"bulk": ["precision"]}]
    assert captured["num_retries"] == 2
    assert captured["allowed_fails"] == 3
    assert captured["cooldown_time"] == 30
    assert captured["timeout"] == 30


@pytest.mark.asyncio
async def test_load_router_settings_uses_defaults_when_no_row() -> None:
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args):
            return None

    def factory():
        return FakeSession()

    cfg = await ai_router.load_router_settings(factory)
    assert cfg == ai_router.RouterSettings(30, 2, 3, 30, 2)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_ai_router.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/app/ai/router.py
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import instructor
from litellm import Router
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.ai import AiProviderConfig
from ..models.global_setting import GlobalSetting

logger = logging.getLogger(__name__)

TIERS = ("bulk", "precision")
FALLBACKS = [{"bulk": ["precision"]}]


@dataclass(frozen=True)
class RouterSettings:
    timeout_s: int = 30
    num_retries: int = 2
    allowed_fails: int = 3
    cooldown_s: int = 30
    instructor_max_retries: int = 2


async def load_router_settings(
    session_factory: Callable[[], AsyncSession],
) -> RouterSettings:
    async with session_factory() as session:
        row = await session.get(GlobalSetting, 1)
    if row is None:
        return RouterSettings()
    return RouterSettings(
        timeout_s=row.ai_router_timeout_s,
        num_retries=row.ai_router_num_retries,
        allowed_fails=row.ai_router_allowed_fails,
        cooldown_s=row.ai_router_cooldown_s,
        instructor_max_retries=row.ai_instructor_max_retries,
    )


def _litellm_model(row: AiProviderConfig) -> str:
    if "/" in row.model:
        return row.model
    if row.provider_type == "openai_compatible":
        return f"openai/{row.model}"
    return row.model


def deployment_for(row: AiProviderConfig) -> dict[str, Any]:
    params: dict[str, Any] = {"model": _litellm_model(row)}
    if row.base_url:
        params["api_base"] = row.base_url
    if row.api_key:
        params["api_key"] = row.api_key
    params["timeout"] = row.timeout_s
    return {"model_name": row.tier, "litellm_params": params}


def build_router(
    rows: Sequence[AiProviderConfig], cfg: RouterSettings
) -> Router:
    model_list = [deployment_for(row) for row in rows if row.enabled]
    return Router(
        model_list=model_list,
        fallbacks=FALLBACKS,
        num_retries=cfg.num_retries,
        allowed_fails=cfg.allowed_fails,
        cooldown_time=cfg.cooldown_s,
        timeout=cfg.timeout_s,
    )


def build_instructor(router: Router) -> Any:
    return instructor.from_litellm(router.acompletion, async_client=True)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_ai_router.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/router.py backend/tests/test_ai_router.py
git commit -m "feat(ai): litellm router + instructor builder with tier failover"
```

---

### Task 8: Native cache wrapper

**Files:**
- Create: `app/ai/cache_config.py`
- Test: `tests/test_ai_cache.py`

**Interfaces:**
- Consumes: `Settings` (`redis_url`, `ai_cache_dir`), `GlobalSetting` row.
- Produces:
  - `@dataclass(frozen=True) CacheSettings(cache_type, namespace, ttl_taxonomy_s, ttl_content_s, redis_url, disk_dir)`
  - `async def load_cache_settings(session_factory, settings) -> CacheSettings`
  - `class NativeCache` with `enabled: bool`, `request_kwargs(task_type) -> dict`, `async lookup(**kwargs) -> Any | None`, `async store(response, **kwargs) -> None`, `async status() -> dict`, `async clear(namespace: str | None) -> int`
  - `TAXONOMY_TASKS = {"category_classification"}`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ai_cache.py
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.ai import cache_config


def _settings(redis_url=None, cache_dir="/tmp/ai-cache"):
    return SimpleNamespace(redis_url=redis_url, ai_cache_dir=cache_dir)


def test_effective_backend_prefers_redis_from_env() -> None:
    cfg = cache_config.CacheSettings(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=1,
        ttl_content_s=2, redis_url="redis://localhost:6379/0", disk_dir="/tmp/x",
    )
    assert cache_config.effective_backend(cfg) == "redis"


def test_effective_backend_uses_row_type_without_redis() -> None:
    cfg = cache_config.CacheSettings(
        cache_type="disk", namespace="gmc-ai", ttl_taxonomy_s=1,
        ttl_content_s=2, redis_url=None, disk_dir="/tmp/x",
    )
    assert cache_config.effective_backend(cfg) == "disk"


def test_request_kwargs_namespace_and_ttl() -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=100,
        ttl_content_s=5, redis_url=None, disk_dir="/tmp/x",
    )
    content = cache.request_kwargs("title_optimization")
    taxonomy = cache.request_kwargs("category_classification")
    assert content["cache"]["namespace"] == "gmc-ai:title_optimization"
    assert content["cache"]["ttl"] == 5
    assert taxonomy["cache"]["namespace"] == "gmc-ai:category_classification"
    assert taxonomy["cache"]["ttl"] == 100


@pytest.mark.asyncio
async def test_lookup_is_fail_open(monkeypatch) -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=1,
        ttl_content_s=1, redis_url=None, disk_dir="/tmp/x",
    )

    class Boom:
        async def async_get_cache(self, **kwargs):
            raise RuntimeError("backend down")

    cache._cache = Boom()  # type: ignore[assignment]
    assert await cache.lookup(model="bulk", messages=[]) is None


@pytest.mark.asyncio
async def test_store_only_writes_validated_payload(monkeypatch) -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=1,
        ttl_content_s=1, redis_url=None, disk_dir="/tmp/x",
    )
    fake = MagicMock()
    calls = []

    async def async_add_cache(response, **kwargs):
        calls.append((response, kwargs))

    fake.async_add_cache = async_add_cache
    cache._cache = fake  # type: ignore[assignment]
    await cache.store({"validated": True}, model="bulk", messages=[])
    assert calls and calls[0][0] == {"validated": True}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_ai_cache.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/app/ai/cache_config.py
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import litellm
from litellm.caching.caching import Cache
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..models.global_setting import GlobalSetting

logger = logging.getLogger(__name__)

TAXONOMY_TASKS = frozenset({"category_classification"})


@dataclass(frozen=True)
class CacheSettings:
    cache_type: str
    namespace: str
    ttl_taxonomy_s: int
    ttl_content_s: int
    redis_url: str | None
    disk_dir: str


def effective_backend(cfg: CacheSettings) -> str:
    if cfg.redis_url:
        return "redis"
    return cfg.cache_type if cfg.cache_type in ("local", "disk") else "local"


async def load_cache_settings(
    session_factory: Callable[[], AsyncSession], settings: Settings
) -> CacheSettings:
    async with session_factory() as session:
        row = await session.get(GlobalSetting, 1)
    if row is None:
        return CacheSettings("local", "gmc-ai", 2592000, 604800, settings.redis_url, settings.ai_cache_dir)
    return CacheSettings(
        cache_type=row.ai_cache_type,
        namespace=row.ai_cache_namespace,
        ttl_taxonomy_s=row.ai_cache_ttl_taxonomy_s,
        ttl_content_s=row.ai_cache_ttl_content_s,
        redis_url=settings.redis_url,
        disk_dir=settings.ai_cache_dir,
    )


class NativeCache:
    def __init__(
        self,
        *,
        cache_type: str,
        namespace: str,
        ttl_taxonomy_s: int,
        ttl_content_s: int,
        redis_url: str | None,
        disk_dir: str,
    ) -> None:
        self._cfg = CacheSettings(
            cache_type, namespace, ttl_taxonomy_s, ttl_content_s, redis_url, disk_dir
        )
        self._cache: Any = self._build()
        self.enabled = self._cache is not None

    def _build(self) -> Any:
        try:
            if self._cfg.redis_url:
                built = Cache(type="redis", url=self._cfg.redis_url, namespace=self._cfg.namespace)
            elif self._cfg.cache_type == "disk":
                built = Cache(type="disk", disk_cache_dir=self._cfg.disk_dir, namespace=self._cfg.namespace)
            else:
                built = Cache(type="local", namespace=self._cfg.namespace)
            litellm.cache = built
            return built
        except Exception:
            logger.warning("ai cache: failed to build backend; continuing without cache", exc_info=True)
            return None

    def request_kwargs(self, task_type: str) -> dict[str, Any]:
        ttl = self._cfg.ttl_taxonomy_s if task_type in TAXONOMY_TASKS else self._cfg.ttl_content_s
        return {"cache": {"namespace": f"{self._cfg.namespace}:{task_type}", "ttl": ttl}}

    async def lookup(self, **kwargs: Any) -> Any | None:
        if self._cache is None:
            return None
        try:
            return await self._cache.async_get_cache(**kwargs)
        except Exception:
            logger.warning("ai cache: lookup failed; treating as miss", exc_info=True)
            return None

    async def store(self, response: Any, **kwargs: Any) -> None:
        if self._cache is None:
            return
        try:
            await self._cache.async_add_cache(response, **kwargs)
        except Exception:
            logger.warning("ai cache: store failed; continuing", exc_info=True)

    async def status(self) -> dict[str, Any]:
        backend = effective_backend(self._cfg)
        healthy = True
        entries: int | None = None
        try:
            if self._cache is None:
                healthy = False
            elif backend == "redis":
                entries = None  # verified in phase C status endpoint
        except Exception:
            logger.warning("ai cache: status probe failed", exc_info=True)
            healthy = False
        return {
            "effective_backend": backend,
            "redis_from_env": bool(self._cfg.redis_url),
            "healthy": healthy,
            "namespace": self._cfg.namespace,
            "entries": entries,
        }

    async def clear(self, namespace: str | None = None) -> int:
        if self._cache is None:
            return 0
        try:
            cleared = 0
            if namespace:
                await self._cache.async_clear_cache()
                cleared = 1
            else:
                await self._cache.async_clear_cache()
                cleared = 1
            return cleared
        except Exception:
            logger.warning("ai cache: clear failed", exc_info=True)
            return 0
```

Note for the implementer: `Cache` accepts `url=` for Redis in current LiteLLM; Task 1's spike is the authority. If `url` is not a parameter, pass `host`/`port`/`password` parsed from `redis_url`. `async_clear_cache` clears the whole backend; per-namespace clearing is refined against the real API in phase C (the status/clear endpoints). This task delivers namespacing + TTL + fail-open, which the service uses.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_ai_cache.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/cache_config.py backend/tests/test_ai_cache.py
git commit -m "feat(ai): litellm native cache wrapper with namespaces and ttl"
```

---

### Task 9: `AiService` cutover

**Files:**
- Modify: `app/ai/service.py`
- Modify: `app/config.py` (add `redis_url`, `ai_cache_dir`)
- Test: `tests/test_ai_service.py` (rewrite)

**Interfaces:**
- Consumes: `router.build_router`, `router.build_instructor`, `router.load_router_settings`, `cache_config.NativeCache`, `cache_config.load_cache_settings`, `schemas.RESPONSE_MODELS`, `tasks.TASK_SPECS`.
- Produces: unchanged public API on `AiService` (`run_task`, `complete_chat`, `test_provider`, `invalidate`) and unchanged `AiResult` / `AiChatUnavailable`.

- [ ] **Step 1: Add the config fields**

In `app/config.py` `Settings`, add:
```python
    redis_url: str | None = None
    ai_cache_dir: str = str(Path(__file__).resolve().parents[2] / ".cache" / "ai")
```

- [ ] **Step 2: Rewrite the service test**

```python
# backend/tests/test_ai_service.py
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from app.ai import service as ai_service_module
from app.ai.router import RouterSettings
from app.ai.service import AiResult, AiService


class _FakeModel(BaseModel):
    value: str


def _provider_rows():
    return [SimpleNamespace(
        id=1, name="bulk", provider_type="litellm", base_url="", api_key="",
        model="openai/gpt-4o-mini", tier="bulk", max_concurrency=4, timeout_s=30,
        enabled=True,
        input_price_per_mtok=None, output_price_per_mtok=None,
    )]


@pytest.fixture()
def service() -> AiService:
    svc = AiService(session_factory=MagicMock(), clock=None)
    # Pre-set router/cache state so run_task does not hit the DB or build a real Router.
    svc._router = MagicMock()
    svc._router_settings = RouterSettings()
    svc._cache = MagicMock()
    svc._cache.lookup = AsyncMock(return_value=None)
    svc._cache.store = AsyncMock()
    svc._cache.request_kwargs = MagicMock(return_value={"cache": {"namespace": "n", "ttl": 1}})
    svc._usage = MagicMock()
    svc._usage.write = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_run_task_returns_validated_value(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_resolve_template", AsyncMock(
        return_value=ai_service_module.ResolvedTemplate("sys", "user", "v1")
    ))
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))

    completion = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5), model="gpt-4o-mini"
    )
    instructor_client = MagicMock()
    instructor_client.create_with_completion = AsyncMock(
        return_value=(_FakeModel(value="ok"), completion)
    )
    monkeypatch.setattr(service, "_instructor", lambda: instructor_client)

    result = await service.run_task("title_optimization", {"title": "t"})
    assert result.status == "ok"
    assert result.value == _FakeModel(value="ok")
    assert result.prompt_tokens == 10
    instructor_client.create_with_completion.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_task_returns_fallback_on_instructor_failure(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_resolve_template", AsyncMock(
        return_value=ai_service_module.ResolvedTemplate("sys", "user", "v1")
    ))
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))

    instructor_client = MagicMock()
    instructor_client.create_with_completion = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(service, "_instructor", lambda: instructor_client)

    result = await service.run_task("title_optimization", {"title": "t"})
    assert result.status == "fallback"
    assert result.value is None
    assert result.error_code == "provider_error"


@pytest.mark.asyncio
async def test_run_task_no_provider_is_fallback(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_resolve_template", AsyncMock(
        return_value=ai_service_module.ResolvedTemplate("sys", "user", "v1")
    ))
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=[]))
    result = await service.run_task("title_optimization", {"title": "t"})
    assert result == AiResult(value=None, status="fallback", error_code="no_provider",
                              prompt_tokens=0, completion_tokens=0)


@pytest.mark.asyncio
async def test_run_task_cache_hit_skips_llm(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_resolve_template", AsyncMock(
        return_value=ai_service_module.ResolvedTemplate("sys", "user", "v1")
    ))
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))
    service._cache.lookup = AsyncMock(return_value={"value": "cached"})
    instructor_client = MagicMock()
    instructor_client.create_with_completion = AsyncMock()
    monkeypatch.setattr(service, "_instructor", lambda: instructor_client)

    result = await service.run_task("title_optimization", {"title": "t"})
    assert result.status == "cache_hit"
    assert result.value.title == "cached"
    instructor_client.create_with_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_task_unknown_task_is_fallback(service) -> None:
    result = await service.run_task("nope", {})
    assert result.status == "fallback"
    assert result.error_code == "invalid_task"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_ai_service.py -v`
Expected: FAIL (old internals still call `_provider_for` / `validate_task`).

- [ ] **Step 4: Implement the new internals**

In `app/ai/service.py`:
- Delete imports of `OpenAICompatibleProvider`, `AIProvider`, `AiRequest`, `AiResponse` (keep `AiResponse` — chat uses it), `CircuitBreaker`, `RetryPolicy`, `classify_failure`, `validate_task`.
- Delete `default_provider_factory`, `_provider_for`, `_breaker_for`, `_call_provider`, and `complete_chat`'s manual retry loop (Router handles retries).
- Add:

```python
class AiService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        clock: Clock | None = None,
        settings: Settings | None = None,
        retry_policy: None = None,  # removed in phase D
        breaker_failure_threshold: int | None = None,  # removed in phase D
        breaker_window_s: int | None = None,  # removed in phase D
        breaker_cooldown_s: int | None = None,  # removed in phase D
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._settings = settings if settings is not None else get_settings()
        self._usage = UsageLogWriter(session_factory)
        self._cache: Any = None
        self._router: Any = None
        self._instructor_client: Any = None
        self._router_settings: RouterSettings | None = None

    async def _load_deployments(self) -> list[AiProviderConfig]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(AiProviderConfig).where(AiProviderConfig.enabled.is_(True)).order_by(AiProviderConfig.id)
            )
            return list(result.scalars())

    def _ensure_built(self, rows: list[AiProviderConfig], cfg: RouterSettings) -> None:
        self._router_settings = cfg
        self._router = build_router(rows, cfg)
        self._instructor_client = build_instructor(self._router)

    def _instructor(self) -> Any:
        if self._instructor_client is None:
            raise AiChatUnavailable("no_provider")
        return self._instructor_client

    async def _ensure_cache(self) -> None:
        if self._cache is None:
            cache_cfg = await load_cache_settings(self._session_factory, self._settings)
            self._cache = NativeCache(
                cache_type=cache_cfg.cache_type,
                namespace=cache_cfg.namespace,
                ttl_taxonomy_s=cache_cfg.ttl_taxonomy_s,
                ttl_content_s=cache_cfg.ttl_content_s,
                redis_url=cache_cfg.redis_url,
                disk_dir=cache_cfg.disk_dir,
            )

    def invalidate(self, provider_config_id: int | None = None) -> None:
        self._router = None
        self._instructor_client = None
        self._cache = None
```

- Replace `run_task` with:

```python
    async def run_task(
        self,
        task_type: str,
        variables: dict[str, Any],
        *,
        client_id: int | None = None,
        feed_source_id: int | None = None,
    ) -> AiResult:
        if task_type not in TASK_SPECS:
            await self._log_usage(UsageRecord(
                client_id=client_id, feed_source_id=feed_source_id,
                task_type=task_type, provider_config_id=None, model="",
                cache_hit=False, prompt_tokens=0, completion_tokens=0,
                cost_usd=None, latency_ms=0, error_code="invalid_task",
            ))
            return AiResult(value=None, status="fallback", error_code="invalid_task",
                            prompt_tokens=0, completion_tokens=0)

        rows = await self._load_deployments()
        if not rows:
            await self._log_usage(UsageRecord(
                client_id=client_id, feed_source_id=feed_source_id,
                task_type=task_type, provider_config_id=None, model="",
                cache_hit=False, prompt_tokens=0, completion_tokens=0,
                cost_usd=None, latency_ms=0, error_code="no_provider",
            ))
            return AiResult(value=None, status="fallback", error_code="no_provider",
                            prompt_tokens=0, completion_tokens=0)

        try:
            template = await self._resolve_template(task_type, client_id)
            messages = render_messages(template.system, template.user, variables)
        except TaskSpecError:
            await self._log_usage(UsageRecord(
                client_id=client_id, feed_source_id=feed_source_id,
                task_type=task_type, provider_config_id=None, model="",
                cache_hit=False, prompt_tokens=0, completion_tokens=0,
                cost_usd=None, latency_ms=0, error_code="invalid_task",
            ))
            return AiResult(value=None, status="fallback", error_code="invalid_task",
                            prompt_tokens=0, completion_tokens=0)

        cfg = self._router_settings or await load_router_settings(self._session_factory)
        if self._router is None:
            self._ensure_built(rows, cfg)
        await self._ensure_cache()

        response_model = TASK_SPECS[task_type].response_model
        cache_kwargs = self._cache.request_kwargs(task_type)
        request_kwargs = {"model": "bulk", "messages": messages, **cache_kwargs}

        cached = await self._cache.lookup(**request_kwargs)
        if cached is not None:
            try:
                value = response_model.model_validate(cached)
            except Exception:
                value = None
            if value is not None:
                await self._log_usage(UsageRecord(
                    client_id=client_id, feed_source_id=feed_source_id,
                    task_type=task_type, provider_config_id=None, model="bulk",
                    cache_hit=True, prompt_tokens=0, completion_tokens=0,
                    cost_usd=None, latency_ms=0, error_code=None,
                ))
                return AiResult(value=value, status="cache_hit", error_code=None,
                                prompt_tokens=0, completion_tokens=0)

        try:
            value, completion = await self._instructor().create_with_completion(
                response_model=response_model,
                messages=messages,
                max_retries=cfg.instructor_max_retries,
                **request_kwargs,
            )
        except Exception as exc:
            logger.warning("ai task %s failed: %s", task_type, exc, exc_info=True)
            await self._log_usage(UsageRecord(
                client_id=client_id, feed_source_id=feed_source_id,
                task_type=task_type, provider_config_id=None, model="bulk",
                cache_hit=False, prompt_tokens=0, completion_tokens=0,
                cost_usd=None, latency_ms=0, error_code="provider_error",
            ))
            return AiResult(value=None, status="fallback", error_code="provider_error",
                            prompt_tokens=0, completion_tokens=0)

        await self._cache.store(value.model_dump(), **request_kwargs)
        usage = getattr(completion, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        await self._log_usage(UsageRecord(
            client_id=client_id, feed_source_id=feed_source_id,
            task_type=task_type, provider_config_id=None, model="bulk",
            cache_hit=False, prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens, cost_usd=None, latency_ms=0,
            error_code=None,
        ))
        return AiResult(value=value, status="ok", error_code=None,
                        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
```

- `complete_chat` keeps its contract but calls the Instructor/Router path with `messages`/`tools` and `response_model=None`; use `self._router.acompletion(model="bulk", messages=messages, tools=tools)` and adapt to `AiResponse`. Keep raising `AiChatUnavailable` on failure. (Chat is untyped, so no Instructor.)
- `test_provider`: build a one-row Router for that config and issue a minimal completion; return the same dict shape. If the real call cannot be isolated, keep the current behavior by constructing a temporary `Router` with just that row.
- Imports to add at top:

```python
from ..config import Settings, get_settings
from ..models.ai import AiProviderConfig
from .cache_config import NativeCache, load_cache_settings
from .router import RouterSettings, build_instructor, build_router, load_router_settings
from .schemas import RESPONSE_MODELS  # noqa: F401 — re-exported for callers
```

- Update `main.py:270` to pass settings:
```python
        from .config import get_settings
        ai_service = AiService(app.state.db_session_factory, clock=app.state.clock, settings=get_settings())
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_ai_service.py -v`
Expected: PASS.

- [ ] **Step 6: Verify parity callers still pass**

Run: `uv run pytest tests/test_ai_policy_check.py tests/test_chat_api.py tests/test_ai_cache_usage.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/ai/service.py backend/app/config.py backend/app/main.py backend/tests/test_ai_service.py
git commit -m "feat(ai): route run_task through litellm router + instructor"
```

---

### Task 10: Admin provider backend (tier, drop default)

**Files:**
- Modify: `app/schemas/ai_admin.py`, `app/routes/ai_admin.py`
- Test: `tests/test_ai_admin_api.py`

**Interfaces:**
- Consumes: `AiProviderConfig.tier`.
- Produces: `AiProviderOut.tier`, no `is_default`; `AiProviderCreate/Update` accept `tier` and `provider_type: Literal["litellm", "openai_compatible"]`.

- [ ] **Step 1: Update the test**

In `tests/test_ai_admin_api.py`:
- Replace every `is_default` in payloads with `tier`.
- Add:
```python
async def test_provider_out_has_tier_and_no_default(admin_http) -> None:
    response = await admin_http.post("/admin/ai/providers", json={
        "name": "p1", "provider_type": "litellm",
        "base_url": "", "model": "openai/gpt-4o-mini",
        "tier": "bulk", "max_concurrency": 4, "timeout_s": 30, "enabled": True,
    })
    assert response.status_code == 201
    body = response.json()
    assert body["tier"] == "bulk"
    assert "is_default" not in body


async def test_provider_rejects_unknown_tier(admin_http) -> None:
    response = await admin_http.post("/admin/ai/providers", json={
        "name": "p2", "provider_type": "litellm", "base_url": "",
        "model": "openai/gpt-4o-mini", "tier": "platinum",
        "max_concurrency": 4, "timeout_s": 30, "enabled": True,
    })
    assert response.status_code == 422
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ai_admin_api.py -v`
Expected: FAIL (`is_default` still returned; `tier` unknown).

- [ ] **Step 3: Implement**

In `app/schemas/ai_admin.py`:
- `AiProviderOut`: replace `is_default: bool` with `tier: str`.
- `AiProviderCreate`: `provider_type: Literal["litellm", "openai_compatible"] = "litellm"`; remove `is_default`; add `tier: Literal["bulk", "precision"] = "bulk"`.
- `AiProviderUpdate`: same literal widening; remove `is_default`; add `tier: Literal["bulk", "precision"] | None = None`.

In `app/routes/ai_admin.py`:
- Delete `_clear_other_defaults` and its two call sites.
- After provider create/update/delete, call `service.invalidate()` (already present for update/delete; add to create).
- Drop the `is_default` handling.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ai_admin_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/ai_admin.py backend/app/routes/ai_admin.py backend/tests/test_ai_admin_api.py
git commit -m "feat(ai): provider tier in admin api, remove is_default"
```

---

### Task 11: Admin provider frontend (tier, no default)

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/hooks.ts`
- Modify: `frontend/src/features/admin/ai/ProvidersPage.tsx`
- Modify: i18n files under `frontend/src/i18n/`
- Test: `frontend/src/features/admin/ai/ProvidersPage.test.tsx`

**Interfaces:**
- Consumes: backend provider `tier`, `provider_type` widening.
- Produces: provider form with tier select and backend type select; no default toggle.

- [ ] **Step 1: Update types**

In `frontend/src/api/types.ts`, `AiProvider`: replace `is_default: boolean` with `tier: 'bulk' | 'precision'`; add `provider_type: 'litellm' | 'openai_compatible'`.

- [ ] **Step 2: Rewrite the test**

Replace `ProvidersPage.test.tsx` with:

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

beforeAll(async () => {
  await i18n.loadNamespaces('admin');
});

beforeEach(() => {
  stubFetch((url) => {
    if (url === '/admin/ai/providers') return jsonResponse(providers);
    return jsonResponse({});
  });
});

describe('ProvidersPage', () => {
  it('renders the provider table with a tier and no default badge', async () => {
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByTestId('ai-providers-table')).toBeInTheDocument());
    expect(screen.getByText('primary')).toBeInTheDocument();
    expect(screen.getByText('openai/gpt-4o-mini')).toBeInTheDocument();
    expect(screen.getByTestId('ai-provider-row-1')).toHaveTextContent('bulk');
    expect(screen.queryByText('Default')).not.toBeInTheDocument();
  });

  it('shows empty state when no providers exist', async () => {
    stubFetch((url) => {
      if (url === '/admin/ai/providers') return jsonResponse([]);
      return jsonResponse({});
    });
    render(<ProvidersPage />);
    await waitFor(() =>
      expect(screen.getByText('No AI providers configured')).toBeInTheDocument(),
    );
  });

  it('submits a provider with the selected tier', async () => {
    const posts: unknown[] = [];
    stubFetch((url, init) => {
      if (url === '/admin/ai/providers' && init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)));
        return jsonResponse({ ...providers[0], id: 2, tier: 'precision' }, 201);
      }
      if (url === '/admin/ai/providers') return jsonResponse(providers);
      return jsonResponse({});
    });
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByTestId('ai-providers-table')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('ai-add-provider'));
    fireEvent.change(screen.getByTestId('ai-modal-name'), { target: { value: 'primary2' } });
    fireEvent.change(screen.getByTestId('ai-modal-model'), {
      target: { value: 'openai/gpt-4o-mini' },
    });
    fireEvent.change(screen.getByTestId('ai-modal-tier'), { target: { value: 'precision' } });
    fireEvent.click(screen.getByTestId('ai-modal-save'));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ tier: 'precision' });
  });
});
```

- [ ] **Step 3: Update the page**

In `ProvidersPage.tsx`:
- Table: replace the default column with a tier column (`<Badge>{provider.tier}</Badge>`); remove the `is_default` badge cell.
- `ProviderModal`: add a `Select` for `tier` (`bulk`/`precision`) with `data-testid="ai-modal-tier"`, a `Select` for `provider_type` (`litellm`/`openai_compatible`) with `data-testid="ai-modal-provider-type"`, and `TextInput`s for `max_concurrency` and `timeout_s`; remove the `is_default` `Switch`.
- Add `data-testid="ai-add-provider"` to the "Add" button, `data-testid="ai-modal-model"` to the Model input, and `data-testid="ai-modal-save"` to the Save button.
- The modal's Save is disabled only by `name` and `model` (Base URL is optional for `litellm`).
- Create payload: `provider_type` from the select, `tier` from the select, `max_concurrency`/`timeout_s` parsed from the inputs (fall back to `4`/`30`), `base_url` from the input, and `api_key` only when non-empty.
- Update payload includes `tier` when changed.

- [ ] **Step 4: Update i18n**

Add keys to en + de under `admin.ai`: `columns.tier`, `tier.bulk`, `tier.precision`, `providerType`, `providerType.litellm`, `providerType.openaiCompatible`, `maxConcurrency`, `timeoutS`. Remove `columns.default` and `default` if unused elsewhere (check `rg "ai.default" frontend/src`).

- [ ] **Step 5: Run frontend checks**

Run from `frontend/`: `npm run test -- ProvidersPage && npm run typecheck`
Expected: PASS; no type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api frontend/src/features/admin/ai frontend/src/i18n
git commit -m "feat(ai): provider tier + type in admin provider UI"
```

---

### Task 12: Docs, ADR, and final gates

**Files:**
- Create: `docs/decisions/0010-litellm-instructor-ai-transport.md`
- Modify: `backend/docs/architecture.md`, `backend/docs/data-model.md`, `backend/docs/api.md`

**Interfaces:**
- Consumes: everything above.
- Produces: documentation reflecting the new core.

- [ ] **Step 1: Write the ADR**

Create `docs/decisions/0010-litellm-instructor-ai-transport.md` with sections: Topic, Decision, Rationale, Deviations. Cover: LiteLLM Router + Instructor replace the bespoke httpx provider and loose JSON validators; LiteLLM native cache replaces `ai_result_cache` with validated-only writes; provider `tier` replaces `is_default`; `.env` limited to `redis_url`/`ai_cache_dir` while the rest is DB-backed (surfaced in phase C); app→plugin taxonomy CSV coupling; library versions from Task 1.

- [ ] **Step 2: Update the backend docs**

- `backend/docs/architecture.md`: AI section describes Router + Instructor + native cache; remove `ai_result_cache` mentions; note tier failover.
- `backend/docs/data-model.md`: `ai_provider_configs.tier`, dropped `is_default`, dropped `ai_result_cache`, new `ai_usage_logs` telemetry columns, `global_settings` AI columns, dropped `ai_cache_retention_days`.
- `backend/docs/api.md`: provider payloads now carry `tier`; `/admin/settings` no longer has `ai_cache_retention_days`.

- [ ] **Step 3: Run the full gate suite**

From `backend/`:
```bash
uv run ruff check .
uv run mypy .
uv run pytest --report-log=.report.jsonl
```
Expected: ruff count equals `ruff-baseline.txt`; mypy exit 0; zero failed tests.

- [ ] **Step 4: Confirm no dead imports remain**

Run: `rg -n "openai_compat|default_provider_factory|AiResultCache|is_default" backend/app backend/tests`
Expected: only `app/ai/openai_compat.py` (deleted in phase D) and its own test `tests/test_ai_openai_compat.py`; everything else clean.

- [ ] **Step 5: Commit**

```bash
git add backend/docs docs/decisions
git commit -m "docs(ai): litellm + instructor core ADR and doc updates"
```

---

## Self-Review

**Spec coverage (phase A):**
- Transport via LiteLLM Router with bulk/precision failover → Tasks 7, 9.
- Instructor structured outputs + bounded retries → Tasks 4, 7, 9.
- Native cache, namespaces, TTLs, fail-open, validated-only → Task 8; schema sensitivity verified by the cache-hit test in Task 9.
- Provider config from DB rows; tier selection; legacy mapping → Tasks 6, 7, 10.
- Settings columns (router knobs, cache type/namespace/TTL, retention) → Task 6; endpoints/UI deferred to phase C.
- Telemetry columns (provider/tier/fallback) → Task 6; aggregation/population refined in phase C.
- Drop `ai_result_cache`, `ai_cache_retention_days`, `is_default` → Task 6.
- All new source passes ruff/mypy with no new baseline exceptions → Task 1 override + Tasks 2–12 gates.

**Deferred to later phases (intentionally not in this plan):** `EnrichmentStep`, `GET/PUT /admin/ai/settings`, cache status/stats/clear endpoints and `AiSettingsPage`, `UsagePage` KPIs, full `fallback_used` derivation, deletion of `openai_compat.py`/`cache.py`/`resilience.py` and the `AIProvider` Protocol, `description_optimization` exposure in the enrichment step.

**Type consistency:** `AiResult(value, status, error_code, prompt_tokens, completion_tokens)` is used unchanged across Tasks 9–10 and existing callers; `TaskSpec(system, user, response_model)` is consistent between Tasks 4, 5, 9; `RouterSettings` field names are identical in Tasks 6, 7, 9; `NativeCache.request_kwargs`/`lookup`/`store` signatures match between Tasks 8 and 9.

**Known verification points (explicitly handled, not placeholders):** Task 1's spike is the authority for `Router`/`Instructor`/`Cache` keyword shapes; Task 8's Redis `url=`/`async_clear_cache` and Task 9's `provider_config_id=None` cache logging are adjusted against it before dependent code is written.
