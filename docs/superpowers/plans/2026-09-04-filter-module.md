# Filter Module (Core Plugin `filter`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Second core pipeline module `filter` — drop products failing a conjunctive scalar condition set, with a single-pane custom UI and a live pass-count preview.

**Architecture:** `plugins/core/filter/` (manifest + self-contained evaluator + preview route + frontend stub). Config is one filter set (`isActive` + `conditions`) in `plugin_configs` JSONB via three-tier merge. `process()` returns the product unchanged when all conditions match, else `None` (drop → `excluded=true`). UI lives in `frontend/src/features/filter/` behind the proven stub seam; PluginPage gets a custom-component registry map.

**Tech Stack:** Python 3.10+ stdlib (backend engine), FastAPI APIRouter (preview route), React 19 + Mantine 8 + TanStack Query, i18next (en/de), pytest + vitest.

**Spec:** `docs/superpowers/specs/2026-09-04-filter-module-design.md`

## Global Constraints

- Plugin id: `filter`; must match `^[a-z][a-z0-9_]*$`.
- Core plugin lives in `plugins/core/filter/` → auto-enabled at discovery.
- Ops (exact set): `equals`, `not_equals`, `contains`, `not_contains`, `exists`, `empty`. NO numeric, NO regex, NO groups.
- `caseSensitive` flag (default `true`) applies to the four text ops (`equals`, `not_equals`, `contains`, `not_contains`).
- Missing-field semantics: `equals`/`contains` → false; `not_equals`/`not_contains` → **true**; `exists` → false; `empty` → true.
- `isActive: false` → pass-through; empty `conditions` → pass-all.
- `validate_config({})` must NOT raise (contract gate); strict on real documents (ValueError).
- `process()` never mutates `ctx.original_product`; returns product dict or None (None = drop).
- Plugin router paths must NOT start with `/config` or `/data` (`/preview` is fine).
- Plugin route handlers may import `app.*` modules (they run inside the backend process; `app` is importable — `uvicorn app.main:app` runs from `backend/`).
- No new dependencies (backend or frontend).
- Text ops coerce non-string values via `str()`; `None` → `""` for text comparison (but missing-field rules above take precedence for `not_*`).
- Locales: en + de in `frontend/public/locales/<lng>/filter.json`.
- Import arithmetic (repo-verified): from `frontend/src/features/filter/*` repo root is 4-up (`../../../../`); from `frontend/src/features/filter/__tests__/*` 5-up; from `plugins/core/filter/frontend/component.tsx` 4-up. Plugin stubs are ONE relative-only re-export line; PluginPage imports STUBS, never `frontend/src/features/...` directly.
- Test-import pattern for plugin python modules (established in rules tests): `sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins/core/filter"))` then `from plugin import ...` with `# noqa: E402`.
- Backend commands from `backend/`: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto -q`; lint via `uvx ruff check <files>` (ruff not in venv — pre-existing).
- Frontend commands from `frontend/`: `npm run typecheck`, `npm run test`, `npm run build`.
- Conventional Commits (`feat:`/`fix:`/`test:`/`docs:`).

---

### Task 1: Filter engine — condition evaluation, validation, FilterPlugin

**Files:**
- Create: `plugins/core/filter/__init__.py` (empty)
- Create: `plugins/core/filter/plugin.py`
- Test: `backend/tests/test_filter_plugin.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces (used by Tasks 2-3):
  - `class FilterError(ValueError)` — raised on malformed conditions at run time and validation failures
  - `evaluate_condition(condition: dict, product: dict) -> bool` — single condition
  - `passes_all(conditions: list[dict], product: dict) -> bool` — conjunctive; empty list → True
  - `validate_config(config: Any) -> None` — strict; `{}` and `{"conditions": []}` pass
  - `class FilterPlugin` with `validate_config(config) -> None`, `process(product, config, data, ctx) -> dict | None`, `register_routes(router: APIRouter) -> None` (registered in Task 3; stub in this task raising nothing — actually leave `register_routes` for Task 3 entirely; do NOT define it here)

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_filter_plugin.py`:

```python
"""FilterPlugin engine tests: condition ops, validation, process contract."""

import copy
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins/core/filter"))
from plugin import FilterPlugin, FilterError, evaluate_condition, passes_all, validate_config  # noqa: E402


def _ctx():
    class _Ctx:
        client_id = 0
        feed_source_id = 0
        run_id = 0
        logger = logging.getLogger("test")

    return _Ctx()


# --- evaluate_condition: text ops ---

def test_equals_case_sensitive_default():
    node = {"field": "brand", "op": "equals", "arg": "Acme"}
    assert evaluate_condition(node, {"brand": "Acme"}) is True
    assert evaluate_condition(node, {"brand": "acme"}) is False


def test_equals_case_insensitive():
    node = {"field": "brand", "op": "equals", "arg": "acme", "caseSensitive": False}
    assert evaluate_condition(node, {"brand": "ACME"}) is True


def test_not_equals_is_inverse_on_present_values():
    node = {"field": "brand", "op": "not_equals", "arg": "Acme"}
    assert evaluate_condition(node, {"brand": "Globex"}) is True
    assert evaluate_condition(node, {"brand": "Acme"}) is False


def test_not_equals_true_when_field_missing():
    node = {"field": "brand", "op": "not_equals", "arg": "Acme"}
    assert evaluate_condition(node, {}) is True


def test_contains_and_not_contains():
    has = {"field": "description", "op": "contains", "arg": "refurb"}
    assert evaluate_condition(has, {"description": "used refurbished item"}) is True
    assert evaluate_condition(has, {"description": "brand new"}) is False
    not_has = {"field": "description", "op": "not_contains", "arg": "refurb"}
    assert evaluate_condition(not_has, {"description": "brand new"}) is True
    assert evaluate_condition(not_has, {"description": "refurbished"}) is False


def test_not_contains_true_when_field_missing():
    node = {"field": "description", "op": "not_contains", "arg": "refurb"}
    assert evaluate_condition(node, {}) is True


def test_contains_case_insensitive():
    node = {"field": "title", "op": "contains", "arg": "sale", "caseSensitive": False}
    assert evaluate_condition(node, {"title": "BIG SALE today"}) is True


def test_text_ops_coerce_non_strings():
    node = {"field": "price", "op": "contains", "arg": "9"}
    assert evaluate_condition(node, {"price": 19.99}) is True


# --- evaluate_condition: exists / empty ---

