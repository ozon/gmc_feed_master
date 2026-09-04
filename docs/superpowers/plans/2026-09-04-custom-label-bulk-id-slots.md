# Custom Label Bulk-ID Slots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `custom_labels` core plugin — ordered bulk-ID slot rules that set `custom_label_0`..`custom_label_4` from dynamic templates — plus the `prepare_run` contract hook it needs.

**Architecture:** New plugin under `plugins/core/custom_labels/` following the `core/rules` + `core/filter` pattern: a **single self-contained `plugin.py`** (the loader imports plugin modules standalone via `spec_from_file_location("gmc_plugin_<id>", ...)` — no package-relative imports), a `plugin.json` manifest, and a frontend stub. Slot templates = plugin config (`config_scope: ["global","client"]`); bulk-ID lists = plugin data (`data_scope: ["client","feed_source"]`, per-key merged by rule id). Run-scoped preprocessing (ID frozensets, compiled templates) happens in a new optional `prepare_run(config, data, ctx) -> state` contract hook called once per plugin instance per run; `process()` receives the state per product. Spec: `docs/superpowers/specs/2026-09-04-custom-label-bulk-id-slots-design.md`.

**Tech Stack:** Python 3.10+, pytest + pytest-asyncio (strict mode — decorate async tests individually; `-n auto`); React 19 + TypeScript + Mantine + TanStack Query + dnd-kit (`@dnd-kit/core` 6.3.1, `@dnd-kit/sortable` 10.0.0) + vitest.

## Global Constraints

- Backend commands run from `backend/`: `uv run pytest -n auto` (integration tests need `TEST_DATABASE_URL`), `uv run ruff check .`, `uv run mypy .`
- Frontend commands run from `frontend/`: `npm run test`, `npm run typecheck`, `npm run build`
- `process()` must never mutate `original_product` (read-only in `RunContext`)
- No new backend/frontend dependencies (in particular: no `@dnd-kit/modifiers` — it is not installed; skip `restrictToVerticalAxis`)
- No DB migrations — plugin config/data reuse existing JSONB tables
- Plugin `plugin.py` must be a single standalone-importable file (no relative imports, no sibling-module imports)
- Docs: any behavior/API change updates `backend/docs/*.md` / `frontend/docs/*.md` **in the same commit**
- i18n: new namespace requires BOTH `frontend/public/locales/en/customLabels.json` AND `frontend/public/locales/de/customLabels.json` (auto-loads via HttpBackend — no registration in `src/i18n/index.ts`)
- Do NOT touch `gmc-feed-engine-spec.md` — the §5.9 Labelizer replacement lands with spec v7 (flagged in design §8)
- Registry facts verified in this repo (2026-09-04): `id`, `brand`, `item_group_id`, `title`, `price` are SCALAR attributes; `sku` and `offer_id` do NOT exist — that is exactly why match fields must be validated as registry paths

---

### Task 1: `prepare_run` contract hook

**Files:**
- Modify: `backend/app/plugins/runtime.py`
- Modify: `backend/app/pipeline/steps.py` (module imports + `PluginStep.execute`, ~lines 200-279)
- Modify: `backend/app/plugins/contract.py`
- Modify: `backend/tests/test_plugin_contract.py`
- Modify: `backend/tests/test_pipeline_steps.py`
- Modify: `backend/docs/plugins.md`, `backend/docs/architecture.md`

**Interfaces:**
- Consumes: existing `RunContext` (`backend/app/plugins/runtime.py`), `PluginStep.execute` product loop.
- Produces: `RunContext.original_product: dict[str, Any] | None = None`; optional `prepare_run(self, config, data, ctx) -> Any` on plugin classes; `PluginStep` calls it once per instance per run and passes `state=<return>` to `process()` **only when** the plugin's `process` signature declares a `state` parameter.

- [ ] **Step 1: Write the failing contract tests**

Append to `backend/tests/test_plugin_contract.py` (file already imports `contract_violations` and defines `_make_candidate`):

```python
class TestPrepareRunContract:
    def test_prepare_run_returning_state_passes(self, tmp_path):
        code = """
class UpperPlugin:
    def validate_config(self, config):
        pass
    def process(self, product, config, data, ctx, state=None):
        return product
    def prepare_run(self, config, data, ctx):
        return {"prepared": True}
"""
        candidate = _make_candidate(tmp_path, code=code)
        assert contract_violations(candidate) == []

    def test_prepare_run_raising_returns_violation(self, tmp_path):
        code = """
class UpperPlugin:
    def validate_config(self, config):
        pass
    def process(self, product, config, data, ctx):
        return product
    def prepare_run(self, config, data, ctx):
        raise RuntimeError("boom")
"""
        candidate = _make_candidate(tmp_path, code=code)
        violations = contract_violations(candidate)
        assert any("prepare_run" in v.lower() for v in violations)
```

- [ ] **Step 2: Write the failing PluginStep wiring tests**

Append to `backend/tests/test_pipeline_steps.py`. The file currently contains only **sync** tests, so use per-test `@pytest.mark.asyncio` decorators — do NOT add a module-level `pytestmark`. Add to the file's imports (only the ones not already present): `logging`, `import pytest`, `from app.pipeline.steps import PluginStep, RunState, StepContext`, `from app.plugins.runtime import RunContext` (if not already imported).

```python
class _StatefulPlugin:
    def validate_config(self, config):
        pass

    def prepare_run(self, config, data, ctx):
        return {"suffix": str((config or {}).get("suffix", ""))}

    def process(self, product, config, data, ctx, state=None):
        out = dict(product)
        out["title"] = str(product.get("title", "")) + state["suffix"]
        return out


class _LegacyPlugin:
    def validate_config(self, config):
        pass

    def process(self, product, config, data, ctx):
        return dict(product)


@pytest.mark.asyncio
async def test_plugin_step_calls_prepare_run_once_and_passes_state(monkeypatch):
    async def _noop_outcomes(*args, **kwargs):
        return None

    monkeypatch.setattr("app.pipeline.steps.apply_plugin_outcomes", _noop_outcomes)

    step = PluginStep({"stateful": _StatefulPlugin(), "legacy": _LegacyPlugin()})
    run_state = RunState(
        products=[{"id": "p1", "title": "T"}],
        config_bundle={"instances": [
            {"plugin": "legacy", "resolved_config": {}, "resolved_data": {}},
            {"plugin": "stateful", "resolved_config": {"suffix": "-X"}, "resolved_data": {}},
        ]},
        product_pks={},
    )
    ctx = StepContext(
        feed_source_id=1,
        session_factory=None,
        logger=logging.getLogger("test"),
        run_state=run_state,
    )

    result = await step.execute(ctx)

    assert result.processed_count == 1
    assert run_state.products[0]["title"] == "T-X"


@pytest.mark.asyncio
async def test_plugin_step_legacy_plugins_called_without_state(monkeypatch):
    async def _noop_outcomes(*args, **kwargs):
        return None

    monkeypatch.setattr("app.pipeline.steps.apply_plugin_outcomes", _noop_outcomes)

    seen_kwargs: dict[str, object] = {}

    class _Recorder:
        def validate_config(self, config):
            pass

        def process(self, product, config, data, ctx):
            seen_kwargs["keys"] = list(locals().keys())
            return dict(product)

    step = PluginStep({"rec": _Recorder()})
    run_state = RunState(
        products=[{"id": "p1"}],
        config_bundle={"instances": [{"plugin": "rec", "resolved_config": {}, "resolved_data": {}}]},
        product_pks={},
    )
    ctx = StepContext(
        feed_source_id=1,
        session_factory=None,
        logger=logging.getLogger("test"),
        run_state=run_state,
    )

    result = await step.execute(ctx)

    assert result.processed_count == 1
    assert "state" not in seen_kwargs["keys"]
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run (two separate commands — pytest takes one `-k`):
```bash
cd backend && uv run pytest tests/test_plugin_contract.py -k PrepareRun -v
cd backend && uv run pytest tests/test_pipeline_steps.py -k "prepare_run or legacy_plugins" -v
```
Expected: contract tests FAIL (`prepare_run` raising is not reported as a violation yet); wiring tests FAIL (`state` never passed — `TypeError` on `state["suffix"]` marks the product errored, `title` stays `"T"`).

- [ ] **Step 4: Make `RunContext.original_product` optional**

In `backend/app/plugins/runtime.py`:

```python
@dataclass(frozen=True)
class RunContext:
    client_id: int
    feed_source_id: int
    run_id: int
    logger: logging.Logger
    original_product: dict[str, Any] | None = None
```

Existing call sites keep working (positional/keyword).

- [ ] **Step 5: Wire `prepare_run` into `PluginStep.execute`**

In `backend/app/pipeline/steps.py`:

(a) Add `import inspect` to the module-level imports (next to `import logging`).

(b) In `PluginStep.execute`, directly after the `processed = dropped = errored = 0` line and **before** `for product in ctx.run_state.products:`, insert:

```python
        # prepare_run: once per plugin instance per run (run-scoped state).
        run_states: dict[str, Any] = {}
        accepts_state: dict[str, bool] = {}
        for instance in bundle.get("instances", []):
            plugin_obj = self._registry.get(instance["plugin"])
            if plugin_obj is None:
                continue
            accepts_state[instance["plugin"]] = (
                "state" in inspect.signature(plugin_obj.process).parameters
            )
            prepare = getattr(plugin_obj, "prepare_run", None)
            if callable(prepare):
                rctx = RunContext(
                    client_id=ctx.run_state.client_id or 0,
                    feed_source_id=ctx.feed_source_id,
                    run_id=ctx.ingestion_run_id,
                    logger=ctx.logger,
                )
                run_states[instance["plugin"]] = prepare(
                    instance["resolved_config"], instance["resolved_data"], rctx
                )
```

(c) Replace the single `result = plugin_obj.process(...)` call inside the product-loop `try:` with:

```python
                    if accepts_state.get(instance["plugin"]):
                        result = plugin_obj.process(
                            current,
                            instance["resolved_config"],
                            instance["resolved_data"],
                            rctx,
                            state=run_states.get(instance["plugin"]),
                        )
                    else:
                        result = plugin_obj.process(
                            current,
                            instance["resolved_config"],
                            instance["resolved_data"],
                            rctx,
                        )
```

Everything else in `execute` (drop/error handling, outcomes, statistics) stays unchanged.

- [ ] **Step 6: Add the contract-checker rule**

In `backend/app/plugins/contract.py`, add after `_check_validate_config`:

```python
def _check_prepare_run(candidate: Candidate) -> list[str]:
    prepare = getattr(candidate.instance, "prepare_run", None)
    if prepare is None:
        return []
    rctx = RunContext(
        client_id=0,
        feed_source_id=0,
        run_id=0,
        logger=logging.getLogger("contract"),
    )
    try:
        prepare({}, {}, rctx)
    except Exception as exc:
        return [f"prepare_run() raised: {exc}"]
    return []
```

In `contract_violations` (bottom of file), add next to the other `violations.extend(...)` calls:

```python
    violations.extend(_check_prepare_run(candidate))
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_plugin_contract.py tests/test_pipeline_steps.py -v`
Expected: PASS — all, including the pre-existing contract tests (legacy plugins unaffected).

- [ ] **Step 8: Update docs (same commit)**

In `backend/docs/plugins.md`, runtime-contract section, add:

> **`prepare_run(config, data, ctx) -> state`** (optional): called once per plugin instance per pipeline run, before the first product. Plugins may return any run-scoped state (parsed ID sets, compiled templates). The state is passed to every `process(product, config, data, ctx, state=...)` call of that instance for the run, but only if `process` declares a `state` parameter. Plugins without `prepare_run` are unaffected. Use this instead of caching per-run data on `self` — plugin instances are singletons and runs of different feed sources execute concurrently.

In `backend/docs/architecture.md`, plugin/pipeline section, add one line: "`PluginStep` calls optional `prepare_run` once per plugin instance per run and passes the returned state to `process`."

- [ ] **Step 9: Lint, typecheck, commit**

Run: `cd backend && uv run ruff check . && uv run mypy .`
Expected: clean.

```bash
git add backend/app/plugins/runtime.py backend/app/pipeline/steps.py backend/app/plugins/contract.py backend/tests/test_plugin_contract.py backend/tests/test_pipeline_steps.py backend/docs/plugins.md backend/docs/architecture.md
git commit -m "feat(plugins): optional prepare_run contract hook for run-scoped plugin state"
```

---

### Task 2: custom_labels plugin primitives (pure functions in `plugin.py`)

**Files:**
- Create: `plugins/core/custom_labels/__init__.py` (empty, mirrors `core/rules`)
- Create: `plugins/core/custom_labels/plugin.py` (primitives only — class and validate_config come in Task 3)
- Create: `backend/tests/test_custom_labels_plugin.py` (primitive tests; extended in Task 3)

**Interfaces (Produced — exact, used by Task 3):**
- `parse_id_list(raw: str | None) -> frozenset[str]` — split on `\n`/`,`, strip, drop empties, dedupe.
- `compile_template(template: str) -> tuple[tuple[str, str], ...]` — `("lit", text)` / `("tok", path)` segments.
- `resolve_path(product: dict, path: str) -> list[str]` — registry-path resolution (semantics in the docstring below).
- `render_template(segments, product) -> str | None` — `None` when any token resolves empty.
- `matches(product: dict, match_field: str, ids: frozenset[str]) -> bool` — any-element membership.

Plugin tests import the module the collision-safe way the filter tests use (`backend/tests/test_filter_plugin.py` lines 11-24) — `spec_from_file_location` with a unique module name. NEVER `sys.path.insert` + `from plugin import` (the rules test file does that, but two plugins doing it in one pytest worker collide on the module name `plugin`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_custom_labels_plugin.py`:

```python
"""Tests for the custom_labels plugin (primitives, validation, process semantics)."""

import importlib.util
import logging
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "custom_labels_plugin",
    Path(__file__).resolve().parents[2] / "plugins/core/custom_labels/plugin.py",
)
assert _spec is not None and _spec.loader is not None
_plugin = importlib.util.module_from_spec(_spec)
sys.modules["custom_labels_plugin"] = _plugin
_spec.loader.exec_module(_plugin)

compile_template = _plugin.compile_template
matches = _plugin.matches
parse_id_list = _plugin.parse_id_list
render_template = _plugin.render_template
resolve_path = _plugin.resolve_path


class TestParseIdList:
    def test_split_on_newlines_and_commas(self):
        assert parse_id_list("a,b\n c ,d\n") == frozenset({"a", "b", "c", "d"})

    def test_dedupes_and_drops_empty(self):
        assert parse_id_list("a\na\n\n, ,b") == frozenset({"a", "b"})

    def test_none_and_empty(self):
        assert parse_id_list(None) == frozenset()
        assert parse_id_list("  \n,") == frozenset()


class TestCompileTemplate:
    def test_static_only(self):
        assert compile_template("Mid Funnel") == (("lit", "Mid Funnel"),)

    def test_mixed(self):
        assert compile_template("{brand} - Mid Funnel") == (
            ("tok", "brand"),
            ("lit", " - Mid Funnel"),
        )

    def test_adjacent_tokens_and_trailing_literal(self):
        assert compile_template("{a}{b}!") == (
            ("tok", "a"),
            ("tok", "b"),
            ("lit", "!"),
        )

    def test_token_with_subfield_path(self):
        assert compile_template("under {price.value}") == (
            ("lit", "under "),
            ("tok", "price.value"),
        )


class TestResolvePath:
    def test_scalar(self):
        assert resolve_path({"id": "x1"}, "id") == ["x1"]

    def test_scalar_empty_is_empty(self):
        assert resolve_path({"id": ""}, "id") == []

    def test_missing_head(self):
        assert resolve_path({}, "id") == []

    def test_repeated_scalar_each_element(self):
        assert resolve_path({"gtin": ["a", "", "b"]}, "gtin") == ["a", "b"]

    def test_structured_subfield(self):
        assert resolve_path({"price": {"value": "9.99"}}, "price.value") == ["9.99"]

    def test_repeated_structured_requires_single_element(self):
        assert resolve_path({"p": [{"value": "1"}]}, "p.value") == ["1"]
        assert resolve_path({"p": [{"value": "1"}, {"value": "2"}]}, "p.value") == []

    def test_missing_subfield(self):
        assert resolve_path({"price": {}}, "price.value") == []
        assert resolve_path({"price": {"other": "x"}}, "price.value") == []

    def test_non_string_scalar_coerced(self):
        assert resolve_path({"id": 42}, "id") == ["42"]


class TestRenderTemplate:
    def test_static(self):
        assert render_template(compile_template("Sale"), {"id": "x"}) == "Sale"

    def test_tokens_substituted(self):
        assert render_template(compile_template("{brand} - Mid"), {"brand": "Acme"}) == "Acme - Mid"

    def test_empty_token_returns_none(self):
        assert render_template(compile_template("{brand} - Mid"), {"brand": ""}) is None
        assert render_template(compile_template("{brand} - Mid"), {}) is None


class TestMatches:
    def test_hit_and_miss(self):
        assert matches({"id": "a"}, "id", frozenset({"a", "b"})) is True
        assert matches({"id": "z"}, "id", frozenset({"a"})) is False
        assert matches({}, "id", frozenset({"a"})) is False

    def test_repeated_scalar_any_element(self):
        assert matches({"id": ["x", "a"]}, "id", frozenset({"a"})) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_custom_labels_plugin.py -v`
Expected: FAIL — `plugin.py` does not exist (module load assertion fails).

- [ ] **Step 3: Create the package and `plugin.py` primitives**

Create empty `plugins/core/custom_labels/__init__.py`.

Create `plugins/core/custom_labels/plugin.py`:

```python
"""Custom Labels core plugin — bulk-ID slot rules with dynamic value templates."""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Pure primitives
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\{([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)?)\}")
_SEPARATOR_RE = re.compile(r"[\n,]+")

_TARGET_SLOTS = tuple(f"custom_label_{i}" for i in range(5))


def parse_id_list(raw: str | None) -> frozenset[str]:
    """Split on newlines/commas, trim, drop empties, dedupe."""
    if not raw:
        return frozenset()
    return frozenset(part for part in (p.strip() for p in _SEPARATOR_RE.split(raw)) if part)


def compile_template(template: str) -> tuple[tuple[str, str], ...]:
    """Compile a template into ("lit", text) / ("tok", path) segments."""
    segments: list[tuple[str, str]] = []
    pos = 0
    for match in _TOKEN_RE.finditer(template):
        if match.start() > pos:
            segments.append(("lit", template[pos : match.start()]))
        segments.append(("tok", match.group(1)))
        pos = match.end()
    if pos < len(template):
        segments.append(("lit", template[pos:]))
    return tuple(segments)


def resolve_path(product: dict[str, Any], path: str) -> list[str]:
    """Resolve a registry attribute path to candidate string values.

    Path shapes and semantics (spec §2.1):
    - ``attr`` on scalar -> [value] (empty string -> no candidates)
    - ``attr`` on repeated_scalar -> every non-empty element
    - ``attr.subfield`` on structured -> [value]
    - ``attr.subfield`` on repeated_structured -> [value] only when exactly
      one element exists, else no candidates (ambiguous -> treated as empty)
    """
    head, _, sub = path.partition(".")
    value = product.get(head)
    if value is None:
        return []
    if sub:
        if isinstance(value, dict):
            item = value.get(sub)
            return [str(item)] if item not in (None, "") else []
        if isinstance(value, list):
            if len(value) != 1 or not isinstance(value[0], dict):
                return []
            item = value[0].get(sub)
            return [str(item)] if item not in (None, "") else []
        return []
    if isinstance(value, str):
        return [value] if value != "" else []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def render_template(
    segments: tuple[tuple[str, str], ...], product: dict[str, Any]
) -> str | None:
    """Render compiled segments; None when any token resolves empty (token skip)."""
    parts: list[str] = []
    for kind, text in segments:
        if kind == "lit":
            parts.append(text)
            continue
        values = resolve_path(product, text)
        if not values:
            return None
        parts.append(values[0])
    return "".join(parts)


def matches(product: dict[str, Any], match_field: str, ids: frozenset[str]) -> bool:
    """True when any candidate value of `match_field` is in `ids`."""
    return any(value in ids for value in resolve_path(product, match_field))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_custom_labels_plugin.py -v`
Expected: PASS (primitive tests only at this point).

- [ ] **Step 5: Commit**

```bash
git add plugins/core/custom_labels/__init__.py plugins/core/custom_labels/plugin.py backend/tests/test_custom_labels_plugin.py
git commit -m "feat(custom-labels): ID-list parser, template compiler, registry-path resolver"
```

---

### Task 3: custom_labels plugin class, validation, manifest

**Files:**
- Modify: `plugins/core/custom_labels/plugin.py` (append validate_config + class)
- Create: `plugins/core/custom_labels/plugin.json`
- Modify: `backend/tests/test_custom_labels_plugin.py` (append validation + process tests)
- Modify: `backend/docs/plugins.md` (core plugin list, same commit)

**Interfaces:**
- Consumes: Task 2 primitives (same module, so plain names — no import needed); `registry.loader.load_registry` imported **lazily inside** `_registry_document()` so tests can monkeypatch `registry.loader.load_registry`.
- Produces: `CustomLabelsPlugin` with `validate_config(config)`, `prepare_run(config, data, ctx) -> dict`, `process(product, config, data, ctx, state=None) -> dict`. State shape: `{"rules": [{"id": str, "targetSlot": str, "matchField": str, "ids": frozenset[str], "template": tuple, "fallback": tuple}, ...]}`.

- [ ] **Step 1: Append the failing tests**

Append to `backend/tests/test_custom_labels_plugin.py` (imports `pytest` needs adding at top; also `import copy` for the original_product test):

```python
import pytest  # noqa: F401  (add at top of file with the other imports)

CustomLabelsPlugin = _plugin.CustomLabelsPlugin
validate_config_fn = None  # bound via class in Task 3; tests call the method

from registry.model import (  # noqa: E402
    AttributeKind,
    ExportStatus,
    FeedDomain,
    RegistryAttribute,
    RegistryDocument,
    RequirementStatus,
    SubField,
)


def _registry():
    def attr(name, kind=AttributeKind.SCALAR, fields=()):
        return RegistryAttribute(
            name=name, kind=kind, type="string",
            required=RequirementStatus.OPTIONAL,
            domain=FeedDomain.PRIMARY,
            export_status=ExportStatus.EXPORTABLE,
            fields=fields,
        )

    return RegistryDocument(attributes={
        "id": attr("id"),
        "brand": attr("brand"),
        "item_group_id": attr("item_group_id"),
        "price": attr("price", AttributeKind.STRUCTURED,
                      (SubField("value", "String", RequirementStatus.REQUIRED),)),
    })


CONFIG = {
    "slotRules": [
        {
            "id": "r1", "name": "Mid Funnel", "isActive": True,
            "targetSlot": "custom_label_1", "matchField": "id",
            "valueTemplate": "{brand} - Mid Funnel",
        },
        {
            "id": "r2", "name": "Rising", "isActive": True,
            "targetSlot": "custom_label_1", "matchField": "item_group_id",
            "valueTemplate": "Rising {brand}",
        },
        {
            "id": "r3", "name": "Static", "isActive": True,
            "targetSlot": "custom_label_0", "matchField": "id",
            "valueTemplate": "Static Sale",
            "fallbackTemplate": "EverythingElse",
        },
    ]
}
DATA = {"slotIds": {"r1": "a, b\nb\nc", "r2": "g1", "r3": "s1"}}


def _ctx():
    from app.plugins.runtime import RunContext

    return RunContext(client_id=1, feed_source_id=1, run_id=1, logger=logging.getLogger("t"))


@pytest.fixture()
def plugin():
    return CustomLabelsPlugin()


def _state(plugin, config=CONFIG, data=DATA):
    return plugin.prepare_run(config, data, _ctx())


# --- validation -------------------------------------------------------------


class TestValidateConfig:
    def test_valid_config_passes(self, plugin, monkeypatch):
        monkeypatch.setattr("registry.loader.load_registry", _registry)
        plugin.validate_config(CONFIG)

    def test_empty_config_passes(self, plugin):
        plugin.validate_config({})
        plugin.validate_config(None)

    def test_rejects_unknown_target_slot(self, plugin):
        bad = {"slotRules": [{**CONFIG["slotRules"][0], "targetSlot": "custom_label_9"}]}
        with pytest.raises(ValueError, match="targetSlot"):
            plugin.validate_config(bad)

    def test_rejects_empty_match_field_and_template(self, plugin):
        with pytest.raises(ValueError, match="matchField"):
            plugin.validate_config({"slotRules": [{**CONFIG["slotRules"][0], "matchField": ""}]})
        with pytest.raises(ValueError, match="valueTemplate"):
            plugin.validate_config({"slotRules": [{**CONFIG["slotRules"][0], "valueTemplate": ""}]})

    def test_rejects_non_registry_match_field(self, plugin, monkeypatch):
        monkeypatch.setattr("registry.loader.load_registry", _registry)
        bad = {"slotRules": [{**CONFIG["slotRules"][0], "matchField": "sku"}]}
        with pytest.raises(ValueError, match="unknown registry attribute"):
            plugin.validate_config(bad)

    def test_rejects_unknown_token_path(self, plugin, monkeypatch):
        monkeypatch.setattr("registry.loader.load_registry", _registry)
        bad = {"slotRules": [{**CONFIG["slotRules"][0], "valueTemplate": "{nope} x"}]}
        with pytest.raises(ValueError, match="unknown registry attribute"):
            plugin.validate_config(bad)

    def test_rejects_unknown_subfield_token(self, plugin, monkeypatch):
        monkeypatch.setattr("registry.loader.load_registry", _registry)
        bad = {"slotRules": [{**CONFIG["slotRules"][0], "valueTemplate": "{price.nope}"}]}
        with pytest.raises(ValueError, match="unknown subfield"):
            plugin.validate_config(bad)

    def test_rejects_duplicate_ids(self, plugin):
        dup = {"slotRules": [CONFIG["slotRules"][0], dict(CONFIG["slotRules"][0])]}
        with pytest.raises(ValueError, match="duplicate"):
            plugin.validate_config(dup)

    def test_rejects_second_fallback_on_same_slot(self, plugin):
        second = {**CONFIG["slotRules"][1], "fallbackTemplate": "Other"}
        with pytest.raises(ValueError, match="fallback"):
            plugin.validate_config({"slotRules": [CONFIG["slotRules"][0], second]})


# --- process semantics -------------------------------------------------------


class TestProcess:
    def test_first_match_wins_per_slot_and_slots_are_independent(self, plugin):
        state = _state(plugin)
        product = {"id": "a", "item_group_id": "g1", "brand": "Acme"}
        out = plugin.process(product, CONFIG, DATA, _ctx(), state=state)
        assert out["custom_label_1"] == "Acme - Mid Funnel"  # r1 beats r2 (priority)
        assert "custom_label_0" not in out  # r3's IDs don't contain "a"

    def test_evaluation_continues_across_slots(self, plugin):
        state = _state(plugin)
        out = plugin.process({"id": "s1", "brand": "B"}, CONFIG, DATA, _ctx(), state=state)
        assert out["custom_label_0"] == "Static Sale"
        assert "custom_label_1" not in out

    def test_empty_token_skips_all_dynamic_rules_for_that_slot(self, plugin):
        state = _state(plugin)
        # "a" is in r1's IDs and "g1" in r2's, but brand empty -> both skipped
        out = plugin.process(
            {"id": "a", "item_group_id": "g1", "brand": ""}, CONFIG, DATA, _ctx(), state=state,
        )
        assert "custom_label_1" not in out

    def test_matched_but_token_empty_falls_to_lower_priority_static_rule(self, plugin):
        config = {"slotRules": [
            {"id": "r1", "name": "Dyn", "isActive": True, "targetSlot": "custom_label_0",
             "matchField": "id", "valueTemplate": "{brand} X"},
            {"id": "r2", "name": "Stat", "isActive": True, "targetSlot": "custom_label_0",
             "matchField": "id", "valueTemplate": "Static"},
        ]}
        data = {"slotIds": {"r1": "a", "r2": "a"}}
        state = _state(plugin, config, data)
        out = plugin.process({"id": "a", "brand": ""}, config, data, _ctx(), state=state)
        assert out["custom_label_0"] == "Static"

    def test_fallback_used_when_no_rule_matches(self, plugin):
        state = _state(plugin)
        out = plugin.process({"id": "zzz", "brand": "B"}, CONFIG, DATA, _ctx(), state=state)
        assert out["custom_label_0"] == "EverythingElse"
        assert "custom_label_1" not in out  # no fallback declared on custom_label_1

    def test_fallback_with_empty_token_leaves_label_empty(self, plugin):
        config = {"slotRules": [
            {"id": "r1", "name": "Fb", "isActive": True, "targetSlot": "custom_label_0",
             "matchField": "id", "valueTemplate": "X",
             "fallbackTemplate": "{brand} rest"},
        ]}
        state = _state(plugin, config, {"slotIds": {"r1": "nope"}})
        out = plugin.process({"id": "zzz", "brand": ""}, config, {}, _ctx(), state=state)
        assert "custom_label_0" not in out

    def test_inactive_rules_skipped(self, plugin):
        config = {"slotRules": [{**CONFIG["slotRules"][0], "isActive": False}]}
        state = _state(plugin, config, DATA)
        out = plugin.process({"id": "a", "brand": "B"}, config, DATA, _ctx(), state=state)
        assert "custom_label_1" not in out

    def test_without_state_rebuilds_from_config_and_data(self, plugin):
        # process must still work when called without state (defensive path)
        out = plugin.process({"id": "a", "brand": "Acme"}, CONFIG, DATA, _ctx())
        assert out["custom_label_1"] == "Acme - Mid Funnel"

    def test_original_product_not_mutated(self, plugin):
        state = _state(plugin)
        product = {"id": "a", "brand": "B"}
        plugin.process(product, CONFIG, DATA, _ctx(), state=state)
        assert product == {"id": "a", "brand": "B"}

    def test_structured_subfield_token(self, plugin):
        config = {"slotRules": [
            {"id": "r1", "name": "Price", "isActive": True, "targetSlot": "custom_label_2",
             "matchField": "id", "valueTemplate": "under {price.value}"},
        ]}
        data = {"slotIds": {"r1": "a"}}
        state = _state(plugin, config, data)
        out = plugin.process(
            {"id": "a", "price": {"value": "9.99"}}, config, data, _ctx(), state=state,
        )
        assert out["custom_label_2"] == "under 9.99"
```