def test_exists():
    node = {"field": "image_link", "op": "exists"}
    assert evaluate_condition(node, {"image_link": "https://x"}) is True
    assert evaluate_condition(node, {"image_link": None}) is False
    assert evaluate_condition(node, {}) is False


def test_empty():
    node = {"field": "image_link", "op": "empty"}
    assert evaluate_condition(node, {}) is True
    assert evaluate_condition(node, {"image_link": ""}) is True
    assert evaluate_condition(node, {"image_link": None}) is True
    assert evaluate_condition(node, {"image_link": "x"}) is False


# --- conjunctive evaluation ---

def test_passes_all_conjunction():
    conditions = [
        {"field": "brand", "op": "equals", "arg": "Acme"},
        {"field": "image_link", "op": "exists"},
    ]
    assert passes_all(conditions, {"brand": "Acme", "image_link": "x"}) is True
    assert passes_all(conditions, {"brand": "Acme"}) is False


def test_passes_all_empty_conditions_is_true():
    assert passes_all([], {"anything": 1}) is True


def test_evaluate_unknown_op_raises():
    with pytest.raises(FilterError):
        evaluate_condition({"field": "x", "op": "regex", "arg": "."}, {"x": "y"})


def test_evaluate_missing_field_key_raises():
    with pytest.raises(FilterError):
        evaluate_condition({"op": "equals", "arg": "x"}, {"y": "z"})


# --- validate_config ---

def test_validate_config_accepts_empty_and_minimal():
    validate_config({})
    validate_config({"conditions": []})
    validate_config({"isActive": False, "conditions": []})


def test_validate_config_accepts_valid_document():
    validate_config({
        "isActive": True,
        "conditions": [
            {"field": "brand", "op": "equals", "arg": "Acme", "caseSensitive": False},
            {"field": "image_link", "op": "exists"},
 cares    ],
    })


def test_validate_config_rejects_bad_shapes():
    with pytest.raises(ValueError):
        validate_config({"conditions": "nope"})
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"op": "equals", "arg": "x"}]})  # missing field
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"field": "", "op": "equals", "arg": "x"}]})
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"field": "f", "op": "nope"}]})
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"field": "f", "op": "equals"}]})  # missing arg
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"field": "f", "op": "exists", "arg": "x"}]})  # arg not allowed


# --- FilterPlugin.process ---

def _cfg(conditions, is_active=True):
    return {"isActive": is_active, "conditions": conditions}


def test_process_drops_non_matching_product():
    plugin = FilterPlugin()
    config = _cfg([{"field": "brand", "op": "equals", "arg": "Acme"}])
    assert plugin.process({"brand": "Acme"}, config, {}, _ctx()) == {"brand": "Acme"}
    assert plugin.process({"brand": "Other"}, config, {}, _ctx()) is None


def test_process_inactive_is_passthrough():
    plugin = FilterPlugin()
    config = _cfg([{"field": "brand", "op": "equals", "arg": "Acme"}], is_active=False)
    assert plugin.process({"brand": "Other"}, config, {}, _ctx()) == {"brand": "Other"}


def test_process_empty_conditions_passthrough():
    plugin = FilterPlugin()
    assert plugin.process({"a": 1}, _cfg([]), {}, _ctx()) == {"a": 1}


def test_process_returns_same_dict_never_copies():
    plugin = FilterPlugin()
    product = {"brand": "Acme"}
    out = plugin.process(product, _cfg([]), {}, _ctx())
    assert out is product


def test_process_does_not_mutate_original_product():
    class Ctx:
        client_id = feed_source_id = run_id = 0
        logger = logging.getLogger("test")

    product = {"brand": "Acme"}
    Ctx.original_product = copy.deepcopy(product)
    config = _cfg([{"field": "brand", "op": "equals", "arg": "Acme"}])
    assert FilterPlugin().process(product, config, {}, Ctx()) is product
    assert Ctx.original_product == {"brand": "Acme"}