Note on `test_without_state_rebuilds_from_config_and_data`: implement the defensive path by making `process` build the state itself when `state is None` (see Step 3) — this also keeps the plugin contract-checker working (it calls `process(product, {}, {}, rctx)` with no state).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_custom_labels_plugin.py -v`
Expected: FAIL — `CustomLabelsPlugin` missing (`AttributeError` on `_plugin.CustomLabelsPlugin`).

- [ ] **Step 3: Append validate_config + class to `plugin.py`**

Append to `plugins/core/custom_labels/plugin.py`:

```python
# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def _registry_document():
    # Imported lazily so tests can monkeypatch registry.loader.load_registry.
    from registry.loader import load_registry

    return load_registry()


def _validate_registry_path(path: str, registry: Any, where: str) -> None:
    head, _, sub = path.partition(".")
    attribute = registry.attributes.get(head)
    if attribute is None:
        raise ValueError(f"{where}: unknown registry attribute {head!r}")
    if sub:
        field_names = {field.name for field in attribute.fields}
        if sub not in field_names:
            raise ValueError(f"{where}: unknown subfield {sub!r} on {head!r}")


def _validate_template(template: str, where: str) -> None:
    registry = _registry_document()
    for kind, token_path in compile_template(template):
        if kind == "tok":
            _validate_registry_path(token_path, registry, f"{where} token {{{token_path}}}")


def validate_config(config: Any) -> None:
    """Strict validation of a custom_labels config document. Empty config passes."""
    if not isinstance(config, dict) or not config:
        return
    rules = config.get("slotRules")
    if rules is None:
        return
    if not isinstance(rules, list):
        raise ValueError("config.slotRules must be an array")
    seen_ids: set[str] = set()
    first_rule_per_slot: dict[str, str] = {}
    for index, rule in enumerate(rules):
        path = f"slotRules[{index}]"
        if not isinstance(rule, dict):
            raise ValueError(f"{path}: rule must be an object")
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            raise ValueError(f"{path}: id must be a non-empty string")
        if rule_id in seen_ids:
            raise ValueError(f"{path}: duplicate rule id {rule_id!r}")
        seen_ids.add(rule_id)
        if not isinstance(rule.get("name"), str) or not rule["name"]:
            raise ValueError(f"{path}: name must be a non-empty string")
        if rule.get("targetSlot") not in _TARGET_SLOTS:
            raise ValueError(f"{path}: targetSlot must be one of {', '.join(_TARGET_SLOTS)}")
        match_field = rule.get("matchField")
        if not isinstance(match_field, str) or not match_field:
            raise ValueError(f"{path}: matchField must be a non-empty string")
        _validate_registry_path(match_field, _registry_document(), f"{path}.matchField")
        template = rule.get("valueTemplate")
        if not isinstance(template, str) or not template:
            raise ValueError(f"{path}: valueTemplate must be a non-empty string")
        _validate_template(template, path)
        fallback = rule.get("fallbackTemplate", "")
        if not isinstance(fallback, str):
            raise ValueError(f"{path}: fallbackTemplate must be a string")
        if fallback:
            _validate_template(fallback, path)
            slot = rule["targetSlot"]
            if slot in first_rule_per_slot:
                raise ValueError(
                    f"{path}: fallbackTemplate already declared by rule "
                    f"{first_rule_per_slot[slot]!r} for {slot}"
                )
        first_rule_per_slot.setdefault(rule["targetSlot"], rule_id)


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


def _build_state(config: Any, data: Any) -> dict[str, Any]:
    rules = (config or {}).get("slotRules") or []
    slot_ids = (data or {}).get("slotIds") or {}
    prepared: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict) or not rule.get("isActive", True):
            continue
        raw = slot_ids.get(rule.get("id"), "")
        prepared.append({
            "id": rule["id"],
            "targetSlot": rule["targetSlot"],
            "matchField": rule["matchField"],
            "ids": parse_id_list(raw if isinstance(raw, str) else ""),
            "template": compile_template(rule["valueTemplate"]),
            "fallback": compile_template(rule.get("fallbackTemplate") or ""),
        })
    return {"rules": prepared}


class CustomLabelsPlugin:
    """Pipeline module assigning custom labels from bulk-ID slot rules."""

    def validate_config(self, config: Any) -> None:
        validate_config(config)

    def prepare_run(self, config: Any, data: Any, ctx: Any) -> dict[str, Any]:
        return _build_state(config, data)

    def process(
        self,
        product: dict[str, Any],
        config: Any,
        data: Any,
        ctx: Any,
        state: Any = None,
    ) -> dict[str, Any]:
        rules = (state or _build_state(config, data)).get("rules") or []
        if not rules:
            return product
        result = dict(product)
        by_slot: dict[str, list[dict[str, Any]]] = {}
        for rule in rules:
            by_slot.setdefault(rule["targetSlot"], []).append(rule)

        for slot, slot_rules in by_slot.items():
            value: str | None = None
            for rule in slot_rules:
                if not matches(product, rule["matchField"], rule["ids"]):
                    continue
                value = render_template(rule["template"], product)
                if value is not None:
                    break
                # matched but a token resolved empty -> skip to the next rule
            if value is None and slot_rules[0]["fallback"]:
                value = render_template(slot_rules[0]["fallback"], product)
            if value:
                result[slot] = value
        return result
```

- [ ] **Step 4: Write the manifest**

Create `plugins/core/custom_labels/plugin.json`:

```json
{
  "id": "custom_labels",
  "name": "Custom Labels",
  "version": "1.0.0",
  "extension_point": "pipeline_module",
  "entry_point": "plugin:CustomLabelsPlugin",
  "config_scope": ["global", "client"],
  "data_scope": ["client", "feed_source"],
  "frontend": {
    "menu_item": "Custom Labels",
    "icon": "tag",
    "component": "component.tsx"
  },
  "config_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Custom Labels",
    "properties": {
      "slotRules": {
        "type": "array",
        "title": "Slot rules",
        "items": {
          "type": "object",
          "properties": {
            "id": {"type": "string", "title": "ID"},
            "name": {"type": "string", "title": "Name"},
            "isActive": {"type": "boolean", "title": "Active", "default": true},
            "targetSlot": {
              "type": "string",
              "title": "Target slot",
              "enum": ["custom_label_0", "custom_label_1", "custom_label_2", "custom_label_3", "custom_label_4"]
            },
            "matchField": {"type": "string", "title": "Match field"},
            "valueTemplate": {"type": "string", "title": "Value template"},
            "fallbackTemplate": {"type": "string", "title": "Fallback template", "default": ""}
          },
          "required": ["id", "name", "targetSlot", "matchField", "valueTemplate"]
        }
      }
    }
  },
  "data_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Custom Labels bulk IDs",
    "properties": {
      "slotIds": {
        "type": "object",
        "title": "Slot ID lists",
        "additionalProperties": {"type": "string"}
      }
    }
  }
}
```

No top-level `required` in `config_schema` — the contract checker calls `validate_config({})` and empty config must pass (same as `core/rules`).

- [ ] **Step 5: Run all plugin tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_custom_labels_plugin.py -v`
Expected: PASS (primitive, validation, and process tests — all in this file).

- [ ] **Step 6: Run contract + discovery + startup suites**

Run: `cd backend && uv run pytest tests/test_plugin_contract.py tests/test_plugins_discovery.py tests/test_plugins_startup.py -v`
Expected: PASS. The new core plugin is now discovered (a `plugins/core/custom_labels/` dir with a valid manifest) — if any test asserts an exact count or list of core plugins, update the expectation to include `custom_labels` and say so in the commit message. If a contract test rejects the plugin because `_check_process` calls `process` with empty config/data (no slotRules → product returned unchanged), that is correct behavior and passes.

- [ ] **Step 7: Update docs (same commit)**

In `backend/docs/plugins.md`, wherever core plugins are listed (alongside `rules` and `filter`), add a `custom_labels` entry: bulk-ID slot rules; config = `slotRules` (global/client); data = `slotIds` keyed by rule id (client/feed_source); matching = registry attribute path membership in a trimmed/deduped set; first-match-wins per slot; empty token skips the rule; per-slot fallback from the first rule of a slot.

- [ ] **Step 8: Lint, typecheck, commit**

Run: `cd backend && uv run ruff check . && uv run mypy .`
Expected: clean.

```bash
git add plugins/core/custom_labels/plugin.py plugins/core/custom_labels/plugin.json backend/tests/test_custom_labels_plugin.py backend/docs/plugins.md
git commit -m "feat(custom-labels): plugin class with validate_config, prepare_run, per-slot first-match process"
```

---

### Task 4: Scope-merge and config_hash delta tests

**Files:**
- Create: `backend/tests/test_custom_labels_delta.py`

**Interfaces:**
- Consumes: `merge_scopes` from `backend/app/staging/config_resolver.py` (signature `merge_scopes(global_payload: dict, client_payload: dict | None, feed_source_payload: dict | None) -> dict`); `content_hash` from `backend/app/staging/hashing.py` (`StagingStep` derives `config_hash = content_hash(bundle)` — `backend/app/pipeline/steps.py:172`; the bundle contains each instance's `resolved_config` AND `resolved_data` — `backend/docs/data-model.md:237`).
- Produces: regression proof that (a) `slotIds` merges per key across scopes and (b) config **and** data edits each change `config_hash` → reprocessing.

- [ ] **Step 1: Write the tests**

Create `backend/tests/test_custom_labels_delta.py`:

```python
"""Scope merge + config_hash sensitivity for custom_labels config/data edits."""

from app.staging.config_resolver import merge_scopes
from app.staging.hashing import content_hash


class TestSlotIdsPerKeyMerge:
    def test_feed_source_overrides_only_its_rule(self):
        client = {"slotIds": {"r1": "a\nb", "r2": "x\ny"}}
        feed = {"slotIds": {"r2": "z"}}
        resolved = merge_scopes({}, client, feed)
        assert resolved["slotIds"] == {"r1": "a\nb", "r2": "z"}

    def test_client_overrides_global_only_its_rule(self):
        global_cfg = {"slotIds": {"r1": "a", "r2": "x"}}
        client = {"slotIds": {"r1": "b"}}
        resolved = merge_scopes(global_cfg, client, None)
        assert resolved["slotIds"] == {"r1": "b", "r2": "x"}


def _bundle(resolved_config: dict, resolved_data: dict) -> dict:
    return {
        "pipeline": None,
        "instances": [
            {
                "position": 0,
                "plugin": "custom_labels",
                "plugin_version": "1.0.0",
                "instance_config": {},
                "resolved_config": resolved_config,
                "resolved_data": resolved_data,
            }
        ],
    }


class TestConfigHashSensitivity:
    BASE_CONFIG = {"slotRules": [
        {"id": "r1", "name": "Mid", "isActive": True, "targetSlot": "custom_label_1",
         "matchField": "id", "valueTemplate": "{brand} - Mid"},
    ]}
    BASE_DATA = {"slotIds": {"r1": "a\nb"}}

    def test_unchanged_config_and_data_hash_equal(self):
        assert content_hash(_bundle(self.BASE_CONFIG, self.BASE_DATA)) == content_hash(
            _bundle(dict(self.BASE_CONFIG), dict(self.BASE_DATA))
        )

    def test_config_edit_changes_hash(self):
        edited = {"slotRules": [
            {**self.BASE_CONFIG["slotRules"][0], "valueTemplate": "{brand} - NEW"},
        ]}
        assert content_hash(_bundle(edited, self.BASE_DATA)) != content_hash(
            _bundle(self.BASE_CONFIG, self.BASE_DATA)
        )

    def test_data_edit_changes_hash(self):
        edited = {"slotIds": {"r1": "a\nb\nc"}}
        assert content_hash(_bundle(self.BASE_CONFIG, edited)) != content_hash(
            _bundle(self.BASE_CONFIG, self.BASE_DATA)
        )
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_custom_labels_delta.py -v`
Expected: PASS immediately — these pin existing behavior. If any fails, STOP and investigate: a failure means the spec's delta assumptions are wrong and blocks the frontend tasks.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_custom_labels_delta.py
git commit -m "test(custom-labels): per-key scope merge and config_hash sensitivity for config/data edits"
```

---

### Task 5: Frontend plugin-data hooks

**Files:**
- Modify: `frontend/src/api/queryKeys.ts` (append `pluginData` after `pluginConfig`, end of `queryKeys` object)
- Modify: `frontend/src/api/hooks.ts` (append after `useSavePluginConfig`, ~line 392)
- Modify: `frontend/src/api/hooks.plugin.test.tsx` (append tests)

**Interfaces:**
- Consumes: existing `buildScopeQuery`, `PluginScope`, `apiGet`/`apiPut`, `queryKeys.pluginConfig` pattern.
- Produces: `usePluginData(pluginId: string, scope?: PluginScope)` and `useSavePluginData(pluginId: string, scope?: PluginScope)`; response type `Record<string, unknown>`.

- [ ] **Step 1: Write the failing hook tests**

Append to `frontend/src/api/hooks.plugin.test.tsx`, reusing its existing `jsonResponse` helper and adding `usePluginData, useSavePluginData` to the imports from `./hooks` (plus `renderHook`, `waitFor` are already imported):

```tsx
describe('usePluginData', () => {
  it('GETs /plugins/{id}/data with scope query params', async () => {
    let capturedUrl = '';
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/data')) {
        capturedUrl = url;
        return jsonResponse({ slotIds: { r1: 'a' } });
      }
      return jsonResponse({});
    });

    const { result } = renderHook(() => usePluginData('custom_labels', { feedSourceId: 7 }), {
      wrapper: withClient(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedUrl).toBe('/plugins/custom_labels/data?feed_source_id=7');
    expect(result.current.data).toEqual({ slotIds: { r1: 'a' } });
  });
});