def test_process_missing_config_keys_defaults():
    plugin = FilterPlugin()
    assert plugin.process({"a": 1}, {}, _ctx().__class__ and _ctx()) == {"a": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `uv run pytest tests/test_filter_plugin.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'plugin'`.

NOTE: the last test `test_process_missing_config_keys_defaults` contains a deliberate oddity (`_ctx().__class__ and _ctx()`) — replace that line with `assert plugin.process({"a": 1}, {}, _ctx()) == {"a": 1}` before running. This is the only correction; everything else is verbatim.

- [ ] **Step 3: Implement plugin.py**

Create `plugins/core/filter/plugin.py`:

```python
"""Filter core plugin — conjunctive scalar condition product filter."""

from __future__ import annotations

from typing import Any

_ALLOWED_OPS = ("equals", "not_equals", "contains", "not_contains", "exists", "empty")
_TEXT_OPS = ("equals", "not_equals", "contains", "not_contains")


class FilterError(ValueError):
    """Invalid filter condition (unknown op, missing field, malformed args)."""


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _texts(value: Any, arg: Any, case_sensitive: bool) -> tuple[str, str]:
    actual, expected = _as_text(value), _as_text(arg)
    if case_sensitive:
        return actual, expected
    return actual.lower(), expected.lower()


def evaluate_condition(condition: dict[str, Any], product: dict[str, Any]) -> bool:
    """Evaluate one condition against a product. Raises FilterError on bad shape."""
    if not isinstance(condition, dict):
        raise FilterError("filter condition must be an object")
    op = condition.get("op")
    if op not in _ALLOWED_OPS:
        raise FilterError(f"unknown filter op {op!r}")
    field = condition.get("field")
    if not isinstance(field, str) or not field:
        raise FilterError(f"filter op {op!r} requires a non-empty field")
    value = product.get(field)

    if op == "exists":
        return value is not None
    if op == "empty":
        return value is None or (isinstance(value, str) and value == "")

    arg = condition.get("arg")
    if arg is None:
        raise FilterError(f"filter op {op!r} requires arg")
    case_sensitive = condition.get("caseSensitive", True)

    if op == "equals":
        actual, expected = _texts(value, arg, case_sensitive)
        return actual == expected
    if op == "not_equals":
        if value is None:
            return True
        actual, expected = _texts(value, arg, case_sensitive)
        return actual != expected
    if op == "contains":
        actual, expected = _texts(value, arg, case_sensitive)
        return expected in actual
    # not_contains
    if value is None:
        return True
    actual, expected = _texts(value, arg, case_sensitive)
    return expected not in actual


def passes_all(conditions: list[dict[str, Any]], product: dict[str, Any]) -> bool:
    """Conjunctive evaluation; empty condition list passes."""
    return all(evaluate_condition(c, product) for c in conditions)


def _validate_condition(condition: Any, index: int) -> None:
    if not isinstance(condition, dict):
        raise ValueError(f"conditions[{index}]: condition must be an object")
    op = condition.get("op")
    if op not in _ALLOWED_OPS:
        raise ValueError(f"conditions[{index}]: unknown filter op {op!r}")
    field = condition.get("field")
    if not isinstance(field, str) or not field:
        raise ValueError(f"conditions[{index}]: op {op!r} requires a non-empty field")
    if op in _TEXT_OPS:
        if condition.get("arg") is None:
            raise ValueError(f"conditions[{index}]: op {op!r} requires arg")
    else:
        if condition.get("arg") is not None:
            raise ValueError(f"conditions[{index}]: op {op!r} does not take arg")


def validate_config(config: Any) -> None:
    """Strict validation of a filter config document. Empty config passes."""
    if config is None:
        return
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    if not config:
        return
    conditions = config.get("conditions")
    if conditions is None:
        return
    if not isinstance(conditions, list):
        raise ValueError("config.conditions must be an array")
    for index, condition in enumerate(conditions):
        _validate_condition(condition, index)


class FilterPlugin:
    """Pipeline module dropping products that fail the conjunctive condition set."""

    def validate_config(self, config: dict[str, Any]) -> None:
        validate_config(config)

    def process(
        self,
        product: dict[str, Any],
        config: dict[str, Any],
        data: dict[str, Any],
        ctx: Any,
    ) -> dict[str, Any] | None:
        conditions = config.get("conditions", []) if isinstance(config, dict) else []
        if not config.get("isActive", True):
            return product
        if passes_all(conditions, product):
            return product
        return None
```

Create empty `plugins/core/filter/__init__.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_filter_plugin.py -q`
Expected: PASS (all ~24 tests).

- [ ] **Step 5: Lint**

Run: `uvx ruff check ../plugins/core/filter/plugin.py tests/test_filter_plugin.py`
Expected: no findings (RUF100 on the noqa line is pre-existing baseline pattern from rules tests — if flagged, keep; it matches the house pattern).

- [ ] **Step 6: Commit**

```bash
git add ../plugins/core/filter/__init__.py ../plugins/core/filter/plugin.py tests/test_filter_plugin.py
git commit -m "feat(filter): conjunctive scalar condition engine"
```

---

### Task 2: Manifest and contract compliance

**Files:**
- Create: `plugins/core/filter/plugin.json`
- Test: `backend/tests/test_filter_contract.py`

**Interfaces:**
- Consumes: `FilterPlugin` from Task 1; `discover()` from `backend/app/plugins/discovery.py`.
- Produces: plugin id `filter`, core=True (auto-enabled), manifest `frontend.component: "component.tsx"` (Task 4's registry depends on this value + plugin id).

- [ ] **Step 1: Write failing contract test**

Create `backend/tests/test_filter_contract.py`:

```python
"""Contract + discovery tests for the filter core plugin (mirrors rules contract test)."""

PLUGINS_DIR = __import__("pathlib").Path(__file__).resolve().parents[2] / "plugins"


def _rules_of(candidates):
    return [c for c in candidates if c.manifest.id == "filter"]


def test_filter_discovered_as_core():
    from app.plugins.discovery import discover

    candidates, rejected = discover(PLUGINS_DIR)
    filters = _rules_of(candidates)
    assert filters and filters[0].core is True


def test_filter_manifest_fields():
    from app.plugins.discovery import discover

    candidates, _ = discover(PLUGINS_DIR)
    filters = _rules_of(candidates)
    assert filters, "filter plugin not discovered"
    manifest = filters[0].manifest
    assert manifest.config_scope == ("global", "client", "feed_source")
    assert manifest.data_scope == ("global", "client", "feed_source")
    frontend = manifest.raw.get("frontend")
    assert frontend and frontend.get("component") == "component.tsx"


def test_filter_passes_contract():
    from app.plugins.contract import contract_violations

    candidates, _ = __import__("app.plugins.discovery", fromlist=["discover"]).discover(PLUGINS_DIR)
    filters = _rules_of(candidates)
    assert filters, "filter plugin not discovered"
    assert contract_violations(filters[0]) == []
```

NOTE: the third test's discovery import is needlessly convoluted (`__import__` form) — simplify to the same import style as the first two tests (`from app.plugins.discovery import discover`) before committing. Behavior identical.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_filter_contract.py -x -q`
Expected: FAIL — `filter plugin not discovered`.

- [ ] **Step 3: Create manifest**

Create `plugins/core/filter/plugin.json`:

```json
{
  "id": "filter",
  "name": "Filter",
  "version": "1.0.0",
  "extension_point": "pipeline_module",
  "entry_point": "plugin:FilterPlugin",
  "config_scope": ["global", "client", "feed_source"],
  "data_scope": ["global", "client", "feed_source"],
  "config_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Filter",
    "properties": {
      "isActive": {"type": "boolean", "title": "Filter active", "default": true},
      "conditions": {
        "type": "array",
        "title": "Conditions",
        "items": {
          "type": "object",
          "properties": {
            "field": {"type": "string", "title": "Field"},
            "op": {"type": "string", "title": "Operator", "enum": ["equals", "not_equals", "contains", "not_contains", "exists", "empty"]},
            "arg": {"type": "string", "title": "Value"},
            "caseSensitive": {"type": "boolean", "title": "Case sensitive", "default": true}
          },
          "required": ["field", "op"]
        }
      }
    }
  },
  "data_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Filter data"
  },
  "frontend": {
    "menu_item": "Filter",
    "icon": "filter",
    "component": "component.tsx"
  }
}
```

- [ ] **Step 4: Run tests to verify they pass + full suite**

Run: `uv run pytest tests/test_filter_contract.py -q` → PASS (3 tests).
Run: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto -q` → PASS (no regressions; filter auto-registers as core alongside rules).

- [ ] **Step 5: Commit**

```bash
git add ../plugins/core/filter/plugin.json tests/test_filter_contract.py
git commit -m "feat(filter): manifest and contract compliance"
```

---

### Task 3: Preview endpoint

**Files:**
- Modify: `plugins/core/filter/plugin.py` (append `register_routes`)
- Test: `backend/tests/test_filter_preview.py`

**Interfaces:**
- Consumes: `passes_all`, `_validate_condition`-equivalent validation, `FilterError` from Task 1; `app.db.engine.get_db_session`, `app.auth.require_user`, `app.models.staging.StagingProduct`, `app.models.feed_source.FeedSource`.
- Produces: `FilterPlugin.register_routes(router: APIRouter) -> None` mounting `POST /preview` — request `{"feed_source_id": int, "conditions": [...]}` → response `{"total": int, "pass": int, "fail": int}`; 404 unknown feed source; 422 invalid conditions (`{"errors": [msg]}`); 401 unauthenticated (inherited via `require_user`).

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_filter_preview.py` (reuses the app-fixture pattern from `test_products_api.py` — copy the `app_factory`/`logged_in_client`/`_setup_feed` helpers from that file verbatim, with these differences: `_setup_feed` gains optional `excluded` flag per product row, and products get `processed_data=None`):

Setup helper shape (adapt `test_products_api.py::_setup_feed`):

```python
async def _setup_feed(factory, client, products):
    """products: list of (product_id, raw_data, status, excluded) tuples."""
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (
        await client.post(
            f"/clients/{created['id']}/feed-sources",
            json={"name": "DE", "source_format": "wide_tsv"},
        )
    ).json()
    async with factory() as session:
        async with session.begin():
            run = IngestionRun(feed_source_id=feed["id"], status="success",
                               started_at=datetime.now(timezone.utc))
            session.add(run)
            await session.flush()
            for pid, raw, status, excluded in products:
                session.add(
                    StagingProduct(
                        feed_source_id=feed["id"], ingestion_run_id=run.id,
                        product_id=pid, content_hash="h", config_hash="c",
                        status=status, raw_data=raw,
                        processed_data=None, excluded=excluded,
                    )
                )
    return feed["id"]
```

Router mounting helper (the plugin router is built by the plugin's `register_routes`; mount it manually to avoid full discovery):

```python
def _mount_filter(app):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins/core/filter"))
    from plugin import FilterPlugin
    router = __import__("fastapi").APIRouter()
    FilterPlugin().register_routes(router)
    app.include_router(router, prefix="/plugins/filter")
```

Mount in each test right after `app, _ = app_factory` (before creating the client).

Tests:

```python
_BASE = {"title": "T", "price": "1.00 EUR", "brand": "Acme"}


async def test_preview_requires_auth(app_factory):
    app, _ = app_factory
    _mount_filter(app)
    anon = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await anon.post("/plugins/filter/preview", json={"feed_source_id": 1, "conditions": []})
    assert resp.status_code == 401


async def test_preview_unknown_feed_source_404(app_factory):
    app, _ = app_factory
    _mount_filter(app)
    client = await logged_in_client(app_factory)
    resp = await client.post(
        "/plugins/filter/preview",
        json={"feed_source_id": 99999, "conditions": []},
    )
    assert resp.status_code == 404


async def test_preview_invalid_conditions_422(app_factory):
    app, factory = app_factory
    _mount_filter(app)
    client = await logged_in_client(app_factory)
    feed_id = await _setup_feed(factory, client, [])
    resp = await client.post(
        "/plugins/filter/preview",
        json={"feed_source_id": feed_id, "conditions": [{"field": "f", "op": "nope"}]},
    )
    assert resp.status_code == 422
    assert "errors" in resp.json()


async def test_preview_counts_pass_fail(app_factory):
    app, factory = app_factory
    _mount_filter(app)
    client = await logged_in_client(app_factory)
    feed_id = await _setup_feed(factory, client, [
        ("a", {"id": "a", **_BASE}, "active", False),
        ("b", {"id": "b", **_BASE, "brand": "Globex"}, "active", False),
        ("c", {"id": "c", **_BASE}, "active", True),   # excluded → not counted
        ("d", {"id": "d", **_BASE}, "removed", False),  # removed → not counted
    ])
    resp = await client.post(
        "/plugins/filter/preview",
        json={"feed_source_id": feed_id, "conditions": [{"field": "brand", "op": "equals", "arg": "Acme"}]},
    )
    body = resp.json()
    assert body == {"total": 2, "pass": 1, "fail": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_filter_preview.py -x -q`
Expected: FAIL — `AttributeError: 'FilterPlugin' object has no attribute 'register_routes'` (or TypeError from `register_routes=None`).

- [ ] **Step 3: Implement register_routes**

First, adjust Task 1's module-level validator: change the three `raise ValueError(...)` in `_validate_condition` to `raise FilterError(...)` (messages unchanged; `FilterError` is a `ValueError` subclass, so Task 1's tests stay green unchanged).

Then append to `plugins/core/filter/plugin.py`:

```python
def register_routes(self, router: Any) -> None:
    """Mount POST /preview — live pass/fail counts against staged products."""
    from fastapi import Depends, HTTPException
    from pydantic import BaseModel, Field
    from sqlalchemy import select

    from app.auth import require_user
    from app.db.engine import get_db_session
    from app.models.feed_source import FeedSource
    from app.models.staging import StagingProduct

    class PreviewRequest(BaseModel):
        feed_source_id: int
        conditions: list[dict[str, Any]] = Field(default_factory=list)

    @router.post("/preview")
    async def preview(
        payload: PreviewRequest,
        _user: str = Depends(require_user),
        db_session: Any = Depends(get_db_session),
    ) -> dict[str, int]:
        for index, condition in enumerate(payload.conditions):
            try:
                _validate_condition(condition, index)
            except FilterError as exc:
                raise HTTPException(
                    status_code=422, detail={"errors": [str(exc)]}
                ) from exc

        session = db_session
        if session is None:
            raise HTTPException(status_code=503, detail="database unavailable")
        async with session.begin():
            if await session.get(FeedSource, payload.feed_source_id) is None:
                raise HTTPException(status_code=404, detail="feed source not found")
            rows = (await session.execute(
                select(StagingProduct.raw_data).where(
                    StagingProduct.feed_source_id == payload.feed_source_id,
                    StagingProduct.status == "active",
                    StagingProduct.excluded.is_(False),
                )
            )).scalars().all()

        total = len(rows)
        passing = sum(
            1 for raw in rows
            if passes_all(payload.conditions, dict(raw) if raw else {})
        )
        return {"total": total, "pass": passing, "fail": total - passing}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_filter_preview.py tests/test_filter_plugin.py -q`
Expected: PASS (all).

Run full suite: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add ../plugins/core/filter/plugin.py tests/test_filter_preview.py
git commit -m "feat(filter): preview endpoint with live pass/fail counts"
```

---

### Task 4: Frontend — FilterUI + i18n + stub

**Files:**
- Create: `plugins/core/filter/frontend/component.tsx` (one-line stub)
- Create: `frontend/src/features/filter/FilterUI.tsx`
- Create: `frontend/public/locales/en/filter.json`
- Create: `frontend/public/locales/de/filter.json`
- Test: `frontend/src/features/filter/__tests__/FilterUI.test.tsx`

**Interfaces:**
- Consumes: preview endpoint from Task 3 (`POST /plugins/filter/preview` body `{feed_source_id, conditions}` → `{total, pass, fail}`); `usePluginConfig`/`useSavePluginConfig`/`useFeedSourceFields` (`frontend/src/api/hooks.ts`); save-flow pattern from `frontend/src/features/rules/RulesUI.tsx` (lastConfigRef rehydration, rulesEqual-style dirty check, useBlocker via data router in tests); PluginScope type.
- Produces: default-export `FilterUI` with props `{ pluginId: string; scope: PluginScope }` (Task 5 registry consumes this); config document `{isActive: boolean, conditions: Condition[]}` where `Condition = {field: string, op: FilterOp, arg?: string, caseSensitive?: boolean}`.

- [ ] **Step 1: Write failing component tests**

Create `frontend/src/features/filter/__tests__/FilterUI.test.tsx`:

```tsx
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { ReactNode } from 'react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import FilterUI from '../../../../../plugins/core/filter/frontend/component';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeAll(async () => {
  await i18n.loadNamespaces(['filter', 'common']);
});