describe('useSavePluginData', () => {
  it('PUTs /plugins/{id}/data and invalidates the pluginData key', async () => {
    let captured: { url: string; body: unknown } | null = null;
    stubFetch((url, init) => {
      if (url === '/plugins/custom_labels/data?feed_source_id=7' && init?.method === 'PUT') {
        captured = { url, body: JSON.parse(String(init.body)) };
        return jsonResponse({ status: 'ok' });
      }
      return jsonResponse({});
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useSavePluginData('custom_labels', { feedSourceId: 7 }), {
      wrapper,
    });
    result.current.mutate({ slotIds: { r1: 'a' } });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toEqual({
      url: '/plugins/custom_labels/data?feed_source_id=7',
      body: { slotIds: { r1: 'a' } },
    });
    const invalidated = invalidateSpy.mock.calls.map((c) => c[0]);
    const hasDataKey = invalidated.some(
      (q) =>
        JSON.stringify(q?.queryKey) ===
        JSON.stringify(queryKeys.pluginData('custom_labels', { feedSourceId: 7 })),
    );
    expect(hasDataKey).toBe(true);
  });
});
```

Note: `withClient()` already exists in that file (used by the `usePluginConfig` tests) — reuse it; do not define a second one. Match its exact shape if it differs from the snippet.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- hooks.plugin`
Expected: FAIL — `usePluginData` is not exported from `./hooks`.

- [ ] **Step 3: Add the query key**

In `frontend/src/api/queryKeys.ts`, append inside the `queryKeys` object right after `pluginConfig`:

```ts
  pluginData: (pluginId: string, scope?: { clientId?: number; feedSourceId?: number }) =>
    ['plugin-data', pluginId, scope ?? {}] as const,
```

- [ ] **Step 4: Add the hooks**

In `frontend/src/api/hooks.ts`, append after `useSavePluginConfig`:

```ts
export function usePluginData(pluginId: string, scope?: PluginScope) {
  return useQuery({
    queryKey: queryKeys.pluginData(pluginId, scope),
    queryFn: () =>
      apiGet<Record<string, unknown>>(`/plugins/${pluginId}/data${buildScopeQuery(scope)}`),
    enabled: Boolean(pluginId),
  });
}

export function useSavePluginData(pluginId: string, scope?: PluginScope) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      apiPut<Record<string, unknown>>(`/plugins/${pluginId}/data${buildScopeQuery(scope)}`, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.pluginData(pluginId, scope) });
    },
  });
}
```

All imports (`useQuery`, `useMutation`, `useQueryClient`, `apiGet`, `apiPut`, `queryKeys`, `PluginScope`, `buildScopeQuery`) are already present in `hooks.ts` — used by the config hooks directly above.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm run test -- hooks.plugin && npm run typecheck`
Expected: PASS, typecheck clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/queryKeys.ts frontend/src/api/hooks.ts frontend/src/api/hooks.plugin.test.tsx
git commit -m "feat(frontend): plugin data hooks mirroring plugin config hooks"
```

---

### Task 6: Custom Labels plugin UI (config + operational page)

**Files:**
- Create: `frontend/src/features/customLabels/ids.ts`
- Create: `frontend/src/features/customLabels/SortableRuleRow.tsx`
- Create: `frontend/src/features/customLabels/CustomLabelsUI.tsx`
- Create: `frontend/src/features/customLabels/__tests__/ids.test.ts`
- Create: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
- Create: `plugins/core/custom_labels/frontend/component.tsx`
- Modify: `frontend/src/features/plugin/PluginPage.tsx` (imports at lines 10-12, mapping at line 54)
- Create: `frontend/public/locales/en/customLabels.json`, `frontend/public/locales/de/customLabels.json`
- Modify: `frontend/docs/plugin-uis.md`

**Interfaces:**
- Consumes: Task 5 hooks, existing `usePluginConfig`/`useSavePluginConfig`/`useRegistryAttributes`, `@dnd-kit/core` + `@dnd-kit/sortable` (the `RuleList.tsx` idiom: `useSortable({ id })` returning `{ attributes, listeners, setNodeRef, transform, transition }`), `useBlocker` from `react-router` (the `RulesUI.tsx:62` idiom).
- Produces: `CustomLabelsUI` (named + default export), props `{ pluginId: string; scope: PluginScope }`; frontend `parseIdList`/`compileTemplate`/`renderPreview` in `ids.ts` mirroring backend semantics.

- [ ] **Step 1: Frontend parser + preview helpers with tests**

Create `frontend/src/features/customLabels/ids.ts`:

```ts
export function parseIdList(raw: string | undefined | null): Set<string> {
  if (!raw) return new Set();
  const ids = new Set<string>();
  for (const part of raw.split(/[\n,]+/)) {
    const trimmed = part.trim();
    if (trimmed) ids.add(trimmed);
  }
  return ids;
}

export type TemplateSegment = { kind: 'lit'; text: string } | { kind: 'tok'; path: string };

export function compileTemplate(template: string): TemplateSegment[] {
  const segments: TemplateSegment[] = [];
  let pos = 0;
  for (const match of template.matchAll(/\{([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)?)\}/g)) {
    if (match.index > pos) segments.push({ kind: 'lit', text: template.slice(pos, match.index) });
    segments.push({ kind: 'tok', path: match[1] });
    pos = match.index + match[0].length;
  }
  if (pos < template.length) segments.push({ kind: 'lit', text: template.slice(pos) });
  return segments;
}

export function renderPreview(
  template: string,
  sample: Record<string, unknown> = { brand: 'Brand', id: '123' },
): string {
  return compileTemplate(template)
    .map((seg) => (seg.kind === 'lit' ? seg.text : String(sample[seg.path] ?? `{${seg.path}}`)))
    .join('');
}
```

Create `frontend/src/features/customLabels/__tests__/ids.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { compileTemplate, parseIdList, renderPreview } from '../ids';

describe('parseIdList', () => {
  it('splits, trims, drops empties, dedupes', () => {
    expect(parseIdList('a,b\n c ,d\n')).toEqual(new Set(['a', 'b', 'c', 'd']));
    expect(parseIdList('a\na\n\n, ,b')).toEqual(new Set(['a', 'b']));
  });

  it('handles null/empty', () => {
    expect(parseIdList(null).size).toBe(0);
    expect(parseIdList('  \n,').size).toBe(0);
  });
});

describe('compileTemplate', () => {
  it('splits literals and tokens including subfield paths', () => {
    expect(compileTemplate('{brand} - Mid')).toEqual([
      { kind: 'tok', path: 'brand' },
      { kind: 'lit', text: ' - Mid' },
    ]);
    expect(compileTemplate('under {price.value}')).toEqual([
      { kind: 'lit', text: 'under ' },
      { kind: 'tok', path: 'price.value' },
    ]);
  });
});

describe('renderPreview', () => {
  it('renders tokens from the sample and keeps unknown tokens visible', () => {
    expect(renderPreview('{brand} - Mid')).toBe('Brand - Mid');
    expect(renderPreview('{nope} x')).toBe('{nope} x');
  });
});
```

Run: `cd frontend && npm run test -- customLabels/ids`
Expected: PASS.

- [ ] **Step 2: Write the failing UI tests**

Create `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`, following the `RulesUI.test.tsx` idioms exactly (`stubFetch`, `createMemoryRouter` + `RouterProvider`, fresh `QueryClient` wrapper, `await i18n.loadNamespaces([...])` in `beforeAll`):

```tsx
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import CustomLabelsUI from '../../../../../plugins/core/custom_labels/frontend/component';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeAll(async () => {
  await i18n.loadNamespaces(['customLabels', 'common']);
});

beforeEach(() => {
  vi.restoreAllMocks();
});

const CONFIG = {
  slotRules: [
    {
      id: 'r1', name: 'Mid Funnel', isActive: true, targetSlot: 'custom_label_1',
      matchField: 'id', valueTemplate: '{brand} - Mid Funnel', fallbackTemplate: '',
    },
    {
      id: 'r2', name: 'Off', isActive: false, targetSlot: 'custom_label_0',
      matchField: 'item_group_id', valueTemplate: 'Rising', fallbackTemplate: '',
    },
  ],
};
const DATA = { slotIds: { r1: 'a,b,c' } };

function renderUI() {
  stubFetch((url) => {
    if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(CONFIG);
    if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse(DATA);
    if (url.startsWith('/registry/attributes')) return jsonResponse([
      { name: 'id', kind: 'scalar', sub_fields: [] },
      { name: 'brand', kind: 'scalar', sub_fields: [] },
      { name: 'item_group_id', kind: 'scalar', sub_fields: [] },
    ]);
    return jsonResponse({});
  });
  const router = createMemoryRouter(
    [
      {
        path: '/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId',
        element: <CustomLabelsUI pluginId="custom_labels" scope={{ feedSourceId: 1 }} />,
      },
    ],
    { initialEntries: ['/clients/1/feeds/1/plugins/custom_labels'] },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  render(
    <Wrapper>
      <RouterProvider router={router} />
    </Wrapper>,
  );
}

describe('CustomLabelsUI operational page', () => {
  it('renders one column per active rule with header metadata', async () => {
    renderUI();
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.getByText('custom_label_1 · id')).toBeInTheDocument();
    expect(screen.getByText('Brand - Mid Funnel')).toBeInTheDocument(); // template preview
    expect(screen.queryByText('Off')).not.toBeInTheDocument(); // inactive rule hidden
  });

  it('shows the parsed/deduped ID count live', async () => {
    renderUI();
    const area = await screen.findByLabelText('Mid Funnel ids');
    await userEvent.type(area, '{backspace>3}');
    await userEvent.type(area, 'x1\nx2,x1');
    expect(await screen.findByText(/2 unique IDs/)).toBeInTheDocument();
  });

  it('wraps the slot grid in a horizontally scrollable container', async () => {
    renderUI();
    expect(await screen.findByText('Mid Funnel'));
    const grid = document.querySelector('[data-testid="slot-grid"]') as HTMLElement;
    expect(grid.style.overflowX).toBe('auto');
  });
});
```

Note: the exact `render` import (`../../../test/render`) matches `RulesUI.test.tsx` — verify the relative depth when you create the file (it is three directories up from `__tests__`) and adjust if the test helper lives elsewhere. The `{backspace>3}` keyboard string deletes the prefilled `a,b,c` — verify against the actual userEvent version in `frontend/package.json`; if typing into a controlled Mantine `Textarea` is flaky, instead assert the initial count `3 unique IDs` (from the prefilled `a,b,c`) and skip the typing interaction.

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npm run test -- CustomLabelsUI`
Expected: FAIL — the component stub does not exist.

- [ ] **Step 4: Implement the UI components**

Create `frontend/src/features/customLabels/SortableRuleRow.tsx` (mirror the `RuleList.tsx:195` sortable idiom):

```tsx
import { Badge, Group, Switch, Text, UnstyledButton } from '@mantine/core';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useTranslation } from 'react-i18next';

export type SlotRuleSummary = {
  id: string;
  name: string;
  targetSlot: string;
  isActive: boolean;
};

export function SortableRuleRow({
  rule,
  selected,
  onSelect,
  onToggleActive,
}: {
  rule: SlotRuleSummary;
  selected: boolean;
  onSelect: () => void;
  onToggleActive: (isActive: boolean) => void;
}) {
  const { t } = useTranslation('customLabels');
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({
    id: rule.id,
  });
  return (
    <Group
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      gap="xs"
      px="xs"
      py={4}
      onClick={onSelect}
      data-selected={selected || undefined}
    >
      <UnstyledButton
        {...attributes}
        {...listeners}
        aria-label={t('dragHandle')}
        style={{ cursor: 'grab' }}
      >
        ⠿
      </UnstyledButton>
      <Text size="sm" style={{ flex: 1 }}>
        {rule.name}
      </Text>
      <Badge size="xs" variant="light">
        {rule.targetSlot}
      </Badge>
      <Switch
        checked={rule.isActive}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => onToggleActive(e.currentTarget.checked)}
      />
    </Group>
  );
}
```

Create `frontend/src/features/customLabels/CustomLabelsUI.tsx`:

```tsx
import { useMemo, useState } from 'react';
import {
  Badge, Button, Card, Group, Loader, Select, Stack, Switch, Tabs, Text, Textarea, TextInput,
} from '@mantine/core';
import {
  DndContext, PointerSensor, closestCenter, useSensor, useSensors,
} from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { useBlocker } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  usePluginConfig, usePluginData, useRegistryAttributes, useSavePluginConfig,
  useSavePluginData, type PluginScope,
} from '../../api/hooks';
import { notifySuccess } from '../../app/notifications';
import { parseIdList, renderPreview } from './ids';
import { SortableRuleRow } from './SortableRuleRow';

const TARGET_SLOTS = [
  'custom_label_0', 'custom_label_1', 'custom_label_2', 'custom_label_3', 'custom_label_4',
];

type SlotRule = {
  id: string;
  name: string;
  isActive: boolean;
  targetSlot: string;
  matchField: string;
  valueTemplate: string;
  fallbackTemplate: string;
};

function newRule(name: string): SlotRule {
  return {
    id: typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `r_${Math.random().toString(36).slice(2)}`,
    name,
    isActive: true,
    targetSlot: 'custom_label_0',
    matchField: 'id',
    valueTemplate: '',
    fallbackTemplate: '',
  };
}

export function CustomLabelsUI({ pluginId, scope }: { pluginId: string; scope: PluginScope }) {
  const { t } = useTranslation('customLabels');
  const { t: tCommon } = useTranslation('common');
  const config = usePluginConfig(pluginId, scope);
  const saveConfig = useSavePluginConfig(pluginId, scope);
  const data = usePluginData(pluginId, scope);
  const saveData = useSavePluginData(pluginId, scope);
  const attributes = useRegistryAttributes();

  const [rules, setRules] = useState<SlotRule[] | null>(null);
  const [slotIds, setSlotIds] = useState<Record<string, string> | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const serverRules = (config.data as { slotRules?: SlotRule[] } | undefined)?.slotRules ?? [];
  const serverIds =
    (data.data as { slotIds?: Record<string, string> } | undefined)?.slotIds ?? {};
  const effectiveRules = rules ?? serverRules;
  const effectiveIds = slotIds ?? serverIds;
  const dirtyRules = rules !== null;
  const dirtyIds = slotIds !== null;
  const dirty = dirtyRules || dirtyIds;

  const activeRules = effectiveRules.filter((r) => r.isActive);
  const selected = effectiveRules.find((r) => r.id === selectedId) ?? null;
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const matchSuggestions = useMemo(() => {
    const list: string[] = [];
    for (const attr of attributes.data ?? []) {
      list.push(attr.name);
      for (const sub of attr.sub_fields ?? []) list.push(`${attr.name}.${sub.name}`);
    }
    return list;
  }, [attributes.data]);

  function patchSelected(patch: Partial<SlotRule>) {
    if (!selected) return;
    setRules(effectiveRules.map((r) => (r.id === selected.id ? { ...r, ...patch } : r)));
  }

  useBlocker(({ currentLocation, nextLocation }) => {
    if (!dirty) return false;
    if (currentLocation.pathname === nextLocation.pathname) return false;
    return !window.confirm(t('unsavedChanges'));
  });

  async function saveRules() {
    await saveConfig.mutateAsync({ slotRules: effectiveRules });
    setRules(null);
    notifySuccess(t('configSaved'));
  }

  async function saveIds() {
    await saveData.mutateAsync({ slotIds: effectiveIds });
    setSlotIds(null);
    notifySuccess(t('idsSaved'));
  }

  if (config.isPending || data.isPending) return <Loader />;

  return (
    <Tabs defaultValue="ids" keepMounted={false}>
      <Tabs.List>
        <Tabs.Tab value="ids">{t('tabs.bulkIds')}</Tabs.Tab>
        <Tabs.Tab value="rules">{t('tabs.slotRules')}</Tabs.Tab>
      </Tabs.List>

      <Tabs.Panel value="ids" pt="sm">
        <Stack gap="sm">
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setSlotIds(null)} disabled={!dirtyIds}>
              {tCommon('actions.cancel')}
            </Button>
            <Button onClick={() => void saveIds()} loading={saveData.isPending} disabled={!dirtyIds}>
              {tCommon('actions.save')}
            </Button>
          </Group>
          <div data-testid="slot-grid" style={{ overflowX: 'auto' }}>
            <Group gap="md" wrap="nowrap" align="flex-start">
              {activeRules.map((rule) => {
                const raw = effectiveIds[rule.id] ?? '';
                const count = parseIdList(raw).size;
                return (
                  <Stack key={rule.id} gap={4} miw={280} w={280}>
                    <Group gap="xs">
                      <Text size="sm" fw={600}>{rule.name}</Text>
                      <Badge size="xs" variant="light">{rule.targetSlot}</Badge>
                    </Group>
                    <Text size="xs" c="dimmed">{rule.matchField}</Text>
                    <Text size="xs" c="dimmed">{renderPreview(rule.valueTemplate)}</Text>
                    <Textarea
                      aria-label={`${rule.name} ids`}
                      minRows={10}
                      autosize
                      value={raw}
                      onChange={(e) =>
                        setSlotIds({ ...effectiveIds, [rule.id]: e.currentTarget.value })}
                      placeholder={t('idsPlaceholder')}
                    />
                    <Text size="xs" c="dimmed">{t('idCount', { count })}</Text>
                  </Stack>
                );
              })}
              {activeRules.length === 0 && <Text c="dimmed">{t('noActiveRules')}</Text>}
            </Group>
          </div>
        </Stack>
      </Tabs.Panel>

      <Tabs.Panel value="rules" pt="sm">
        <Stack gap="sm">
          <Group justify="space-between">
            <Group>
              <Button variant="default" onClick={() => setRules(null)} disabled={!dirtyRules}>
                {tCommon('actions.cancel')}
              </Button>
              <Button
                onClick={() => void saveRules()}
                loading={saveConfig.isPending}
                disabled={!dirtyRules}
              >
                {tCommon('actions.save')}
              </Button>
            </Group>
            <Button
              variant="light"
              onClick={() => {
                const rule = newRule(t('newRuleName'));
                setRules([...effectiveRules, rule]);
                setSelectedId(rule.id);
              }}
            >
              {t('addRule')}
            </Button>
          </Group>
          <Group align="flex-start" gap="md" wrap="nowrap">
            <Card withBorder miw={320} w={320}>
              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={({ active, over }) => {
                  if (!over || active.id === over.id) return;
                  const from = effectiveRules.findIndex((r) => r.id === active.id);
                  const to = effectiveRules.findIndex((r) => r.id === over.id);
                  const next = [...effectiveRules];
                  const [moved] = next.splice(from, 1);
                  next.splice(to, 0, moved);
                  setRules(next);
                }}
              >
                <SortableContext
                  items={effectiveRules.map((r) => r.id)}
                  strategy={verticalListSortingStrategy}
                >
                  <Stack gap={4}>
                    {effectiveRules.map((rule) => (
                      <SortableRuleRow
                        key={rule.id}
                        rule={rule}
                        selected={rule.id === selectedId}
                        onSelect={() => setSelectedId(rule.id)}
                        onToggleActive={(isActive) =>
                          setRules(
                            effectiveRules.map((r) =>
                              r.id === rule.id ? { ...r, isActive } : r,
                            ),
                          )}
                      />
                    ))}
                  </Stack>
                </SortableContext>
              </DndContext>
            </Card>
            {selected && (
              <Card withBorder style={{ flex: 1 }}>
                <Stack gap="sm">
                  <TextInput
                    label={t('fields.name')}
                    value={selected.name}
                    onChange={(e) => patchSelected({ name: e.currentTarget.value })}
                  />
                  <Switch
                    label={t('fields.isActive')}
                    checked={selected.isActive}
                    onChange={(e) => patchSelected({ isActive: e.currentTarget.checked })}
                  />
                  <Select
                    label={t('fields.targetSlot')}
                    data={TARGET_SLOTS}
                    value={selected.targetSlot}
                    onChange={(v) => patchSelected({ targetSlot: v ?? 'custom_label_0' })}
                  />
                  <TextInput
                    label={t('fields.matchField')}
                    value={selected.matchField}
                    onChange={(e) => patchSelected({ matchField: e.currentTarget.value })}
                    list="match-field-suggestions"
                  />
                  <datalist id="match-field-suggestions">
                    {matchSuggestions.map((s) => (
                      <option key={s} value={s} />
                    ))}
                  </datalist>
                  <TextInput
                    label={t('fields.valueTemplate')}
                    description={t('fields.valueTemplateHint')}
                    value={selected.valueTemplate}
                    onChange={(e) => patchSelected({ valueTemplate: e.currentTarget.value })}
                  />
                  <TextInput
                    label={t('fields.fallbackTemplate')}
                    description={t('fields.fallbackHint')}
                    value={selected.fallbackTemplate}
                    onChange={(e) => patchSelected({ fallbackTemplate: e.currentTarget.value })}
                  />
                </Stack>
              </Card>
            )}
          </Group>
        </Stack>
      </Tabs.Panel>
    </Tabs>
  );
}