beforeEach(() => {
  vi.restoreAllMocks();
});

function withQueryClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

const savedConfig = {
  isActive: true,
  conditions: [{ field: 'brand', op: 'equals', arg: 'Acme', caseSensitive: true }],
};

function renderUI(handlers?: (url: string, method?: string) => unknown) {
  stubFetch((url, init) => {
    const method = init?.method;
    if (url.startsWith('/plugins/filter/config')) {
      if (method === 'PUT') return jsonResponse({ isActive: true, conditions: [] });
      return jsonResponse(savedConfig);
    }
    if (url.startsWith('/feed-sources/1/fields')) return jsonResponse({ fields: ['brand', 'title', 'price'] });
    if (url.startsWith('/plugins/filter/preview')) return jsonResponse({ total: 308, pass: 137, fail: 171 });
    return handlers?.(url, method) ?? jsonResponse({});
  });
  const router = createMemoryRouter(
    [{ path: '/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId', element: <FilterUI pluginId="filter" scope={{ feedSourceId: 1 }} /> }],
    { initialEntries: ['/clients/1/feeds/1/plugins/filter'] },
  );
  return render(<RouterProvider router={router} />, { wrapper: withQueryClient() });
}

describe('FilterUI', () => {
  it('loads config and renders the condition row', async () => {
    renderUI();
    expect(await screen.findByTestId('filter-editor')).toBeInTheDocument();
    expect(screen.getByTestId('condition-row-0')).toBeInTheDocument();
  });

  it('adds and deletes condition rows', async () => {
    const user = userEvent.setup();
    renderUI();
    await screen.findByTestId('condition-row-0');
    await user.click(screen.getByTestId('condition-add'));
    expect(await screen.findByTestId('condition-row-1')).toBeInTheDocument();
    await user.click(screen.getByTestId('condition-delete-1'));
    expect(screen.queryByTestId('condition-row-1')).not.toBeInTheDocument();
  });

  it('renders the preview count from the preview endpoint', async () => {
    renderUI();
    expect(await screen.findByText(/137 of 308/)).toBeInTheDocument();
  });

  it('save button posts the config', async () => {
    const user = userEvent.setup();
    const puts: Array<{ url: string; body: unknown }> = [];
    stubFetch((url, init) => {
      if (url.startsWith('/plugins/filter/config') && init?.method === 'PUT') {
        puts.push({ url, body: JSON.parse(String(init.body)) });
        return jsonResponse({ isActive: true, conditions: [] });
      }
      if (url.startsWith('/plugins/filter/config')) return jsonResponse(savedConfig);
      if (url.startsWith('/feed-sources/1/fields')) return jsonResponse({ fields: ['brand'] });
      if (url.startsWith('/plugins/filter/preview')) return jsonResponse({ total: 1, pass: 1, fail: 0 });
      return jsonResponse({});
    });
    const router = createMemoryRouter(
      [{ path: '/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId', element: <FilterUI pluginId="filter" scope={{ feedSourceId: 1 }} /> }],
      { initialEntries: ['/clients/1/feeds/1/plugins/filter'] },
    );
    render(<RouterProvider router={router} />, { wrapper: withQueryClient() });
    await screen.findByTestId('condition-row-0');
    await user.click(screen.getByRole('button', { name: /^save$/i }));
    await screen.findByText(/saved/i);
    expect(puts).toHaveLength(1);
    expect(puts[0].body).toEqual(savedConfig);
  });
});
```

NOTE on the last test: the exact save payload equality (`toEqual(savedConfig)`) requires FilterUI's save to serialize conditions verbatim (including `caseSensitive: true`) — implement the save serializer to pass through condition fields as-is (no key reordering beyond JSON key order stability of the object literals). If the dirty-check prevents clicking Save (config untouched → button disabled), first modify something harmless that round-trips identically (e.g. toggle `isActive` off and on) OR relax the assertion to `expect(puts[0].body.conditions).toEqual(savedConfig.conditions)`. Prefer the relaxed assertion if needed — document the choice in the report.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -- src/features/filter/__tests__/FilterUI.test.tsx`
Expected: FAIL — cannot resolve stub import (file doesn't exist).

- [ ] **Step 3: Create i18n files**

`frontend/public/locales/en/filter.json`:

```json
{
  "title": "Filter",
  "active": "Filter active",
  "addCondition": "Add condition",
  "field": "Field",
  "operator": "Operator",
  "value": "Value",
  "caseSensitive": "Case sensitive",
  "incomplete": "Complete all rows to see the preview",
  "previewPass": "{{pass}} of {{total}} products pass",
  "previewError": "Preview failed",
  "saved": "Filter saved",
  "saveFailed": "Failed to save filter",
  "unsavedChanges": "You have unsaved changes. Leave anyway?",
  "ops": {
    "equals": "equals",
    "not_equals": "does not equal",
    "contains": "contains",
    "not_contains": "does not contain",
    "exists": "exists",
    "empty": "is empty"
  }
}
```

`frontend/public/locales/de/filter.json`:

```json
{
  "title": "Filter",
  "active": "Filter aktiv",
  "addCondition": "Bedingung hinzufügen",
  "field": "Feld",
  "operator": "Operator",
  "value": "Wert",
  "caseSensitive": "Groß-/Kleinschreibung beachten",
  "incomplete": "Alle Zeilen ausfüllen, um die Vorschau zu sehen",
  "previewPass": "{{pass}} von {{total}} Produkten bestehen",
  "previewError": "Vorschau fehlgeschlagen",
  "saved": "Filter gespeichert",
  "saveFailed": "Filter speichern fehlgeschlagen",
  "unsavedChanges": "Ungespeicherte Änderungen. Trotzdem verlassen?",
  "ops": {
    "equals": "ist gleich",
    "not_equals": "ist nicht gleich",
    "contains": "enthält",
    "not_contains": "enthält nicht",
    "exists": "existiert",
    "empty": "ist leer"
  }
}
```

Also register the namespace in `frontend/src/i18n/i18next.d.ts` if it enumerates namespaces (add `'filter'` next to `'rules'`).

- [ ] **Step 4: Implement the stub and FilterUI**

Create `plugins/core/filter/frontend/component.tsx` (ONE line, relative-only):

```tsx
export { default } from '../../../../frontend/src/features/filter/FilterUI';
```

Create `frontend/src/features/filter/FilterUI.tsx`:

```tsx
import { ActionIcon, Badge, Button, Group, Paper, Select, Stack, Switch, Text, TextInput } from '@mantine/core';
import { IconPlus, IconTrash } from '@tabler/icons-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useBlocker } from 'react-router';
import { apiPost } from '../../../api/client';
import { useFeedSourceFields, usePluginConfig, useSavePluginConfig, type PluginScope } from '../../api/hooks';
import { notifyApiError, notifySuccess } from '../../app/notifications';

type FilterOp = 'equals' | 'not_equals' | 'contains' | 'not_contains' | 'exists' | 'empty';

type Condition = {
  field: string;
  op: FilterOp;
  arg?: string;
  caseSensitive?: boolean;
};

type FilterConfig = {
  isActive: boolean;
  conditions: Condition[];
};

const OPS: FilterOp[] = ['equals', 'not_equals', 'contains', 'not_contains', 'exists', 'empty'];
const TEXT_OPS: FilterOp[] = ['equals', 'not_equals', 'contains', 'not_contains'];

export type FilterUIProps = { pluginId: string; scope: PluginScope };

function normalizeConfig(value: unknown): FilterConfig {
  if (typeof value !== 'object' || value === null) return { isActive: true, conditions: [] };
  const raw = value as Record<string, unknown>;
  const conditions: Condition[] = [];
  if (Array.isArray(raw.conditions)) {
    for (const entry of raw.conditions) {
      if (typeof entry !== 'object' || entry === null) continue;
      const c = entry as Record<string, unknown>;
      if (typeof c.field !== 'string' || !c.field) continue;
      if (typeof c.op !== 'string' || !OPS.includes(c.op as FilterOp)) continue;
      const condition: Condition = { field: c.field, op: c.op as FilterOp };
      if (typeof c.arg === 'string') condition.arg = c.arg;
      if (typeof c.caseSensitive === 'boolean') condition.caseSensitive = c.caseSensitive;
      conditions.push(condition);
    }
  }
  return { isActive: raw.isActive !== false, conditions };
}

function configsEqual(a: FilterConfig, b: FilterConfig): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export default function FilterUI({ pluginId, scope }: FilterUIProps) {
  const { t } = useTranslation('filter');
  const { t: tCommon } = useTranslation('common');
  const config = usePluginConfig(pluginId, scope);
  const saveConfig = useSavePluginConfig(pluginId, scope);
  const fieldsQuery = useFeedSourceFields(String(scope.feedSourceId ?? ''));
  const fields = useMemo(() => fieldsQuery.data?.fields ?? [], [fieldsQuery.data]);

  const [draft, setDraft] = useState<FilterConfig>({ isActive: true, conditions: [] });
  const lastConfigRef = useRef<unknown>(null);

  useEffect(() => {
    if (config.data !== undefined && config.data !== lastConfigRef.current) {
      lastConfigRef.current = config.data;
      setDraft(normalizeConfig(config.data));
    }
  }, [config.data]);

  const serverDraft = useMemo(
    () => (config.data !== undefined ? normalizeConfig(config.data) : null),
    [config.data],
  );
  const dirty = serverDraft !== null && !configsEqual(draft, serverDraft);

  useBlocker(({ currentLocation, nextLocation }) => {
    if (!dirty) return false;
    if (currentLocation.pathname === nextLocation.pathname) return false;
    return !window.confirm(t('unsavedChanges'));
  });

  const fieldData = fields.map((f) => ({ value: f, label: f }));
  const hasIncomplete = draft.conditions.some(
    (c) => !c.field || (TEXT_OPS.includes(c.op) && (c.arg === undefined || c.arg === '')),
  );

  async function refreshPreview() {
    if (hasIncomplete) return;
    try {
      return await apiPost<{ total: number; pass: number; fail: number }>(
        '/plugins/filter/preview',
        { feed_source_id: scope.feedSourceId, conditions: draft.conditions },
      );
    } catch {
      return null;
    }
  }

  // Preview: debounced refetch on draft change (400ms) via useDebouncedValue-like effect.
  const draftKey = JSON.stringify(draft.conditions);
  const [preview, setPreview] = useState<{ total: number; pass: number; fail: number } | null>(null);
  const [previewTick, setPreviewTick] = useState(0);
  useEffect(() => {
    if (hasIncomplete) {
      setPreview(null);
      return;
    }
    const timer = setTimeout(() => setPreviewTick((n) => n + 1), 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey, hasIncomplete]);
  useEffect(() => {
    if (previewTick === 0) return;
    void refreshPreview().then((result) => setPreview(result));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewTick]);

  async function onSave() {
    const payload: FilterConfig = {
      isActive: draft.isActive,
      conditions: draft.conditions.map(({ field, op, arg, caseSensitive }) =>
        TEXT_OPS.includes(op)
          ? { field, op, arg: arg ?? '', caseSensitive: caseSensitive ?? true }
          : { field, op },
      ),
    };
    try {
      await saveConfig.mutateAsync(payload);
      notifySuccess(t('saved'));
    } catch (error) {
      notifyApiError(error, t('saveFailed'));
    }
  }

  function patchCondition(index: number, patch: Partial<Condition>) {
    setDraft((prev) => ({
      ...prev,
      conditions: prev.conditions.map((c, i) => (i === index ? { ...c, ...patch } : c)),
    }));
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text fw={500} size="lg">{t('title')}</Text>
        <Group>
          <Button variant="default" onClick={() => serverDraft && setDraft(serverDraft)} disabled={!dirty}>
            {tCommon('actions.cancel')}
          </Button>
          <Button onClick={() => void onSave()} loading={saveConfig.isPending} disabled={!dirty}>
            {tCommon('actions.save')}
          </Button>
        </Group>
      </Group>
      <Switch
        label={t('active')}
        checked={draft.isActive}
        onChange={(e) => setDraft((prev) => ({ ...prev, isActive: e.currentTarget.checked }))}
      />
      <Stack gap="xs" data-testid="filter-editor">
        {draft.conditions.map((condition, index) => (
          <Group key={index} gap="xs" wrap="nowrap" align="flex-start" data-testid={`condition-row-${index}`}>
            <Select
              aria-label={t('field')}
              data={fieldData}
              value={condition.field || null}
              onChange={(v) => patchCondition(index, { field: v ?? '' })}
              searchable
              w={180}
            />
            <Select
              aria-label={t('operator')}
              data={OPS.map((op) => ({ value: op, label: t(`ops.${op}`) }))}
              value={condition.op}
              onChange={(v) => patchCondition(index, { op: (v ?? 'equals') as FilterOp })}
              w={180}
            />
            {TEXT_OPS.includes(condition.op) ? (
              <>
                <TextInput
                  aria-label={t('value')}
                  value={condition.arg ?? ''}
                  onChange={(e) => patchCondition(index, { arg: e.currentTarget.value })}
                  w={160}
                />
                <Switch
                  aria-label={t('caseSensitive')}
                  label={t('caseSensitive')}
                  checked={condition.caseSensitive !== false}
                  onChange={(e) => patchCondition(index, { caseSensitive: e.currentTarget.checked })}
                />
              </>
            ) : null}
            <ActionIcon
              variant="subtle"
              color="red"
              aria-label="delete condition"
              onClick={() => setDraft((prev) => ({
                ...prev,
                conditions: prev.conditions.filter((_, i) => i !== index),
              }))}
              data-testid={`condition-delete-${index}`}
            >
              <IconTrash size={14} />
            </ActionIcon>
          </Group>
        ))}
        <Button
          variant="light"
          size="xs"
          leftSection={<IconPlus size={14} />}
          onClick={() => setDraft((prev) => ({
            ...prev,
            conditions: [...prev.conditions, { field: '', op: 'equals', arg: '' }],
          }))}
          data-testid="condition-add"
          w="fit-content"
        >
          {t('addCondition')}
        </Button>
      </Stack>
      <Paper withBorder p="sm">
        {hasIncomplete ? (
          <Text size="sm" c="dimmed">{t('incomplete')}</Text>
        ) : preview ? (
          <Text size="sm">
            {t('previewPass', { pass: preview.pass, total: preview.total })}{' '}
            <Badge size="xs" variant="light" color="gray">{preview.fail}</Badge>
          </Text>
        ) : (
          <Text size="sm" c="dimmed">…</Text>
        )}
      </Paper>
    </Stack>
  );
}
```

Implementation notes (binding):
1. The preview `previewTick === 0` guard skips the initial fetch until the first debounce fires — but the FIRST render with a saved config should show a preview. Fix: initialize `previewTick` to `1` and let the debounce effect increment; the second effect then runs on mount with tick=1. Adjust so exactly one preview request fires on load (assert-able via the stub).
2. Remove both `eslint-disable-next-line` comments only if the repo's lint actually flags them; keep the code honest — `refreshPreview` closes over `draftKey` state via JSON key, acceptable. If the repo has no eslint in the test pipeline, leave the comments out entirely and keep the deps honest (`[draftKey, hasIncomplete]` / `[previewTick]`).
3. `apiPost` — verify the exact export name in `frontend/src/api/client.ts` (grep for `export.*apiPost`); if the function is named differently (e.g. `postJson`), use the real one.
4. `notifySuccess(t('saved'))` after save must also re-sync `lastConfigRef` — the save hook invalidates the config query, fresh data arrives, the identity-guard effect re-hydrates (same mechanism as RulesUI fix `8b3a9ac`) — verify Save→dirty=false transition works in the save test.

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm run test -- src/features/filter/__tests__/FilterUI.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 6: Typecheck + full suite**

Run: `npm run typecheck && npm run test`
Expected: typecheck clean; full suite green (219 existing + 4 new = 223 expected).

- [ ] **Step 7: Commit**

```bash
git add ../plugins/core/filter/frontend/component.tsx src/features/filter/ public/locales/en/filter.json public/locales/de/filter.json ../frontend/src/i18n/i18next.d.ts
git commit -m "feat(filter): FilterUI — condition editor with live preview"
```

---

### Task 5: PluginPage custom-component registry

**Files:**
- Create: `frontend/src/features/plugin/customComponents.ts`
- Modify: `frontend/src/features/plugin/PluginPage.tsx`
- Test: `frontend/src/features/plugin/PluginPage.test.tsx` (extend)

**Interfaces:**
- Consumes: stubs `plugins/core/rules/frontend/component.tsx` and `plugins/core/filter/frontend/component.tsx` (both default-export `{pluginId, scope}` components).
- Produces: `CUSTOM_COMPONENTS: Record<string, ComponentType<{ pluginId: string; scope: PluginScope }>>` keyed by plugin id; PluginPage resolves `manifest.frontend.component` set + `CUSTOM_COMPONENTS[plugin.id]`.

- [ ] **Step 1: Write failing test**

Append to `frontend/src/features/plugin/PluginPage.test.tsx` (reuse `renderWithDataRouter`, `jsonResponse`, `stubFetch`, `plugin` fixture — the harness from Task 7 of the rules cycle):

```tsx
  it('renders the filter custom component for the filter plugin', async () => {
    const filterPlugin = {
      ...plugin,
      id: 'filter',
      name: 'Filter',
      manifest: {
        frontend: { menu_item: 'Filter', icon: 'filter', component: 'component.tsx' },
      },
    };
    stubFetch((url, init) => {
      if (url === '/plugins') return jsonResponse([filterPlugin]);
      if (url.startsWith('/plugins/filter/config')) {
        if (init?.method === 'PUT') return jsonResponse({ isActive: true, conditions: [] });
        return jsonResponse({ isActive: true, conditions: [] });
      }
      if (url.startsWith('/feed-sources/1/fields')) return jsonResponse({ fields: ['brand'] });
      if (url.startsWith('/plugins/filter/preview')) return jsonResponse({ total: 2, pass: 1, fail: 1 });
      return jsonResponse({});
    });
    renderWithDataRouter('/clients/1/feeds/1/plugins/filter');
    expect(await screen.findByTestId('filter-editor')).toBeInTheDocument();
 expect(screen.queryByText(/no configuration schema/i)).not.toBeInTheDocument();
  });
```

NOTE: fix the stray indentation on the `expect(screen.queryByText...` line (it must align with the findByTestId line) before committing. Also confirm the existing rules custom-component test still passes unchanged (the registry refactor must not regress it).

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/features/plugin/PluginPage.test.tsx`
Expected: FAIL — `filter-editor` never appears (PluginPage maps only rules to a custom component; filter falls to the noSchema EmptyState or JsonSchemaForm).

- [ ] **Step 3: Implement the registry**

Create `frontend/src/features/plugin/customComponents.ts`:

```tsx
import type { ComponentType } from 'react';
import type { PluginScope } from '../../api/hooks';
import RulesUI from '../../../../plugins/core/rules/frontend/component';
import FilterUI from '../../../../plugins/core/filter/frontend/component';

export type CustomComponentProps = { pluginId: string; scope: PluginScope };

// Plugin id -> custom UI component. Extend as core plugins gain custom UIs.
// Full build-time discovery (ADR 0002) replaces this static map as follow-up.
export const CUSTOM_COMPONENTS: Record<string, ComponentType<CustomComponentProps>> = {
  rules: RulesUI,
  filter: FilterUI,
};
```

Modify `frontend/src/features/plugin/PluginPage.tsx`:
- Remove the direct `import RulesUI from '../../../../plugins/core/rules/frontend/component';` line.
- Add `import { CUSTOM_COMPONENTS } from './customComponents';`
- Replace the resolution (~:50-51): `const CustomComponent = plugin.manifest?.frontend?.component ? CUSTOM_COMPONENTS[plugin.id] ?? null : null;` — keep the ADR-0002 comment, updated to mention the registry map.
- The schema-less guard (`if (!schema && !CustomComponent)`) and generic-Save hiding stay unchanged.

- [ ] **Step 4: Run tests + typecheck + full suite**

Run: `npm run test -- src/features/plugin/PluginPage.test.tsx` → PASS (all, incl. the existing rules custom-component test and the schema-less test).
Run: `npm run typecheck && npm run test` → PASS (223 + 1 new = 224 expected).

- [ ] **Step 5: Commit**

```bash
git add src/features/plugin/customComponents.ts src/features/plugin/PluginPage.tsx src/features/plugin/PluginPage.test.tsx
git commit -m "feat(plugin-page): custom-component registry map (rules, filter)"
```

---

### Task 6: Documentation + final gate

**Files:**
- Modify: `backend/docs/plugins.md` (core-plugin table Filter row + config-shape subsection)
- Modify: `backend/docs/api.md` (preview endpoint)
- Modify: `frontend/docs/plugin-uis.md` (registry map + second reference component)

**Interfaces:**
- Consumes: everything above.
- Produces: docs matching reality.

- [ ] **Step 1: backend/docs/plugins.md**

Replace the Filter row in "Core Plugins (MVP Rudimentary)":

```markdown
| Filter | `filter` | `config: [global, client, feed_source]`, `data: [global, client, feed_source]` | Single conjunctive condition set (6 scalar ops); drops non-matching products; live preview endpoint; `plugins/core/filter/` |
```

Add after the Rules subsection:

```markdown
### Filter Plugin (`plugins/core/filter/`)

Config document: `{"isActive": true, "conditions": [{field, op, arg?, caseSensitive?}]}`.
- Ops: `equals`, `not_equals`, `contains`, `not_contains` (text, `caseSensitive` default
  `true`), `exists`, `empty`. Conjunctive — all conditions must match.
- Missing field: `equals`/`contains` → false; `not_equals`/`not_contains` → true;
  `exists` → false; `empty` → true.
- `isActive: false` → pass-through; empty `conditions` → pass-all.
- Non-matching product → `process()` returns `None` → dropped (`excluded=true`).
- `POST /plugins/filter/preview` — `{feed_source_id, conditions}` →
  `{total, pass, fail}` against active, non-excluded staged products (canonical
  mapped state; approximation when mutating modules run before the filter).
```

- [ ] **Step 2: backend/docs/api.md**

Add under the plugins section:

```markdown
- `POST /plugins/filter/preview` — live filter preview. Body: `{feed_source_id, conditions}` (same condition shape as the filter config). Response `{total, pass, fail}` counting active, non-excluded staged products. 404 unknown feed source; 422 `{"errors": [...]}` on invalid conditions.
```

- [ ] **Step 3: frontend/docs/plugin-uis.md**

In the First-Party Reference section, extend: custom components resolve through a static registry map (`frontend/src/features/plugin/customComponents.ts`, keyed by plugin id — `rules`, `filter`) instead of a single import; FilterUI is the second consumer (single-pane condition editor + `POST /plugins/filter/preview` live count).

- [ ] **Step 4: Final gate**

Backend (from `backend/`): `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto -q` → PASS (~771).
Frontend (from `frontend/`): `npm run typecheck && npm run test && npm run build` → PASS (~224).

- [ ] **Step 5: Commit docs**

```bash
git add ../backend/docs/plugins.md ../backend/docs/api.md ../frontend/docs/plugin-uis.md
git commit -m "docs: filter core plugin — config shape, preview endpoint, registry map"
```

---

## Self-Review Notes (for executing agents)

- Task 1: the deliberate `_ctx().__class__ and _ctx()` oddity in the last test must be replaced with the clean call (instruction in Step 2).
- Task 3: do NOT commit the `_preview_router_routes` placeholder sketch — only the real `register_routes` (instruction inline).
- Task 3: `_validate_condition` raise type changes `ValueError` → `FilterError` (a ValueError subclass) — existing Task 1 tests must stay green unchanged.
- Task 4: follow the binding implementation notes 1–4 (preview initial fetch, eslint comments, apiPost export name, lastConfigRef re-sync).
- Task 5: fix the stray indentation in the new test before committing; registry refactor must keep both existing rules PluginPage tests green.
- All commits from repo root or respective subdirs as written; never commit `.env`, secrets, or `__pycache__`.