export default CustomLabelsUI;
```

- [ ] **Step 5: Wire the plugin stub and PluginPage mapping**

Create `plugins/core/custom_labels/frontend/component.tsx` (same seam as rules):

```tsx
export { default } from '../../../../frontend/src/features/customLabels/CustomLabelsUI';
```

In `frontend/src/features/plugin/PluginPage.tsx`:

(a) Replace lines 10-12 with:

```tsx
// MVP wiring: static import of core plugin components (the plugin stub is the seam).
// Full build-time discovery of plugin components is a follow-up — see ADR 0002.
import RulesUI from '../../../../plugins/core/rules/frontend/component';
import CustomLabelsUI from '../../../../plugins/core/custom_labels/frontend/component';
```

(b) Replace line 54 (`const CustomComponent = customComponent === 'component.tsx' ? RulesUI : null;`) with:

```tsx
  const CUSTOM_COMPONENTS: Record<string, typeof RulesUI> = {
    rules: RulesUI,
    custom_labels: CustomLabelsUI,
  };
  const CustomComponent =
    customComponent === 'component.tsx' ? (CUSTOM_COMPONENTS[plugin.id] ?? null) : null;
```

- [ ] **Step 6: Add i18n files**

Create `frontend/public/locales/en/customLabels.json`:

```json
{
  "tabs": { "bulkIds": "Bulk IDs", "slotRules": "Slot rules" },
  "idsPlaceholder": "One ID per line, or comma-separated",
  "idCount": "{{count}} unique IDs",
  "noActiveRules": "No active slot rules — add one under Slot rules.",
  "addRule": "Add rule",
  "newRuleName": "New slot rule",
  "configSaved": "Slot rules saved",
  "idsSaved": "Bulk IDs saved",
  "unsavedChanges": "You have unsaved changes. Leave anyway?",
  "dragHandle": "Drag to reorder",
  "fields": {
    "name": "Name",
    "isActive": "Active",
    "targetSlot": "Target slot",
    "matchField": "Match field",
    "valueTemplate": "Value template",
    "valueTemplateHint": "Use {field} tokens, e.g. {brand} - Mid Funnel. An empty token skips the rule.",
    "fallbackTemplate": "Fallback template",
    "fallbackHint": "Used when no rule matches this slot. Only the first rule of a slot may declare it."
  }
}
```

Create `frontend/public/locales/de/customLabels.json` (same keys, German):

```json
{
  "tabs": { "bulkIds": "Bulk-IDs", "slotRules": "Slot-Regeln" },
  "idsPlaceholder": "Eine ID pro Zeile oder kommagetrennt",
  "idCount": "{{count}} eindeutige IDs",
  "noActiveRules": "Keine aktiven Slot-Regeln — unter Slot-Regeln anlegen.",
  "addRule": "Regel hinzufügen",
  "newRuleName": "Neue Slot-Regel",
  "configSaved": "Slot-Regeln gespeichert",
  "idsSaved": "Bulk-IDs gespeichert",
  "unsavedChanges": "Du hast ungespeicherte Änderungen. Trotzdem verlassen?",
  "dragHandle": "Zum Neusortieren ziehen",
  "fields": {
    "name": "Name",
    "isActive": "Aktiv",
    "targetSlot": "Ziel-Slot",
    "matchField": "Match-Feld",
    "valueTemplate": "Wert-Vorlage",
    "valueTemplateHint": "{field}-Tokens verwenden, z. B. {brand} - Mid Funnel. Ein leerer Token überspringt die Regel.",
    "fallbackTemplate": "Fallback-Vorlage",
    "fallbackHint": "Wird verwendet, wenn keine Regel für diesen Slot greift. Nur die erste Regel eines Slots darf sie setzen."
  }
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd frontend && npm run test && npm run typecheck && npm run build`
Expected: PASS, typecheck and build clean.

- [ ] **Step 8: Update docs (same commit)**

In `frontend/docs/plugin-uis.md`, "Custom Plugin Components" section, update the Rules-only sentence to: "`PluginPage` maps plugin IDs to statically imported components (`rules` → RulesUI, `custom_labels` → CustomLabelsUI) and renders the match when `manifest.frontend.component === 'component.tsx'`; add new custom components to that map until build-time discovery lands."

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/customLabels plugins/core/custom_labels/frontend frontend/src/features/plugin/PluginPage.tsx frontend/public/locales/en/customLabels.json frontend/public/locales/de/customLabels.json frontend/docs/plugin-uis.md
git commit -m "feat(custom-labels): plugin UI — slot-rule config editor and bulk-ID grid"
```

---

### Task 7: Full verification + docs consistency

**Files:**
- Modify (only if verification reveals drift): `backend/docs/plugins.md`, `backend/docs/architecture.md`, `backend/docs/api.md`, `frontend/docs/plugin-uis.md`, acceptance tests

- [ ] **Step 1: Full backend suite**

Run: `cd backend && uv run pytest -n auto`
Expected: PASS. If `test_m5_acceptance.py` / `test_m6_acceptance.py` / `test_plugins_discovery.py` assert exact plugin counts or lists, update the expectations to include `custom_labels` and note it in the commit message.

- [ ] **Step 2: Backend lint + typecheck**

Run: `cd backend && uv run ruff check . && uv run mypy .`
Expected: clean.

- [ ] **Step 3: Frontend suite + typecheck + build**

Run: `cd frontend && npm run test && npm run typecheck && npm run build`
Expected: PASS.

- [ ] **Step 4: Docs consistency pass**

Verify the final state is fully documented: `prepare_run` hook (`backend/docs/plugins.md`, `backend/docs/architecture.md`), the `custom_labels` core-plugin entry (`backend/docs/plugins.md`), the component map (`frontend/docs/plugin-uis.md`). Confirm `gmc-feed-engine-spec.md` was NOT modified — the known §5.9 Labelizer staleness is flagged in the design spec §8 and intentionally deferred to spec v7; if any OTHER doc/spec contradiction appears, STOP and flag to the operator.

- [ ] **Step 5: Final commit (if docs changed)**

```bash
git add backend/docs frontend/docs
git commit -m "docs: custom_labels plugin documentation consistency pass"
```
