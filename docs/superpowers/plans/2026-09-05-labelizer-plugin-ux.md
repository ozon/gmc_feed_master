# Labelizer (Custom Labels) UX Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Custom Labels plugin page show a truthful merged Global/Client/Feed view (identical to run-time resolution), add match-mode rules, a registry-field dropdown, help content, scope badges, and rename the UI to "Labelizer".

**Architecture:** Backend first: an opt-in, manifest-declared `union_by_key` list-merge strategy in `config_resolver` makes global+client `slotRules` union-by-id at run time. A mandatory equivalence test (backend + frontend, same fixture) gates the frontend merged view: **if the equivalence tests cannot pass, STOP and switch to a backend resolved-view endpoint per spec §1.2 — do not continue with the frontend merge.** The frontend then multi-fetches declared tiers and merges with the identical algorithm, adds ScopeBadge/ScopeContextBar, rule `matchMode`, a Combobox match-field, help UI, and the i18n display-name override.

**Tech Stack:** FastAPI/SQLAlchemy (backend), React 19 + Mantine 9 + TanStack Query + i18next + vitest (frontend), pytest (backend).

**Spec:** `docs/superpowers/specs/2026-09-05-labelizer-plugin-ux-design.md`

## Global Constraints

- Plugin id stays `custom_labels`; manifest `name`, backend identifiers, REST API surface unchanged (UI-only rename via i18n `pluginNames`).
- `slotRules` remains a JSON array; no data migration.
- Generic list-merge stays wholesale-replacement unless a manifest declares `config_merge` — `test_config_merge.py::test_non_dict_values_replace_wholesale` must stay green.
- All user-facing strings in `frontend/public/locales/en/*.json` AND `de/*.json` (both locales, every task).
- Match-field is NOT restricted to `id`; new rules still default to `id`.
- Backend commands (from `backend/`): `uv run pytest -n auto`, `uv run ruff check .`, `uv run mypy .` (pytest needs `TEST_DATABASE_URL` pointing at PostgreSQL).
- Frontend commands (from `frontend/`): `npm run test`, `npm run typecheck`, `npm run build`.
- Commit style: `feat(...)`, `test(...)`, `docs(...)` conventional prefixes, no secrets.
- Docs updated in the same commit as behavior changes (repo rule).

**Shared equivalence fixture** (used verbatim in Task 1, Task 3, Task 5 — do not diverge):

```
GLOBAL slotRules: g1 (custom_label_1), g2 (custom_label_0)
CLIENT slotRules: g1-override (custom_label_1), c2 (custom_label_0), c3 (custom_label_1)
EXPECTED merged ids (order): ["g1", "g2", "c2", "c3"]
EXPECTED merged names: ["Client Mid", "Global Top", "Client Only", "Same Slot As G1"]
EXPECTED per-slot id order: custom_label_1 -> ["g1", "c3"], custom_label_0 -> ["g2", "c2"]
```

---

### Task 1: Backend — union-by-id list merge in `config_resolver`

**Files:**
- Modify: `backend/app/staging/config_resolver.py`
- Test: `backend/tests/test_config_merge.py`

**Interfaces:**
- Produces: `_merge_dicts(base, overlay, merge_hints=None)`,
  `_merge_list(base, overlay, hint) -> list`,
  `_resolve_declared(scopes, maps, merge_hints=None) -> dict` (private but
  consumed by Task 3's integration test).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_config_merge.py`:

```python
from app.staging.config_resolver import _resolve_declared

# Shared equivalence fixture — keep in lockstep with
# frontend/src/features/customLabels/scopeMerge.test.ts (spec §1.2 gate).
GLOBAL_SLOT_RULES = [
    {"id": "g1", "name": "Global Mid", "isActive": True,
     "targetSlot": "custom_label_1", "matchField": "id",
     "valueTemplate": "{brand} - Mid"},
    {"id": "g2", "name": "Global Top", "isActive": True,
     "targetSlot": "custom_label_0", "matchField": "id",
     "valueTemplate": "{brand} - Top"},
]
CLIENT_SLOT_RULES = [
    {"id": "g1", "name": "Client Mid", "isActive": True,
     "targetSlot": "custom_label_1", "matchField": "brand",
     "valueTemplate": "{brand} - Client"},
    {"id": "c2", "name": "Client Only", "isActive": True,
     "targetSlot": "custom_label_0", "matchField": "id",
     "valueTemplate": "{brand} - ClientOnly"},
    {"id": "c3", "name": "Same Slot As G1", "isActive": True,
     "targetSlot": "custom_label_1", "matchField": "id",
     "valueTemplate": "{brand} - C3"},
]
UNION_HINTS = {"slotRules": {"strategy": "union_by_key", "key": "id"}}


class TestUnionByKey:
    def test_hinted_list_unions_by_id_in_ancestor_order(self):
        merged = _resolve_declared(
            ["global", "client"],
            {"global": {"slotRules": GLOBAL_SLOT_RULES},
             "client": {"slotRules": CLIENT_SLOT_RULES}},
            UNION_HINTS,
        )
        rules = merged["slotRules"]
        # Same ids in the same order as the frontend merge (spec §1.2):
        assert [r["id"] for r in rules] == ["g1", "g2", "c2", "c3"]
        # Content of the more specific tier wins for the overridden id...
        assert [r["name"] for r in rules] == [
            "Client Mid", "Global Top", "Client Only", "Same Slot As G1",
        ]
        # ...and per-slot winning order (first match wins) is identical:
        by_slot: dict[str, list[str]] = {}
        for rule in rules:
            by_slot.setdefault(rule["targetSlot"], []).append(rule["id"])
        assert by_slot == {
            "custom_label_1": ["g1", "c3"],
            "custom_label_0": ["g2", "c2"],
        }

    def test_client_only_config_extends_global(self):
        merged = _resolve_declared(
            ["global", "client"],
            {"global": {"slotRules": GLOBAL_SLOT_RULES},
             "client": {"slotRules": [CLIENT_SLOT_RULES[1]]}},
            UNION_HINTS,
        )
        assert [r["id"] for r in merged["slotRules"]] == ["g1", "g2", "c2"]

    def test_ancestor_only_config_passes_through(self):
        merged = _resolve_declared(
            ["global", "client"],
            {"global": {"slotRules": GLOBAL_SLOT_RULES}, "client": {}},
            UNION_HINTS,
        )
        assert [r["id"] for r in merged["slotRules"]] == ["g1", "g2"]

    def test_without_hint_lists_still_replace_wholesale(self):
        merged = _resolve_declared(
            ["global", "client"],
            {"global": {"slotRules": GLOBAL_SLOT_RULES},
             "client": {"slotRules": CLIENT_SLOT_RULES}},
            None,
        )
        assert [r["id"] for r in merged["slotRules"]] == ["g1", "c2", "c3"]

    def test_unknown_strategy_replaces_wholesale(self):
        merged = _resolve_declared(
            ["global", "client"],
            {"global": {"slotRules": GLOBAL_SLOT_RULES},
             "client": {"slotRules": CLIENT_SLOT_RULES}},
            {"slotRules": {"strategy": "nope"}},
        )
        assert [r["id"] for r in merged["slotRules"]] == ["g1", "c2", "c3"]

    def test_non_dict_items_are_appended(self):
        merged = _resolve_declared(
            ["global", "client"],
            {"global": {"slotRules": ["raw"]},
             "client": {"slotRules": [{"id": "c2", "name": "C"}]}},
            UNION_HINTS,
        )
        assert merged["slotRules"] == ["raw", {"id": "c2", "name": "C"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_merge.py -q` (from `backend/`)
Expected: FAIL — `TypeError: _resolve_declared() takes 3 positional arguments` / ImportError.

- [ ] **Step 3: Implement**

In `backend/app/staging/config_resolver.py`, replace lines 1–48 (up to and
including `_resolve_declared`) with:

```python
"""Three-tier scope resolution for plugin config/data payloads."""

from __future__ import annotations

from typing import Any


def _merge_dicts(
    base: dict[str, Any],
    overlay: dict[str, Any],
    merge_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(merged[key], value)
        elif (
            merge_hints
            and key in merge_hints
            and isinstance(merged.get(key), list)
            and isinstance(value, list)
        ):
            merged[key] = _merge_list(merged[key], value, merge_hints[key])
        else:
            merged[key] = value
    return merged


def _merge_list(base: list[Any], overlay: list[Any], hint: Any) -> list[Any]:
    """Merge lists per manifest hint. Unknown/absent strategy: wholesale replace."""
    if not isinstance(hint, dict) or hint.get("strategy") != "union_by_key":
        return overlay
    key = hint.get("key") or "id"
    merged = list(base)
    positions: dict[Any, int] = {}
    for index, item in enumerate(merged):
        if isinstance(item, dict) and key in item:
            positions.setdefault(item[key], index)
    for item in overlay:
        if isinstance(item, dict) and item.get(key) in positions:
            merged[positions[item[key]]] = item
        else:
            merged.append(item)
    return merged


def merge_scopes(
    global_payload: dict[str, Any],
    client_payload: dict[str, Any] | None,
    feed_source_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved = dict(global_payload)
    if client_payload is not None:
        resolved = _merge_dicts(resolved, client_payload)
    if feed_source_payload is not None:
        resolved = _merge_dicts(resolved, feed_source_payload)
    return resolved


_SCOPE_ORDER = ("global", "client", "feed_source")


def _normalize_scopes(raw: Any) -> list[str]:
    if raw is None:
        return ["global"]
    if isinstance(raw, str):
        return [raw]
    return [str(scope) for scope in raw]


def _resolve_declared(
    scopes: list[str],
    maps: dict[str, dict[str, Any]],
    merge_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for scope in _SCOPE_ORDER:
        if scope not in scopes:
            continue
        resolved = _merge_dicts(resolved, maps.get(scope) or {}, merge_hints)
    return resolved
```

Then in the same file, change the `resolved_config` call inside
`resolve_config_bundle` (currently lines ~110–113) to pass the manifest hint:

```python
            "resolved_config": _resolve_declared(
                _normalize_scopes(manifest.get("config_scope")),
                scoped_rows(configs_by_plugin.get(plugin.id, []), "config"),
                manifest.get("config_merge"),
            ),
```

(`resolved_data` stays unchanged — `slotIds` is an id-keyed object and merges
per-key generically.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config_merge.py tests/test_custom_labels_delta.py -q`
Expected: PASS (all, including pre-existing tests).

- [ ] **Step 5: Lint + typecheck**

Run: `uv run ruff check app/staging/config_resolver.py` and `uv run mypy app/staging/config_resolver.py`
Expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add app/staging/config_resolver.py tests/test_config_merge.py
git commit -m "feat(resolver): manifest-hinted union_by_key list merge"
```

---

### Task 2: Backend — manifest validation for `config_merge`

**Files:**
- Modify: `backend/app/plugins/manifest.py`
- Test: `backend/tests/test_plugins_manifest.py`

**Interfaces:**
- Consumes: manifest key `config_merge` = `{"<config-key>": {"strategy": "union_by_key", "key": "<id-field>"}}`.
- Produces: `parse_manifest` raises `ManifestError` for malformed `config_merge`; valid manifests (incl. custom_labels after Task 4) parse.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_plugins_manifest.py` (inside/beside the existing
test classes; reuse the file's existing minimal-valid-manifest helper or inline
one — check the file first and follow its existing fixture style):

```python
class TestConfigMergeValidation:
    def _manifest(self, **extra):
        doc = {
            "id": "plug", "name": "Plug", "version": "1.0.0",
            "extension_point": "pipeline_module",
            "config_schema": {"type": "object"},
            "data_schema": {"type": "object"},
        }
        doc.update(extra)
        return doc

    def test_valid_config_merge_parses(self):
        parsed = parse_manifest(self._manifest(config_merge={
            "slotRules": {"strategy": "union_by_key", "key": "id"},
        }))
        assert parsed.raw["config_merge"]["slotRules"]["key"] == "id"

    def test_config_merge_defaults_key_to_id(self):
        parsed = parse_manifest(self._manifest(config_merge={
            "slotRules": {"strategy": "union_by_key"},
        }))
        assert parsed.raw["config_merge"]["slotRules"]["key"] == "id"

    def test_rejects_unknown_strategy(self):
        with pytest.raises(ManifestError, match="strategy"):
            parse_manifest(self._manifest(config_merge={
                "slotRules": {"strategy": "replace_things"},
            }))

    def test_rejects_non_object_config_merge(self):
        with pytest.raises(ManifestError, match="config_merge"):
            parse_manifest(self._manifest(config_merge=["bad"]))

    def test_rejects_empty_key(self):
        with pytest.raises(ManifestError, match="key"):
            parse_manifest(self._manifest(config_merge={
                "slotRules": {"strategy": "union_by_key", "key": ""},
            }))
```

(Adjust imports at the top of the file: ensure `parse_manifest`,
`ManifestError`, and `pytest` are imported — they already are in this test
module.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugins_manifest.py -q`
Expected: FAIL — `test_rejects_unknown_strategy` etc. (parse_manifest currently
accepts anything).

- [ ] **Step 3: Implement**

In `backend/app/plugins/manifest.py`, add below `_parse_scope`:

```python
def _parse_config_merge(data: dict[str, Any]) -> None:
    value = data.get("config_merge")
    if value is None:
        return
    if not isinstance(value, dict) or not value:
        raise ManifestError("config_merge must be a non-empty object")
    for key, hint in value.items():
        if not isinstance(key, str) or not key:
            raise ManifestError("config_merge keys must be non-empty strings")
        if not isinstance(hint, dict) or hint.get("strategy") != "union_by_key":
            raise ManifestError(
                f"config_merge.{key}: strategy must be 'union_by_key'"
            )
        merge_key = hint.get("key", "id")
        if not isinstance(merge_key, str) or not merge_key:
            raise ManifestError(f"config_merge.{key}.key must be a non-empty string")
        hint.setdefault("key", merge_key)
```

And in `parse_manifest`, directly after the `schemas` validation loop:

```python
    _parse_config_merge(data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugins_manifest.py tests/test_plugin_contract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/plugins/manifest.py tests/test_plugins_manifest.py
git commit -m "feat(manifest): validate optional config_merge hints"
```

---

### Task 3: Backend — bundle integration + plugin-state equivalence (gate, backend half)

**Files:**
- Test: `backend/tests/test_config_bundle.py`
- Test: `backend/tests/test_custom_labels_plugin.py`

**Interfaces:**
- Consumes: `_resolve_declared(..., merge_hints)` from Task 1; `resolve_config_bundle` wiring; `CustomLabelsPlugin.prepare_run`.
- Produces: proof that `resolve_config_bundle` + plugin state produce the
  fixture's expected ids/order (spec §1.2 backend half).

- [ ] **Step 1: Write the failing integration test**

Append to `backend/tests/test_config_bundle.py` (imports at top: the fixture
constants from `test_config_merge` are local to that file — re-declare them
here, verbatim, with a cross-reference comment):

```python
async def test_bundle_slotrules_union_by_id_matches_frontend(
    isolated_database_url,
):
    # Keep in lockstep with test_config_merge.py and
    # frontend scopeMerge.test.ts (spec §1.2 gate).
    global_rules = [
        {"id": "g1", "name": "Global Mid", "isActive": True,
         "targetSlot": "custom_label_1", "matchField": "id",
         "valueTemplate": "{brand} - Mid"},
        {"id": "g2", "name": "Global Top", "isActive": True,
         "targetSlot": "custom_label_0", "matchField": "id",
         "valueTemplate": "{brand} - Top"},
    ]
    client_rules = [
        {"id": "g1", "name": "Client Mid", "isActive": True,
         "targetSlot": "custom_label_1", "matchField": "brand",
         "valueTemplate": "{brand} - Client"},
        {"id": "c2", "name": "Client Only", "isActive": True,
         "targetSlot": "custom_label_0", "matchField": "id",
         "valueTemplate": "{brand} - ClientOnly"},
        {"id": "c3", "name": "Same Slot As G1", "isActive": True,
         "targetSlot": "custom_label_1", "matchField": "id",
         "valueTemplate": "{brand} - C3"},
    ]
    engine, factory = _make(isolated_database_url)
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            plugin = Plugin(
                name="labelizer", version="1.0.0",
                manifest={
                    "id": "labelizer",
                    "config_scope": ["global", "client"],
                    "data_scope": "client",
                    "config_merge": {"slotRules": {
                        "strategy": "union_by_key", "key": "id",
                    }},
                },
            )
            session.add(plugin)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id, name="US feed", source_format="tsv"
            )
            session.add(feed_source)
            await session.flush()
            pipeline = ModulePipeline(
                feed_source_id=feed_source.id, name="pipe", version="1",
                definition={},
            )
            session.add(pipeline)
            await session.flush()
            feed_source.active_pipeline_id = pipeline.id
            session.add(ModuleInstance(
                pipeline_id=pipeline.id, plugin_id=plugin.id,
                position=0, name="lbl", configuration={},
            ))
            session.add(PluginConfig(
                plugin_id=plugin.id, scope="global", key="default",
                config={"slotRules": global_rules},
            ))
            session.add(PluginConfig(
                plugin_id=plugin.id, scope="client", client_id=client.id,
                key="default", config={"slotRules": client_rules},
            ))
        bundle = await resolve_config_bundle(session, feed_source)

    rules = bundle["instances"][0]["resolved_config"]["slotRules"]
    assert [r["id"] for r in rules] == ["g1", "g2", "c2", "c3"]
    assert [r["name"] for r in rules] == [
        "Client Mid", "Global Top", "Client Only", "Same Slot As G1",
    ]
    await engine.dispose()
```

- [ ] **Step 2: Write the failing plugin-state test (per-slot winning order)**

Append to `backend/tests/test_custom_labels_plugin.py` at module level (the
fixture constants are local to this file's style — re-declare, cross-ref):

```python
class TestMergedStateWinningOrder:
    """Spec §1.2 gate: state built from the union-merged config must preserve
    the fixture order of test_config_merge.py / frontend scopeMerge.test.ts."""

    MERGED_CONFIG = {
        "slotRules": [
            {"id": "g1", "name": "Client Mid", "isActive": True,
             "targetSlot": "custom_label_1", "matchField": "brand",
             "valueTemplate": "{brand} - Client"},
            {"id": "g2", "name": "Global Top", "isActive": True,
             "targetSlot": "custom_label_0", "matchField": "id",
             "valueTemplate": "{brand} - Top"},
            {"id": "c2", "name": "Client Only", "isActive": True,
             "targetSlot": "custom_label_0", "matchField": "id",
             "valueTemplate": "{brand} - ClientOnly"},
            {"id": "c3", "name": "Same Slot As G1", "isActive": True,
             "targetSlot": "custom_label_1", "matchField": "id",
             "valueTemplate": "{brand} - C3"},
        ]
    }

    def test_state_per_slot_order_matches_merged_list(self, plugin):
        state = plugin.prepare_run(self.MERGED_CONFIG, {"slotIds": {}}, _ctx())
        by_slot: dict[str, list[str]] = {}
        for rule in state["rules"]:
            by_slot.setdefault(rule["targetSlot"], []).append(rule["id"])
        assert by_slot == {
            "custom_label_1": ["g1", "c3"],
            "custom_label_0": ["g2", "c2"],
        }
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `uv run pytest tests/test_config_bundle.py tests/test_custom_labels_plugin.py -q`
Expected: PASS (both new tests — they pin Task 1's wiring; if they fail, Task 1's
`resolve_config_bundle` wiring is wrong: fix `config_resolver.py`, NOT the tests.
**If the union semantics themselves cannot be made to pass, STOP: spec §1.2
fallback applies — backend resolved-view endpoint instead of frontend merge;
report back before continuing.**)

- [ ] **Step 4: Commit**

```bash
git add tests/test_config_bundle.py tests/test_custom_labels_plugin.py
git commit -m "test(resolver): bundle/state equivalence for union_by_key merge"
```

---

### Task 4: Plugin — `matchMode` support + manifest keys

**Files:**
- Modify: `plugins/core/custom_labels/plugin.json`
- Modify: `plugins/core/custom_labels/plugin.py`
- Test: `backend/tests/test_custom_labels_plugin.py`

**Interfaces:**
- Consumes: `config_merge` validation from Task 2.
- Produces: rule field `matchMode: "values" | "all"` (optional, default
  `"values"`); `_build_state` emits `matchAll: bool` per prepared rule;
  `process()` treats `matchAll` rules as always-matching.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_custom_labels_plugin.py`:

```python
class TestMatchMode:
    def test_match_all_labels_every_product_without_ids(self, plugin):
        rule = {
            "id": "all1", "name": "All products", "isActive": True,
            "targetSlot": "custom_label_0", "matchField": "id",
            "matchMode": "all", "valueTemplate": "{brand} - All",
        }
        config = {"slotRules": [rule]}
        state = plugin.prepare_run(config, {"slotIds": {}}, _ctx())
        out = plugin.process(
            {"id": "zzz", "brand": "B"}, config, {"slotIds": {}}, _ctx(),
            state=state,
        )
        assert out["custom_label_0"] == "B - All"

    def test_match_all_beats_later_same_slot_rule(self, plugin):
        # g2 wins custom_label_0 because it comes first in the list —
        # the values-mode rule never gets a turn.
        rules = [
            {"id": "all1", "name": "All", "isActive": True,
             "targetSlot": "custom_label_0", "matchField": "id",
             "matchMode": "all", "valueTemplate": "ALL"},
            {"id": "v1", "name": "Vals", "isActive": True,
             "targetSlot": "custom_label_0", "matchField": "id",
             "valueTemplate": "VALS"},
        ]
        config = {"slotRules": rules}
        state = plugin.prepare_run(
            config, {"slotIds": {"v1": "x"}}, _ctx()
        )
        out = plugin.process({"id": "x"}, config, {"slotIds": {"v1": "x"}},
                             _ctx(), state=state)
        assert out["custom_label_0"] == "ALL"

    def test_match_all_supports_fallback_on_token_skip(self, plugin):
        rule = {
            "id": "all1", "name": "All", "isActive": True,
            "targetSlot": "custom_label_2", "matchField": "id",
            "matchMode": "all", "valueTemplate": "{brand}",
            "fallbackTemplate": "NOBRAND",
        }
        config = {"slotRules": [rule]}
        state = plugin.prepare_run(config, {"slotIds": {}}, _ctx())
        out = plugin.process({"id": "1"}, config, {"slotIds": {}}, _ctx(),
                             state=state)
        assert out["custom_label_2"] == "NOBRAND"

    def test_values_mode_default_unchanged(self, plugin):
        # rules without matchMode behave exactly as before: no ids -> no match
        rule = {k: v for k, v in CONFIG["slotRules"][0].items()}
        config = {"slotRules": [rule]}
        state = plugin.prepare_run(config, {"slotIds": {}}, _ctx())
        out = plugin.process({"id": "a", "brand": "B"}, config,
                             {"slotIds": {}}, _ctx(), state=state)
        assert "custom_label_1" not in out

    def test_rejects_bad_match_mode(self, plugin):
        bad = {"slotRules": [
            {**CONFIG["slotRules"][0], "matchMode": "sometimes"},
        ]}
        with pytest.raises(ValueError, match="matchMode"):
            plugin.validate_config(bad)

    def test_accepts_match_mode_all(self, plugin):
        ok = {"slotRules": [
            {**CONFIG["slotRules"][0], "matchMode": "all"},
        ]}
        plugin.validate_config(ok)  # registry not needed: 'all' skips matchField check
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_custom_labels_plugin.py -q`
Expected: FAIL — `KeyError: 'matchAll'` / no `matchMode` validation error.

- [ ] **Step 3: Implement**

`plugins/core/custom_labels/plugin.py`:

In `validate_config`, after the `matchField` check (after line
`_validate_registry_path(match_field, ...)`), insert:

```python
        if rule.get("matchMode", "values") not in ("values", "all"):
            raise ValueError(f"{path}: matchMode must be 'values' or 'all'")
```

In `_build_state`, change the `prepared.append({...})` block to:

```python
        prepared.append({
            "id": rule["id"],
            "targetSlot": rule["targetSlot"],
            "matchField": rule["matchField"],
            "matchAll": rule.get("matchMode") == "all",
            "ids": parse_id_list(raw if isinstance(raw, str) else ""),
            "template": compile_template(rule["valueTemplate"]),
            "fallback": compile_template(rule.get("fallbackTemplate") or ""),
        })
```

In `process`, change the match line to:

```python
                if not rule["matchAll"] and not matches(
                    product, rule["matchField"], rule["ids"]
                ):
                    continue
```

`plugins/core/custom_labels/plugin.json`:

Add a top-level key after `"data_scope"`:

```json
  "config_merge": {"slotRules": {"strategy": "union_by_key", "key": "id"}},
```

And inside `config_schema.properties.slotRules.items.properties`, after
`"matchField"`:

```json
            "matchMode": {
              "type": "string",
              "title": "Match mode",
              "enum": ["values", "all"],
              "default": "values"
            },
```

- [ ] **Step 4: Run tests + contract to verify they pass**

Run: `uv run pytest tests/test_custom_labels_plugin.py tests/test_plugin_contract.py -q`
Expected: PASS.

- [ ] **Step 5: Full backend check**

Run: `uv run ruff check . && uv run mypy . && uv run pytest -n auto`
Expected: all green (needs `TEST_DATABASE_URL`).

- [ ] **Step 6: Commit**

```bash
git add ../plugins/core/custom_labels/plugin.json ../plugins/core/custom_labels/plugin.py tests/test_custom_labels_plugin.py
git commit -m "feat(custom_labels): matchMode all + manifest union merge hint"
```

---

### Task 5: Frontend — `scopeMerge` helpers + equivalence test (gate, frontend half)

**Files:**
- Create: `frontend/src/features/customLabels/scopeMerge.ts`
- Create: `frontend/src/features/customLabels/scopeMerge.test.ts`
- Create: `frontend/src/types/scope.ts`

**Interfaces:**
- Consumes: `PluginScope` from `frontend/src/api/hooks.ts`.
- Produces (used by Tasks 6–9):
  - `type Tier = 'global' | 'client' | 'feed_source'` (in `types/scope.ts`)
  - `type SlotRule`, `type ScopedSlotRule = SlotRule & { origin: Tier }`
  - `mergeSlotRules(tiers: ReadonlyArray<{ tier: Tier; rules: ReadonlyArray<SlotRule> }>): ScopedSlotRule[]`
  - `groupBySlot(rules: ScopedSlotRule[]): Record<string, string[]>`
  - `mergeSlotIds(tiers): Record<string, { value: string; inherited: boolean }>`
  - `configTierChain(scope: PluginScope, routeContext: { clientId?: string }): Array<{ tier: Tier; scope: PluginScope }>`
  - `dataTierChain(scope: PluginScope, routeContext: { clientId?: string }): Array<{ tier: Tier; scope: PluginScope }>`
  - `editableConfigTier(scope: PluginScope): Tier | null`
  - `currentDataTier(scope: PluginScope): Tier | null`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/customLabels/scopeMerge.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import type { PluginScope } from '../../api/hooks';
import {
  configTierChain, currentDataTier, dataTierChain, editableConfigTier,
  groupBySlot, mergeSlotIds, mergeSlotRules, type SlotRule,
} from './scopeMerge';

// Shared equivalence fixture — keep in lockstep with
// backend/tests/test_config_merge.py (TestUnionByKey) and
// backend/tests/test_config_bundle.py (spec §1.2 gate).
const GLOBAL_RULES: SlotRule[] = [
  { id: 'g1', name: 'Global Mid', isActive: true, targetSlot: 'custom_label_1',
    matchField: 'id', valueTemplate: '{brand} - Mid', fallbackTemplate: '' },
  { id: 'g2', name: 'Global Top', isActive: true, targetSlot: 'custom_label_0',
    matchField: 'id', valueTemplate: '{brand} - Top', fallbackTemplate: '' },
];
const CLIENT_RULES: SlotRule[] = [
  { id: 'g1', name: 'Client Mid', isActive: true, targetSlot: 'custom_label_1',
    matchField: 'brand', valueTemplate: '{brand} - Client', fallbackTemplate: '' },
  { id: 'c2', name: 'Client Only', isActive: true, targetSlot: 'custom_label_0',
    matchField: 'id', valueTemplate: '{brand} - ClientOnly', fallbackTemplate: '' },
  { id: 'c3', name: 'Same Slot As G1', isActive: true, targetSlot: 'custom_label_1',
    matchField: 'id', valueTemplate: '{brand} - C3', fallbackTemplate: '' },
];

describe('mergeSlotRules (spec §1.2 gate)', () => {
  it('unions by id: client content wins, global positions first, client-only appended', () => {
    const merged = mergeSlotRules([
      { tier: 'global', rules: GLOBAL_RULES },
      { tier: 'client', rules: CLIENT_RULES },
    ]);
    expect(merged.map((r) => r.id)).toEqual(['g1', 'g2', 'c2', 'c3']);
    expect(merged.map((r) => r.name)).toEqual([
      'Client Mid', 'Global Top', 'Client Only', 'Same Slot As G1',
    ]);
    expect(merged.map((r) => r.origin)).toEqual([
      'client', 'global', 'client', 'client',
    ]);
  });

  it('per-slot winning order matches the backend (first match wins)', () => {
    const merged = mergeSlotRules([
      { tier: 'global', rules: GLOBAL_RULES },
      { tier: 'client', rules: CLIENT_RULES },
    ]);
    expect(groupBySlot(merged)).toEqual({
      custom_label_1: ['g1', 'c3'],
      custom_label_0: ['g2', 'c2'],
    });
  });

  it('client-only chain extends global without overrides', () => {
    const merged = mergeSlotRules([
      { tier: 'global', rules: GLOBAL_RULES },
      { tier: 'client', rules: [CLIENT_RULES[1]] },
    ]);
    expect(merged.map((r) => r.id)).toEqual(['g1', 'g2', 'c2']);
  });
});

describe('mergeSlotIds', () => {
  it('client-only values are inherited, current-tier values are not', () => {
    const merged = mergeSlotIds([
      { tier: 'client', ids: { r1: 'a', r2: 'x' } },
      { tier: 'feed_source', ids: { r2: 'y' } },
    ]);
    expect(merged).toEqual({
      r1: { value: 'a', inherited: true },
      r2: { value: 'y', inherited: false },
    });
  });

  it('single-tier chain has no inherited values', () => {
    const merged = mergeSlotIds([{ tier: 'client', ids: { r1: 'a' } }]);
    expect(merged).toEqual({ r1: { value: 'a', inherited: false } });
  });
});

describe('tier chains', () => {
  it('config chain: global page -> global only', () => {
    const scope: PluginScope = {};
    expect(configTierChain(scope, {})).toEqual([
      { tier: 'global', scope: {} },
    ]);
    expect(editableConfigTier(scope)).toBe('global');
  });

  it('config chain: client page -> global + client, editable client', () => {
    const scope: PluginScope = { clientId: 7 };
    expect(configTierChain(scope, { clientId: '7' })).toEqual([
      { tier: 'global', scope: {} },
      { tier: 'client', scope: { clientId: 7 } },
    ]);
    expect(editableConfigTier(scope)).toBe('client');
  });

  it('config chain: feed page -> global + client ancestor, read-only', () => {
    const scope: PluginScope = { feedSourceId: 3 };
    expect(configTierChain(scope, { clientId: '7' })).toEqual([
      { tier: 'global', scope: {} },
      { tier: 'client', scope: { clientId: 7 } },
    ]);
    expect(editableConfigTier(scope)).toBe(null);
  });

  it('data chain: global page -> empty (global not declared)', () => {
    expect(dataTierChain({}, {})).toEqual([]);
    expect(currentDataTier({})).toBe(null);
  });

  it('data chain: client page -> client only', () => {
    expect(dataTierChain({ clientId: 7 }, { clientId: '7' })).toEqual([
      { tier: 'client', scope: { clientId: 7 } },
    ]);
    expect(currentDataTier({ clientId: 7 })).toBe('client');
  });

  it('data chain: feed page -> client ancestor + feed current', () => {
    expect(dataTierChain({ feedSourceId: 3 }, { clientId: '7' })).toEqual([
      { tier: 'client', scope: { clientId: 7 } },
      { tier: 'feed_source', scope: { feedSourceId: 3 } },
    ]);
    expect(currentDataTier({ feedSourceId: 3 })).toBe('feed_source');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -- scopeMerge` (from `frontend/`)
Expected: FAIL — module `./scopeMerge` does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/types/scope.ts`:

```typescript
export type Tier = 'global' | 'client' | 'feed_source';
```

Create `frontend/src/features/customLabels/scopeMerge.ts`:

```typescript
import type { PluginScope } from '../../api/hooks';
import type { Tier } from '../../types/scope';

export type { Tier } from '../../types/scope';

export type SlotRule = {
  id: string;
  name: string;
  isActive: boolean;
  targetSlot: string;
  matchField: string;
  matchMode?: 'values' | 'all';
  valueTemplate: string;
  fallbackTemplate: string;
};

export type ScopedSlotRule = SlotRule & { origin: Tier };

/**
 * Union-by-id merge mirroring the runtime's manifest-declared
 * `config_merge` strategy (backend config_resolver._merge_list):
 * ancestor rules keep their positions, more-specific content wins by id,
 * unseen ids are appended in overlay order.
 */
export function mergeSlotRules(
  tiers: ReadonlyArray<{ tier: Tier; rules: ReadonlyArray<SlotRule> }>,
): ScopedSlotRule[] {
  const byId = new Map<string, ScopedSlotRule>();
  const order: string[] = [];
  for (const { tier, rules } of tiers) {
    for (const rule of rules) {
      if (!byId.has(rule.id)) order.push(rule.id);
      byId.set(rule.id, { ...rule, origin: tier });
    }
  }
  return order.map((id) => byId.get(id)!);
}

/** Per-slot id sequences — the runtime's per-slot winning order. */
export function groupBySlot(rules: ReadonlyArray<ScopedSlotRule>): Record<string, string[]> {
  const bySlot: Record<string, string[]> = {};
  for (const rule of rules) {
    (bySlot[rule.targetSlot] ??= []).push(rule.id);
  }
  return bySlot;
}

/**
 * Merge bulk-value dicts (ancestors first). `inherited` marks values that
 * come from an ancestor tier and are absent at the current tier.
 */
export function mergeSlotIds(
  tiers: ReadonlyArray<{ tier: Tier; ids: Readonly<Record<string, string>> }>,
): Record<string, { value: string; inherited: boolean }> {
  const current = tiers[tiers.length - 1]?.ids ?? {};
  const merged: Record<string, { value: string; inherited: boolean }> = {};
  for (const { ids } of tiers) {
    for (const [id, value] of Object.entries(ids)) {
      merged[id] = { value, inherited: !(id in current) };
    }
  }
  for (const [id, value] of Object.entries(current)) {
    merged[id] = { value, inherited: false };
  }
  return merged;
}

/** Manifest config_scope = ["global", "client"]: the feed tier is read-only. */
export function editableConfigTier(scope: PluginScope): Tier | null {
  if (scope.feedSourceId !== undefined) return null;
  if (scope.clientId !== undefined) return 'client';
  return 'global';
}

/** Manifest data_scope = ["client", "feed_source"]: no global data tier. */
export function currentDataTier(scope: PluginScope): Tier | null {
  if (scope.feedSourceId !== undefined) return 'feed_source';
  if (scope.clientId !== undefined) return 'client';
  return null;
}

/** Declared config tiers from global down to the URL tier, ancestors first. */
export function configTierChain(
  scope: PluginScope,
  routeContext: { clientId?: string },
): Array<{ tier: Tier; scope: PluginScope }> {
  const chain: Array<{ tier: Tier; scope: PluginScope }> = [
    { tier: 'global', scope: {} },
  ];
  const editable = editableConfigTier(scope);
  if (editable === 'client') {
    chain.push({ tier: 'client', scope: { clientId: scope.clientId! } });
  } else if (editable === null && routeContext.clientId) {
    chain.push({ tier: 'client', scope: { clientId: Number(routeContext.clientId) } });
  }
  return chain;
}

/** Declared data tiers from ancestors down to the URL tier, ancestors first. */
export function dataTierChain(
  scope: PluginScope,
  routeContext: { clientId?: string },
): Array<{ tier: Tier; scope: PluginScope }> {
  const current = currentDataTier(scope);
  if (current === null) return [];
  if (current === 'client') {
    return [{ tier: 'client', scope: { clientId: scope.clientId! } }];
  }
  const chain: Array<{ tier: Tier; scope: PluginScope }> = [];
  if (routeContext.clientId) {
    chain.push({ tier: 'client', scope: { clientId: Number(routeContext.clientId) } });
  }
  chain.push({ tier: 'feed_source', scope });
  return chain;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- scopeMerge && npm run typecheck`
Expected: PASS. **This completes the §1.2 equivalence gate together with Tasks
1+3. If this gate failed and could not be fixed, STOP — spec fallback
(backend resolved-view endpoint) applies; report back before continuing.**

- [ ] **Step 5: Commit**

```bash
git add src/features/customLabels/scopeMerge.ts src/features/customLabels/scopeMerge.test.ts src/types/scope.ts
git commit -m "feat(frontend): scopeMerge helpers mirroring runtime union merge"
```

---

### Task 6: Frontend — `ScopeBadge` + `ScopeContextBar` components

**Files:**
- Create: `frontend/src/components/ScopeBadge.tsx`
- Create: `frontend/src/components/ScopeContextBar.tsx`
- Create: `frontend/src/components/ScopeBadge.test.tsx`
- Create: `frontend/src/components/ScopeContextBar.test.tsx`
- Modify: `frontend/public/locales/en/common.json`
- Modify: `frontend/public/locales/de/common.json`

**Interfaces:**
- Consumes: `Tier` from `frontend/src/types/scope.ts` (Task 5).
- Produces:
  - `ScopeBadge({ tier: Tier; filled?: boolean })` — Badge with
    `data-testid="scope-badge-{tier}"`, colors global=violet/client=blue/feed_source=teal,
    tooltip from `common:scope.{tier}Hint`.
  - `ScopeContextBar({ current: Tier; configTiers: Tier[]; dataTiers: Tier[]; configLabel: string; dataLabel: string })`
    — sticky strip with `data-testid="scope-context-bar"`.

- [ ] **Step 1: Add i18n keys**

In `frontend/public/locales/en/common.json`, add after `"breadcrumbs"`:

```json
  "scope": {
    "global": "Global",
    "client": "Client",
    "feed_source": "Feed",
    "globalHint": "Shared across all clients",
    "clientHint": "Applies to one client",
    "feedHint": "Applies to this feed source",
    "viewing": "Viewing"
  },
  "pluginNames": {}
```

(`pluginNames.custom_labels` is filled in Task 11 — adding the empty object now
keeps the key structure stable.)

In `frontend/public/locales/de/common.json`, same location:

```json
  "scope": {
    "global": "Global",
    "client": "Client",
    "feed_source": "Feed",
    "globalHint": "Wird von allen Mandanten geteilt",
    "clientHint": "Gilt für einen Mandanten",
    "feedHint": "Gilt für diese Feed-Source",
    "viewing": "Ansicht"
  },
  "pluginNames": {}
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/components/ScopeBadge.test.tsx`:

```typescript
import { beforeAll, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../i18n';
import { render } from '../test/render';
import { ScopeBadge } from './ScopeBadge';

beforeAll(async () => {
  await i18n.loadNamespaces(['common']);
});

it('renders one badge per tier with its color and tooltip label', () => {
  render(
    <div>
      <ScopeBadge tier="global" />
      <ScopeBadge tier="client" />
      <ScopeBadge tier="feed_source" filled />
    </div>,
  );
  expect(screen.getByTestId('scope-badge-global')).toHaveTextContent('Global');
  expect(screen.getByTestId('scope-badge-client')).toHaveTextContent('Client');
  expect(screen.getByTestId('scope-badge-feed_source')).toHaveTextContent('Feed');
});
```

Create `frontend/src/components/ScopeContextBar.test.tsx`:

```typescript
import { beforeAll, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../i18n';
import { render } from '../test/render';
import { ScopeContextBar } from './ScopeContextBar';

beforeAll(async () => {
  await i18n.loadNamespaces(['common']);
});

it('shows the viewing tier plus declared config and data tiers', () => {
  render(
    <ScopeContextBar
      current="feed_source"
      configTiers={['global', 'client']}
      dataTiers={['client', 'feed_source']}
      configLabel="Slot rules"
      dataLabel="Bulk values"
    />,
  );
  const bar = screen.getByTestId('scope-context-bar');
  expect(bar).toHaveTextContent('Viewing');
  expect(bar).toHaveTextContent('Slot rules');
  expect(bar).toHaveTextContent('Bulk values');
  expect(screen.getAllByTestId('scope-badge-feed_source').length).toBeGreaterThan(0);
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm run test -- ScopeBadge` (from `frontend/`)
Expected: FAIL — modules do not exist.

- [ ] **Step 4: Implement**

Create `frontend/src/components/ScopeBadge.tsx`:

```tsx
import { Badge, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { Tier } from '../types/scope';

const TIER_COLORS: Record<Tier, string> = {
  global: 'violet',
  client: 'blue',
  feed_source: 'teal',
};

export function ScopeBadge({ tier, filled = false }: { tier: Tier; filled?: boolean }) {
  const { t } = useTranslation();
  return (
    <Tooltip label={t(`scope.${tier}Hint`)} position="top" withArrow>
      <Badge
        size="xs"
        variant={filled ? 'filled' : 'light'}
        color={TIER_COLORS[tier]}
        data-testid={`scope-badge-${tier}`}
      >
        {t(`scope.${tier}`)}
      </Badge>
    </Tooltip>
  );
}
```

Create `frontend/src/components/ScopeContextBar.tsx`:

```tsx
import { Group, Paper, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { ScopeBadge } from './ScopeBadge';
import type { Tier } from '../types/scope';

type Props = {
  current: Tier;
  configTiers: Tier[];
  dataTiers: Tier[];
  configLabel: string;
  dataLabel: string;
};

export function ScopeContextBar({ current, configTiers, dataTiers, configLabel, dataLabel }: Props) {
  const { t } = useTranslation();
  return (
    <Paper
      withBorder
      p="xs"
      mb="sm"
      data-testid="scope-context-bar"
      style={{ position: 'sticky', top: 4, zIndex: 1 }}
    >
      <Group gap="lg" wrap="nowrap">
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" c="dimmed">{t('scope.viewing')}</Text>
          <ScopeBadge tier={current} filled />
        </Group>
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" c="dimmed">{configLabel}</Text>
          {configTiers.map((tier) => (
            <ScopeBadge key={tier} tier={tier} filled={tier === current} />
          ))}
        </Group>
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" c="dimmed">{dataLabel}</Text>
          {dataTiers.length === 0 ? (
            <Text size="sm" c="dimmed">—</Text>
          ) : (
            dataTiers.map((tier) => (
              <ScopeBadge key={tier} tier={tier} filled={tier === current} />
            ))
          )}
        </Group>
      </Group>
    </Paper>
  );
}
```

- [ ] **Step 5: Run tests + typecheck to verify they pass**

Run: `npm run test -- Scope && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/components/ScopeBadge.tsx src/components/ScopeBadge.test.tsx src/components/ScopeContextBar.tsx src/components/ScopeContextBar.test.tsx public/locales/en/common.json public/locales/de/common.json
git commit -m "feat(frontend): scope badge + context bar components"
```

---

### Task 7: Frontend — `CustomLabelsUI` merged tier-chain view (rules tab)

**Files:**
- Rewrite: `frontend/src/features/customLabels/CustomLabelsUI.tsx`
- Modify: `frontend/src/features/customLabels/SortableRuleRow.tsx`
- Modify: `frontend/public/locales/en/customLabels.json`, `de/customLabels.json`
- Modify: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`

**Interfaces:**
- Consumes: `scopeMerge` helpers (Task 5), `ScopeBadge`/`ScopeContextBar` (Task 6),
  `usePluginConfig`/`usePluginData`/`useSavePluginConfig`/`useSavePluginData`/`useRegistryAttributes`
  from `frontend/src/api/hooks.ts`.
- Produces: `CustomLabelsUI` with merged view; `SortableRuleRow` gains a
  `badge?: ReactNode` prop. The old `resolveKindScope` export is REMOVED (nothing
  else imports it).

- [ ] **Step 1: Add i18n keys**

`frontend/public/locales/en/customLabels.json` — add these keys (keep existing):

```json
  "manageAtClient": "Manage slot rules at client level",
  "ruleInherited": "Managed at {{tier}} level — read-only here.",
```

`frontend/public/locales/de/customLabels.json`:

```json
  "manageAtClient": "Slot-Regeln auf Client-Ebene verwalten",
  "ruleInherited": "Wird auf {{tier}}-Ebene verwaltet — hier schreibgeschützt.",
```

- [ ] **Step 2: Update the component tests (failing first)**

Rewrite `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx` —
replace the fixture block and `renderUI` (lines ~27–70) with:

```tsx
const GLOBAL_CONFIG = {
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
const CLIENT_CONFIG = {
  slotRules: [
    {
      id: 'r3', name: 'Client Only', isActive: true, targetSlot: 'custom_label_2',
      matchField: 'id', valueTemplate: '{brand} - ClientOnly', fallbackTemplate: '',
    },
  ],
};
const DATA = { slotIds: { r1: 'a,b,c', r3: 'z' } };

function jsonResponseFor(url: string) {
  if (url.startsWith('/plugins/custom_labels/config') && url.includes('client_id=')) {
    return jsonResponse(CLIENT_CONFIG);
  }
  if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(GLOBAL_CONFIG);
  if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse(DATA);
  if (url.startsWith('/registry/attributes')) return jsonResponse([
    { name: 'id', kind: 'scalar', sub_fields: [] },
    { name: 'brand', kind: 'scalar', sub_fields: [] },
    { name: 'item_group_id', kind: 'scalar', sub_fields: [] },
  ]);
  return jsonResponse({});
}

function renderUI(
  scope: { clientId?: number; feedSourceId?: number },
  url = '/clients/1/feeds/1/plugins/custom_labels',
) {
  stubFetch(jsonResponseFor);
  const element = <CustomLabelsUI pluginId="custom_labels" scope={scope} />;
  const router = createMemoryRouter(
    [
      { path: '/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId', element },
      { path: '/clients/:clientId/plugins/:pluginId', element },
      { path: '/plugins/:pluginId', element },
    ],
    { initialEntries: [url] },
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
```

Then update the broken existing tests and add new ones. Replace the test
`renders one column per active rule with header metadata` with:

```tsx
  it('renders one column per active merged rule (global + client)', async () => {
    renderUI({ feedSourceId: 1 });
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument(); // global rule
    expect(screen.getByText('Client Only')).toBeInTheDocument(); // client rule
    expect(screen.getByText('custom_label_1')).toBeInTheDocument();
    expect(screen.getByText('custom_label_2')).toBeInTheDocument();
    expect(screen.getByText('Brand - ClientOnly')).toBeInTheDocument();
    expect(screen.queryByText('Off')).not.toBeInTheDocument(); // inactive hidden
  });
```

Replace `at feed-source tier fetches config at client scope …` with:

```tsx
  it('at feed tier fetches config at global AND client scope, data at feed scope', async () => {
    const captured: string[] = [];
    stubFetch((url) => {
      captured.push(url);
      return jsonResponseFor(url);
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
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText('Mid Funnel'));
    const configUrls = captured.filter((u) => u.includes('/config'));
    expect(configUrls).toEqual([
      '/plugins/custom_labels/config',
      '/plugins/custom_labels/config?client_id=1',
    ]);
    expect(captured.find((u) => u.includes('/data'))).toBe(
      '/plugins/custom_labels/data?feed_source_id=1',
    );
  });
```

Update the remaining existing tests minimally:

- In every existing test that builds its own `stubFetch((url) => { ... })`
  handler referencing the old `CONFIG` constant, replace the whole handler
  callback with `stubFetch((url) => jsonResponseFor(url))` (or capture URLs via
  `stubFetch((url) => { captured.push(url); return jsonResponseFor(url); })`
  where the test asserts on URLs).

- In `at client tier both config and data are fetched with client_id`, change
  the config assertion to expect both URLs:

```tsx
    const configUrls = captured.filter((u) => u.includes('/config'));
    expect(configUrls).toEqual([
      '/plugins/custom_labels/config',
      '/plugins/custom_labels/config?client_id=7',
    ]);
```

- In both `at global tier the bulk-IDs tab is unavailable …` tests (there are
  two near-duplicates), change the config capture to expect exactly one URL:

```tsx
    expect(captured.filter((u) => u.includes('/config'))).toEqual([
      '/plugins/custom_labels/config',
    ]);
```

- `at feed-source tier the slot-rules tab is read-only …` keeps its
  expectations (no Add rule, readonly hint) unchanged.

and add these new tests:

```tsx
  it('at client tier shows global rules with a Global badge and keeps them read-only', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.getAllByTestId('scope-badge-global').length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Mid Funnel'));
    expect(screen.getByLabelText(/name/i, { selector: 'input' })).toBeDisabled();
    // Client rule stays editable.
    await userEvent.click(screen.getByText('Client Only'));
    expect(screen.getByLabelText(/name/i, { selector: 'input' })).toBeEnabled();
  });

  it('at client tier save writes only client-origin rules', async () => {
    const puts: { url: string; body: unknown }[] = [];
    stubFetch((url, init) => {
      if (url.includes('/config?client_id=1') && init?.method === 'PUT') {
        puts.push({ url, body: JSON.parse(String(init.body)) });
        return jsonResponse(CLIENT_CONFIG);
      }
      return jsonResponseFor(url);
    });
    const router = createMemoryRouter(
      [
        {
          path: '/clients/:clientId/plugins/:pluginId',
          element: <CustomLabelsUI pluginId="custom_labels" scope={{ clientId: 1 }} />,
        },
      ],
      { initialEntries: ['/clients/1/plugins/custom_labels'] },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    await screen.findByText('Client Only');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Client Only'));
    await userEvent.type(screen.getByLabelText(/name/i, { selector: 'input' }), '!');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await screen.findByText(/saved/i);
    const payload = puts[0].body as { slotRules: { id: string }[] };
    expect(payload.slotRules.map((r) => r.id)).toEqual(['r3']);
  });

  it('at feed tier the read-only hint links to the client-level page', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    const link = screen.getByRole('link', { name: /manage slot rules at client level/i });
    expect(link).toHaveAttribute('href', '/clients/1/plugins/custom_labels');
  });
```

(If `stubFetch` does not expose `init` for method/body, check
`frontend/src/test/fetch.ts` and adapt: it must support reading `init` — assert on
the captured PUT body. Keep the assertion semantics.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm run test -- CustomLabelsUI`
Expected: FAIL (badges/links/multi-fetch missing).

- [ ] **Step 4: Implement the rewrite**

Rewrite `frontend/src/features/customLabels/CustomLabelsUI.tsx` completely:

```tsx
import { useMemo, useState } from 'react';
import {
  Anchor, Badge, Button, Card, Group, Select, Stack, Switch, Tabs, Text, TextInput, Textarea,
} from '@mantine/core';
import {
  DndContext, PointerSensor, closestCenter, useSensor, useSensors,
} from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { Link, useBlocker, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  usePluginConfig, usePluginData, useRegistryAttributes, useSavePluginConfig,
  useSavePluginData, type PluginScope,
} from '../../api/hooks';
import { ErrorState, LoadingState } from '../../components/StateViews';
import { ScopeBadge } from '../../components/ScopeBadge';
import { ScopeContextBar } from '../../components/ScopeContextBar';
import { notifySuccess } from '../../app/notifications';
import { parseIdList, renderPreview } from './ids';
import { SortableRuleRow } from './SortableRuleRow';
import {
  configTierChain, currentDataTier, dataTierChain, editableConfigTier,
  mergeSlotIds, mergeSlotRules, type ScopedSlotRule, type SlotRule, type Tier,
} from './scopeMerge';

const TARGET_SLOTS = [
  'custom_label_0', 'custom_label_1', 'custom_label_2', 'custom_label_3', 'custom_label_4',
];

function newRule(name: string, origin: Tier): ScopedSlotRule {
  return {
    id: typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `r_${Math.random().toString(36).slice(2)}`,
    name,
    isActive: true,
    targetSlot: 'custom_label_0',
    matchField: 'id',
    matchMode: 'values',
    valueTemplate: '',
    fallbackTemplate: '',
    origin,
  };
}

function slotRulesOf(payload: unknown): SlotRule[] {
  return (payload as { slotRules?: SlotRule[] } | undefined)?.slotRules ?? [];
}

function slotIdsOf(payload: unknown): Record<string, string> {
  return (payload as { slotIds?: Record<string, string> } | undefined)?.slotIds ?? {};
}

export function CustomLabelsUI({ pluginId, scope }: { pluginId: string; scope: PluginScope }) {
  const { t } = useTranslation('customLabels');
  const { t: tCommon } = useTranslation('common');
  const routeContext = useParams();

  const editableTier = editableConfigTier(scope);
  const rulesReadOnly = editableTier === null;
  const configChain = configTierChain(scope, routeContext);
  const dataChain = dataTierChain(scope, routeContext);
  const viewingTier: Tier = scope.feedSourceId !== undefined
    ? 'feed_source'
    : scope.clientId !== undefined
      ? 'client'
      : 'global';

  const clientConfigScope = configChain.find((c) => c.tier === 'client')?.scope;
  const clientDataScope = dataChain.find((c) => c.tier === 'client')?.scope;
  const feedDataScope = dataChain.find((c) => c.tier === 'feed_source')?.scope;
  const saveConfigScope: PluginScope = editableTier === 'client'
    ? { clientId: scope.clientId! }
    : {};
  const saveDataScope = feedDataScope ?? clientDataScope;

  const globalConfig = usePluginConfig(pluginId, {});
  const clientConfig = usePluginConfig(pluginId, clientConfigScope, clientConfigScope !== undefined);
  const clientData = usePluginData(pluginId, clientDataScope, clientDataScope !== undefined);
  const feedData = usePluginData(pluginId, feedDataScope, feedDataScope !== undefined);
  const saveConfig = useSavePluginConfig(pluginId, saveConfigScope);
  const saveData = useSavePluginData(pluginId, saveDataScope);
  const attributes = useRegistryAttributes();

  const [rules, setRules] = useState<ScopedSlotRule[] | null>(null);
  const [slotIds, setSlotIds] = useState<Record<string, string> | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const serverRules = useMemo(
    () =>
      mergeSlotRules(
        configChain.map(({ tier }) => ({
          tier,
          rules: tier === 'global' ? slotRulesOf(globalConfig.data) : slotRulesOf(clientConfig.data),
        })),
      ),
    [configChain, globalConfig.data, clientConfig.data],
  );
  const serverIds = useMemo(
    () =>
      mergeSlotIds(
        dataChain.map(({ tier }) => ({
          tier,
          ids: tier === 'client' ? slotIdsOf(clientData.data) : slotIdsOf(feedData.data),
        })),
      ),
    [dataChain, clientData.data, feedData.data],
  );

  const effectiveRules = rules ?? serverRules;
  const effectiveIds = slotIds
    ?? Object.fromEntries(Object.entries(serverIds).map(([id, v]) => [id, v.value]));
  const dirtyRules = rules !== null;
  const dirtyIds = slotIds !== null;
  const dirty = dirtyRules || dirtyIds;

  const activeRules = effectiveRules.filter((r) => r.isActive);
  const selected = effectiveRules.find((r) => r.id === selectedId) ?? null;
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

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
    if (editableTier === null) return;
    const payloadRules = effectiveRules
      .filter((r) => r.origin === editableTier)
      .map(({ origin: _origin, ...rest }) => rest);
    await saveConfig.mutateAsync({ slotRules: payloadRules });
    setRules(null);
    notifySuccess(t('configSaved'));
  }

  async function saveIds() {
    if (saveDataScope === undefined) return;
    await saveData.mutateAsync({ slotIds: effectiveIds });
    setSlotIds(null);
    notifySuccess(t('idsSaved'));
  }

  const configPending = globalConfig.isPending
    || (clientConfigScope !== undefined && clientConfig.isPending);
  const dataPending = dataChain.length > 0
    && ((clientDataScope !== undefined && clientData.isPending)
      || (feedDataScope !== undefined && feedData.isPending));
  if (configPending || dataPending) return <LoadingState />;
  const anyError = globalConfig.isError
    || (clientConfigScope !== undefined && clientConfig.isError)
    || (clientDataScope !== undefined && clientData.isError)
    || (feedDataScope !== undefined && feedData.isError);
  if (anyError) {
    return (
      <ErrorState
        onRetry={() => {
          void globalConfig.refetch();
          if (clientConfigScope !== undefined) void clientConfig.refetch();
          if (clientDataScope !== undefined) void clientData.refetch();
          if (feedDataScope !== undefined) void feedData.refetch();
        }}
      />
    );
  }

  const idsUnavailable = dataChain.length === 0;
  const initialTab = idsUnavailable ? 'rules' : 'ids';
  const ruleEditable = (rule: ScopedSlotRule) => !rulesReadOnly && rule.origin === editableTier;

  return (
    <Stack gap="sm">
      <ScopeContextBar
        current={viewingTier}
        configTiers={configChain.map((c) => c.tier)}
        dataTiers={dataChain.map((c) => c.tier)}
        configLabel={t('tabs.slotRules')}
        dataLabel={t('tabs.bulkIds')}
      />
      <Tabs defaultValue={initialTab} keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="ids" disabled={idsUnavailable}>{t('tabs.bulkIds')}</Tabs.Tab>
          <Tabs.Tab value="rules">{t('tabs.slotRules')}</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="ids" pt="sm">
          {idsUnavailable ? (
            <Text c="dimmed">{t('idsUnavailable')}</Text>
          ) : (
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
                    const inherited = serverIds[rule.id]?.inherited === true
                      && raw === serverIds[rule.id].value;
                    return (
                      <Stack key={rule.id} gap={4} miw={280} w={280}>
                        <Group gap="xs">
                          <Text size="sm" fw={600}>{rule.name}</Text>
                          <Badge size="xs" variant="light">{rule.targetSlot}</Badge>
                        </Group>
                        <Group gap={4}>
                          <Text size="xs" c="dimmed">{rule.matchField}</Text>
                          {inherited && (
                            <Badge size="xs" variant="light" color="teal">
                              {t('inheritedFrom', { tier: tCommon('scope.client') })}
                            </Badge>
                          )}
                        </Group>
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
          )}
        </Tabs.Panel>

        <Tabs.Panel value="rules" pt="sm">
          <Stack gap="sm">
            {rulesReadOnly && (
              <Text data-testid="rules-readonly-hint" size="sm" c="dimmed">
                {t('rulesReadOnly')}{' '}
                {routeContext.clientId && (
                  <Anchor
                    component={Link}
                    to={`/clients/${routeContext.clientId}/plugins/${pluginId}`}
                  >
                    {t('manageAtClient')}
                  </Anchor>
                )}
              </Text>
            )}
            <Group justify="space-between">
              {!rulesReadOnly && (
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
              )}
              {!rulesReadOnly && (
                <Button
                  variant="light"
                  onClick={() => {
                    const rule = newRule(t('newRuleName'), editableTier!);
                    setRules([...effectiveRules, rule]);
                    setSelectedId(rule.id);
                  }}
                >
                  {t('addRule')}
                </Button>
              )}
            </Group>
            <Group align="flex-start" gap="md" wrap="nowrap">
              <Card withBorder miw={320} w={320}>
                <DndContext
                  sensors={sensors}
                  collisionDetection={closestCenter}
                  onDragEnd={({ active, over }) => {
                    if (rulesReadOnly) return;
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
                          disabled={!ruleEditable(rule)}
                          badge={rule.origin !== editableTier
                            ? <ScopeBadge tier={rule.origin} />
                            : undefined}
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
                    {!ruleEditable(selected) && (
                      <Group gap="xs">
                        <ScopeBadge tier={selected.origin} />
                        <Text size="xs" c="dimmed">
                          {t('ruleInherited', { tier: tCommon(`scope.${selected.origin}`) })}
                        </Text>
                      </Group>
                    )}
                    <TextInput
                      label={t('fields.name')}
                      value={selected.name}
                      disabled={!ruleEditable(selected)}
                      onChange={(e) => patchSelected({ name: e.currentTarget.value })}
                    />
                    <Switch
                      label={t('fields.isActive')}
                      checked={selected.isActive}
                      disabled={!ruleEditable(selected)}
                      onChange={(e) => patchSelected({ isActive: e.currentTarget.checked })}
                    />
                    <Select
                      label={t('fields.targetSlot')}
                      data={TARGET_SLOTS}
                      value={selected.targetSlot}
                      disabled={!ruleEditable(selected)}
                      onChange={(v) => patchSelected({ targetSlot: v ?? 'custom_label_0' })}
                    />
                    <TextInput
                      label={t('fields.matchField')}
                      value={selected.matchField}
                      disabled={!ruleEditable(selected)}
                      onChange={(e) => patchSelected({ matchField: e.currentTarget.value })}
                      list="match-field-suggestions"
                    />
                    <datalist id="match-field-suggestions">
                      {(attributes.data ?? []).flatMap((attr) =>
                        [attr.name, ...(attr.sub_fields ?? []).map((s) => `${attr.name}.${s.name}`)]
                      ).map((s) => (
                        <option key={s} value={s} />
                      ))}
                    </datalist>
                    <TextInput
                      label={t('fields.valueTemplate')}
                      description={t('fields.valueTemplateHint')}
                      value={selected.valueTemplate}
                      disabled={!ruleEditable(selected)}
                      onChange={(e) => patchSelected({ valueTemplate: e.currentTarget.value })}
                    />
                    <TextInput
                      label={t('fields.fallbackTemplate')}
                      description={t('fields.fallbackHint')}
                      value={selected.fallbackTemplate}
                      disabled={!ruleEditable(selected)}
                      onChange={(e) => patchSelected({ fallbackTemplate: e.currentTarget.value })}
                    />
                  </Stack>
                </Card>
              )}
            </Group>
          </Stack>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

export default CustomLabelsUI;
```

Add the i18n key used above (both locales): en
`"inheritedFrom": "Inherited from {{tier}}"`, de
`"inheritedFrom": "Geerbt von {{tier}}"`.

Then update `frontend/src/features/customLabels/SortableRuleRow.tsx` — add the
`badge` prop and pass `origin`-typed rule. Replace the whole file:

```tsx
import { Badge, Group, Switch, Text, UnstyledButton } from '@mantine/core';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';

export type SlotRuleSummary = {
  id: string;
  name: string;
  targetSlot: string;
  isActive: boolean;
};

export function SortableRuleRow({
  rule,
  selected,
  disabled = false,
  badge,
  onSelect,
  onToggleActive,
}: {
  rule: SlotRuleSummary;
  selected: boolean;
  disabled?: boolean;
  badge?: ReactNode;
  onSelect: () => void;
  onToggleActive: (isActive: boolean) => void;
}) {
  const { t } = useTranslation('customLabels');
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({
    id: rule.id,
    disabled,
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
        style={{ cursor: disabled ? 'default' : 'grab' }}
      >
        ⠿
      </UnstyledButton>
      <Text size="sm" style={{ flex: 1 }}>
        {rule.name}
      </Text>
      {badge}
      <Badge size="xs" variant="light">
        {rule.targetSlot}
      </Badge>
      <Switch
        checked={rule.isActive}
        disabled={disabled}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => onToggleActive(e.currentTarget.checked)}
      />
    </Group>
  );
}
```

(`ScopedSlotRule` structurally satisfies `SlotRuleSummary`.)

- [ ] **Step 5: Run tests + typecheck**

Run: `npm run test -- CustomLabelsUI && npm run typecheck`
Expected: PASS. (If `rules`/`effectiveRules` drag tests from the old suite fail
because reordering is now disabled with inherited rows present, keep the
global-page reorder behavior — at global tier all rows are editable.)

- [ ] **Step 6: Commit**

```bash
git add src/features/customLabels/ src/public/locales 2>/dev/null || git add src/features/customLabels public/locales
git commit -m "feat(frontend): merged tier-chain view for custom labels"
```

---

### Task 8: Frontend — match-field Combobox, match modes, active-switch clarity

**Files:**
- Create: `frontend/src/features/customLabels/MatchFieldCombobox.tsx`
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx` (rule editor card)
- Modify: `frontend/src/features/customLabels/SortableRuleRow.tsx`
- Modify: `frontend/public/locales/en/customLabels.json`, `de/customLabels.json`
- Modify: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`

**Interfaces:**
- Consumes: `RegistryAttribute` from `frontend/src/api/types.ts`;
  `patchSelected`/`ruleEditable` from Task 7's component.
- Produces: `MatchFieldCombobox({ value: string; onChange: (v: string) => void; attributes: RegistryAttribute[]; disabled?: boolean })`.

- [ ] **Step 1: Add i18n keys**

`frontend/public/locales/en/customLabels.json` — merge into existing keys:

```json
  "inactive": "inactive",
  "matchMode": {
    "label": "Match mode",
    "values": "Match value list",
    "all": "Match all products"
  },
  "fields": {
    "isActiveHint": "Inactive rules are skipped during runs and hidden from bulk value lists.",
    "matchFieldHint": "Product field matched against the value list. Pick from the registry or type a custom path.",
    "matchFieldPlaceholder": "Pick or type a field",
    "matchFieldCustom": "Use custom field \"{{value}}\""
  }
```

(Merge the new `fields.*` keys into the existing `"fields"` object — do not
duplicate the object.)

`frontend/public/locales/de/customLabels.json`:

```json
  "inactive": "inaktiv",
  "matchMode": {
    "label": "Match-Modus",
    "values": "Werteliste abgleichen",
    "all": "Alle Produkte treffen"
  },
  "fields": {
    "isActiveHint": "Inaktive Regeln werden in Läufen übersprungen und in Bulk-Wertelisten ausgeblendet.",
    "matchFieldHint": "Produktfeld, das mit der Werteliste abgeglichen wird. Aus der Registry wählen oder eigenen Pfad eingeben.",
    "matchFieldPlaceholder": "Feld wählen oder eingeben",
    "matchFieldCustom": "Eigenes Feld \"{{value}}\" verwenden"
  }
```

- [ ] **Step 2: Write the failing tests**

Add to `CustomLabelsUI.test.tsx` (fixtures from Task 7 still active; the global
`r1` has `matchField: 'id'`):

```tsx
  it('match field is a searchable combobox offering registry fields and custom entry', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Client Only'));
    const input = screen.getByLabelText(/match field/i);
    await userEvent.clear(input);
    await userEvent.type(input, 'brand');
    await userEvent.click(screen.getByRole('option', { name: 'brand' }));
    expect(screen.getByLabelText(/match field/i)).toHaveValue('brand');
  });

  it('rule editor offers the two match modes', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Client Only'));
    expect(screen.getByRole('radio', { name: /match value list/i })).toBeChecked();
    await userEvent.click(screen.getByRole('radio', { name: /match all products/i }));
    expect(screen.getByRole('radio', { name: /match all products/i })).toBeChecked();
  });

  it('inactive rows are dimmed and badged', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    expect(screen.getByText('inactive')).toBeInTheDocument();
  });
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm run test -- CustomLabelsUI`
Expected: FAIL — no combobox/radio roles yet.

- [ ] **Step 4: Implement**

Create `frontend/src/features/customLabels/MatchFieldCombobox.tsx` (Mantine 9
Combobox, grouped + free-text entry per https://mantine.dev/llms/core-combobox.md):

```tsx
import { useEffect, useMemo, useState } from 'react';
import { Combobox, InputBase, useCombobox } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { RegistryAttribute } from '../../api/types';

export function MatchFieldCombobox({
  value,
  onChange,
  attributes,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  attributes: RegistryAttribute[];
  disabled?: boolean;
}) {
  const { t } = useTranslation('customLabels');
  const combobox = useCombobox({
    onDropdownClose: () => combobox.resetSelectedOption(),
  });
  const [search, setSearch] = useState(value);
  useEffect(() => setSearch(value), [value]);

  const groups = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const attr of attributes) {
      const items = [attr.name, ...(attr.sub_fields ?? []).map((s) => `${attr.name}.${s.name}`)];
      map.set(attr.name, items);
    }
    return map;
  }, [attributes]);

  const query = search.trim().toLowerCase();
  const exact = [...groups.values()].some((items) => items.includes(search));
  const visibleGroups = [...groups.entries()]
    .map(([attr, items]) => [attr, items.filter((i) => i.toLowerCase().includes(query))] as const)
    .filter(([, items]) => items.length > 0);

  return (
    <Combobox
      store={combobox}
      onOptionSubmit={(val) => {
        onChange(val);
        combobox.closeDropdown();
      }}
    >
      <Combobox.Target>
        <InputBase
          label={t('fields.matchField')}
          description={t('fields.matchFieldHint')}
          placeholder={t('fields.matchFieldPlaceholder')}
          disabled={disabled}
          value={search}
          rightSection={<Combobox.Chevron />}
          rightSectionPointerEvents="none"
          onChange={(event) => {
            setSearch(event.currentTarget.value);
            onChange(event.currentTarget.value);
            combobox.openDropdown();
            combobox.updateSelectedOptionIndex();
          }}
          onClick={() => combobox.openDropdown()}
          onFocus={() => combobox.openDropdown()}
          onBlur={() => {
            combobox.closeDropdown();
            setSearch(value);
          }}
        />
      </Combobox.Target>
      <Combobox.Dropdown>
        <Combobox.Options mah={280} style={{ overflowY: 'auto' }}>
          {visibleGroups.map(([attr, items]) => (
            <Combobox.Group key={attr} label={attr}>
              {items.map((item) => (
                <Combobox.Option key={item} value={item} active={item === value}>
                  {item}
                </Combobox.Option>
              ))}
            </Combobox.Group>
          ))}
          {!exact && (
            <Combobox.Empty>{t('fields.matchFieldCustom', { value: search })}</Combobox.Empty>
          )}
        </Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
}
```

In `CustomLabelsUI.tsx` rule editor card, replace the `TextInput` + `datalist`
match-field block with:

```tsx
                    <MatchFieldCombobox
                      value={selected.matchField}
                      onChange={(matchField) => patchSelected({ matchField })}
                      attributes={attributes.data ?? []}
                      disabled={!ruleEditable(selected)}
                    />
```

and directly above it insert the match-mode control:

```tsx
                    <SegmentedControl
                      aria-label={t('matchMode.label')}
                      value={selected.matchMode ?? 'values'}
                      onChange={(mode) => patchSelected({ matchMode: mode as 'values' | 'all' })}
                      disabled={!ruleEditable(selected)}
                      data={[
                        { value: 'values', label: t('matchMode.values') },
                        { value: 'all', label: t('matchMode.all') },
                      ]}
                    />
```

Add `SegmentedControl` to the `@mantine/core` import and
`import { MatchFieldCombobox } from './MatchFieldCombobox';`.

Give the Active switch its description — change the editor's `Switch` to:

```tsx
                    <Switch
                      label={t('fields.isActive')}
                      description={t('fields.isActiveHint')}
                      checked={selected.isActive}
                      disabled={!ruleEditable(selected)}
                      onChange={(e) => patchSelected({ isActive: e.currentTarget.checked })}
                    />
```

In `SortableRuleRow.tsx`, dim inactive rows and badge them — change the row
`Group` and the badge area:

```tsx
    <Group
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: rule.isActive ? undefined : 0.55,
      }}
      gap="xs"
      px="xs"
      py={4}
      onClick={onSelect}
      data-selected={selected || undefined}
    >
```

and after the `targetSlot` Badge add:

```tsx
      {!rule.isActive && (
        <Badge size="xs" variant="light" color="gray">
          {t('inactive')}
        </Badge>
      )}
```

- [ ] **Step 5: Run tests + typecheck**

Run: `npm run test -- CustomLabelsUI && npm run typecheck`
Expected: PASS (SegmentedControl renders `radio` roles; the combobox is an
`InputBase` labeled by `t('fields.matchField')`).

- [ ] **Step 6: Commit**

```bash
git add src/features/customLabels public/locales
git commit -m "feat(frontend): match-field combobox, match modes, active clarity"
```

---

### Task 9: Frontend — bulk values tab: dynamic labels + match-all summary

**Files:**
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx` (bulk panel)
- Modify: `frontend/public/locales/en/customLabels.json`, `de/customLabels.json`
- Modify: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`

**Interfaces:**
- Consumes: Task 7's bulk panel structure, `serverIds`, `effectiveIds`;
  Task 8's `matchMode` field.
- Produces: bulk panel that renders a value textarea (relabeled per match
  field) OR a "controlled by rule" summary per rule.

- [ ] **Step 1: Add i18n keys**

`frontend/public/locales/en/customLabels.json` — add:

```json
  "bulk": {
    "productIds": "Product IDs",
    "valuesFor": "Values for {{field}}",
    "controlledByRule": "Controlled by rule — no value list needed.",
    "allProductsGet": "Every product gets: {{preview}}",
    "switchToValueList": "Switch to value list"
  },
```

`frontend/public/locales/de/customLabels.json`:

```json
  "bulk": {
    "productIds": "Produkt-IDs",
    "valuesFor": "Werte für {{field}}",
    "controlledByRule": "Wird von der Regel gesteuert — keine Werteliste nötig.",
    "allProductsGet": "Jedes Produkt erhält: {{preview}}",
    "switchToValueList": "Zur Werteliste wechseln"
  },
```

- [ ] **Step 2: Write the failing tests**

Add to `CustomLabelsUI.test.tsx` (helpers `jsonResponse`, `stubFetch`,
`createMemoryRouter` are already imported there):

```tsx
  function renderFeedWithConfig(config: unknown) {
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(config);
      if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse({ slotIds: {} });
      if (url.startsWith('/registry/attributes')) return jsonResponse([
        { name: 'id', kind: 'scalar', sub_fields: [] },
        { name: 'brand', kind: 'scalar', sub_fields: [] },
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
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
  }

  it('all-mode rules show a controlled-by summary instead of the value textarea', async () => {
    renderFeedWithConfig({
      slotRules: [
        { id: 'a1', name: 'All Products', isActive: true, targetSlot: 'custom_label_0',
          matchField: 'id', matchMode: 'all', valueTemplate: '{brand} - All',
          fallbackTemplate: '' },
      ],
    });
    expect(await screen.findByText(/every product gets: brand - all/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/all products ids/i)).not.toBeInTheDocument();
    // feed tier: config is read-only -> no override button
    expect(
      screen.queryByRole('button', { name: /switch to value list/i }),
    ).not.toBeInTheDocument();
  });

  it('values-mode rules relabel the textarea to the match field', async () => {
    renderFeedWithConfig({
      slotRules: [
        { id: 'v1', name: 'By Brand', isActive: true, targetSlot: 'custom_label_1',
          matchField: 'brand', matchMode: 'values', valueTemplate: '{brand} - Mid',
          fallbackTemplate: '' },
      ],
    });
    expect(await screen.findByLabelText(/values for brand/i)).toBeInTheDocument();
  });
```

And a client-tier override test:

```tsx
  it('at client tier an all-mode rule offers the switch-to-value-list override', async () => {
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse({
        slotRules: [
          { id: 'a1', name: 'All Products', isActive: true, targetSlot: 'custom_label_0',
            matchField: 'id', matchMode: 'all', valueTemplate: '{brand} - All',
            fallbackTemplate: '' },
        ],
      });
      if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse({ slotIds: {} });
      if (url.startsWith('/registry/attributes')) return jsonResponse([
        { name: 'id', kind: 'scalar', sub_fields: [] },
      ]);
      return jsonResponse({});
    });
    const router = createMemoryRouter(
      [
        {
          path: '/clients/:clientId/plugins/:pluginId',
          element: <CustomLabelsUI pluginId="custom_labels" scope={{ clientId: 1 }} />,
        },
      ],
      { initialEntries: ['/clients/1/plugins/custom_labels'] },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    const override = await screen.findByRole('button', { name: /switch to value list/i });
    await userEvent.click(override);
    expect(await screen.findByLabelText(/all products ids/i)).toBeInTheDocument();
  });
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm run test -- CustomLabelsUI`
Expected: FAIL — summary/labels missing.

- [ ] **Step 4: Implement**

In `CustomLabelsUI.tsx`:

1. Add `Collapse, Paper` to the `@mantine/core` import.
2. Add a rule-patch helper next to `patchSelected`:

```tsx
  function patchRule(id: string, patch: Partial<SlotRule>) {
    setRules(effectiveRules.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }
```

3. Replace the body of the `activeRules.map((rule) => { ... })` block inside the
bulk panel (the whole `return (<Stack key={rule.id} ...>` from Task 7) with:

```tsx
                  {activeRules.map((rule) => {
                    const allMode = rule.matchMode === 'all';
                    const raw = effectiveIds[rule.id] ?? '';
                    const count = parseIdList(raw).size;
                    const inherited = serverIds[rule.id]?.inherited === true
                      && raw === serverIds[rule.id].value;
                    return (
                      <Stack key={rule.id} gap={4} miw={280} w={280}>
                        <Group gap="xs" justify="space-between" wrap="nowrap">
                          <Group gap="xs" wrap="nowrap">
                            <Text size="sm" fw={600}>{rule.name}</Text>
                            <Badge size="xs" variant="light">{rule.targetSlot}</Badge>
                          </Group>
                          {inherited && (
                            <Badge size="xs" variant="light" color="teal">
                              {t('inheritedFrom', { tier: tCommon('scope.client') })}
                            </Badge>
                          )}
                        </Group>
                        <Text size="xs" c="dimmed">{rule.matchField}</Text>
                        <Text size="xs" c="dimmed">{renderPreview(rule.valueTemplate)}</Text>
                        <Collapse in={!allMode}>
                          <Stack gap={4}>
                            <Textarea
                              label={rule.matchField === 'id'
                                ? t('bulk.productIds')
                                : t('bulk.valuesFor', { field: rule.matchField })}
                              aria-label={rule.matchField === 'id'
                                ? `${rule.name} ids`
                                : `${rule.name} values`}
                              minRows={10}
                              autosize
                              value={raw}
                              onChange={(e) =>
                                setSlotIds({ ...effectiveIds, [rule.id]: e.currentTarget.value })}
                              placeholder={t('idsPlaceholder')}
                            />
                            <Text size="xs" c="dimmed">{t('idCount', { count })}</Text>
                          </Stack>
                        </Collapse>
                        <Collapse in={allMode}>
                          <Paper withBorder p="xs" data-testid={`all-mode-${rule.id}`}>
                            <Stack gap={4}>
                              <Text size="sm" c="dimmed">{t('bulk.controlledByRule')}</Text>
                              <Text size="sm" fw={600}>
                                {t('bulk.allProductsGet', {
                                  preview: renderPreview(rule.valueTemplate),
                                })}
                              </Text>
                              {editableTier !== null && (
                                <Button
                                  variant="subtle"
                                  size="xs"
                                  onClick={() => patchRule(rule.id, { matchMode: 'values' })}
                                >
                                  {t('bulk.switchToValueList')}
                                </Button>
                              )}
                            </Stack>
                          </Paper>
                        </Collapse>
                      </Stack>
                    );
                  })}
```

(Clicking the override marks the CONFIG dirty — the change is persisted with
the Save button on the Slot rules tab; the unsaved-changes blocker guards
navigation in between.)

- [ ] **Step 5: Run tests + typecheck**

Run: `npm run test -- CustomLabelsUI && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/features/customLabels public/locales
git commit -m "feat(frontend): mode-aware bulk value editors"
```

---

### Task 10: Frontend — description, "How it works" accordion, help drawer

**Files:**
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx`
- Modify: `frontend/public/locales/en/customLabels.json`, `de/customLabels.json`
- Modify: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`

**Interfaces:**
- Produces: inline description (`data-testid="labelizer-description"`), an
  Accordion with four items, and a right-side `Drawer` opened via an
  `ActionIcon` (`aria-label` = `t('help.open')`).

- [ ] **Step 1: Add i18n keys**

`frontend/public/locales/en/customLabels.json` — add:

```json
  "description": "Labelizer fills Google Shopping's custom_label_0–4 slots from an ordered list of slot rules: a rule matches products (by value list or all products), renders a value template, and the first match per slot wins.",
  "howItWorks": {
    "concepts": {
      "question": "What are slot rules?",
      "answer": "Each rule targets one custom_label slot. Rules are evaluated top to bottom; the first matching rule with a non-empty template result fills the slot."
    },
    "matchModes": {
      "question": "Match value list vs. match all products?",
      "answer": "Value-list rules label products whose match field equals one of the listed values. Match-all rules label every product — no value list needed."
    },
    "templates": {
      "question": "How do value templates work?",
      "answer": "Use {field} tokens like {brand} - Mid Funnel. If a token resolves empty the rule is skipped; a fallback template covers that case."
    },
    "scopes": {
      "question": "Where do rules and bulk values live?",
      "answer": "Slot rules live at Global or Client level and merge client-over-global. Bulk values live at Client or Feed level; a feed pins inherited values on its first save."
    }
  },
  "help": {
    "open": "Open user guide",
    "title": "Labelizer user guide",
    "gettingStarted": "Getting started",
    "gettingStartedBody": "1. Add a rule under Slot rules and pick a target slot. 2. Choose a match mode — paste bulk IDs or let all products match. 3. Write a value template. 4. Save, then run the pipeline to see the labels in the export."
  },
```

`frontend/public/locales/de/customLabels.json` — add:

```json
  "description": "Labelizer füllt Googles custom_label_0–4-Slots aus einer geordneten Liste von Slot-Regeln: Eine Regel matcht Produkte (per Werteliste oder alle Produkte), rendert eine Wertvorlage — der erste Treffer pro Slot gewinnt.",
  "howItWorks": {
    "concepts": {
      "question": "Was sind Slot-Regeln?",
      "answer": "Jede Regel zielt auf einen custom_label-Slot. Regeln werden von oben nach unten ausgewertet; die erste passende Regel mit nicht-leerem Vorlagenergebnis füllt den Slot."
    },
    "matchModes": {
      "question": "Werteliste abgleichen oder alle Produkte?",
      "answer": "Wertelisten-Regeln labeln Produkte, deren Match-Feld einem der gelisteten Werte entspricht. „Alle Produkte“-Regeln labeln jedes Produkt — ohne Werteliste."
    },
    "templates": {
      "question": "Wie funktionieren Wertvorlagen?",
      "answer": "Verwende {field}-Tokens wie {brand} - Mid Funnel. Löst ein Token leer auf, wird die Regel übersprungen; eine Fallback-Vorlage deckt diesen Fall ab."
    },
    "scopes": {
      "question": "Wo leben Regeln und Bulk-Werte?",
      "answer": "Slot-Regeln leben auf Global- oder Client-Ebene und mergen Client-über-Global. Bulk-Werte leben auf Client- oder Feed-Ebene; ein Feed pinnt geerbte Werte beim ersten Speichern."
    }
  },
  "help": {
    "open": "Benutzerhandbuch öffnen",
    "title": "Labelizer-Benutzerhandbuch",
    "gettingStarted": "Erste Schritte",
    "gettingStartedBody": "1. Unter „Slot-Regeln“ eine Regel anlegen und einen Ziel-Slot wählen. 2. Match-Modus wählen — Bulk-IDs einfügen oder alle Produkte matchen lassen. 3. Wertvorlage schreiben. 4. Speichern und die Pipeline ausführen, um die Labels im Export zu sehen."
  },
```

- [ ] **Step 2: Write the failing tests**

Add to `CustomLabelsUI.test.tsx`:

```tsx
  it('shows the description, how-it-works accordion, and opens the guide drawer', async () => {
    renderUI({ feedSourceId: 1 });
    expect(await screen.findByTestId('labelizer-description')).toHaveTextContent(/labelizer/i);
    expect(screen.getByText(/what are slot rules\?/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /open user guide/i }));
    expect(await screen.findByText(/labelizer user guide/i)).toBeInTheDocument();
    expect(screen.getByText(/getting started/i)).toBeInTheDocument();
  });
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm run test -- CustomLabelsUI`
Expected: FAIL.

- [ ] **Step 4: Implement**

In `CustomLabelsUI.tsx`:

1. Extend imports:

```tsx
import { Accordion, ActionIcon, Collapse, Drawer, Paper } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { IconHelp } from '@tabler/icons-react';
```

(Merge `Accordion`, `ActionIcon`, `Drawer` into the existing single
`@mantine/core` import.)

2. Inside the component, after the `useSensors` line, add:

```tsx
  const [helpOpened, { open: openHelp, close: closeHelp }] = useDisclosure(false);
```

3. In the returned JSX, directly below `<ScopeContextBar ... />`, insert:

```tsx
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Text size="sm" c="dimmed" data-testid="labelizer-description">
          {t('description')}
        </Text>
        <ActionIcon variant="light" aria-label={t('help.open')} onClick={openHelp}>
          <IconHelp size={16} />
        </ActionIcon>
      </Group>
      <Accordion>
        <Accordion.Item value="concepts">
          <Accordion.Control>{t('howItWorks.concepts.question')}</Accordion.Control>
          <Accordion.Panel>{t('howItWorks.concepts.answer')}</Accordion.Panel>
        </Accordion.Item>
        <Accordion.Item value="matchModes">
          <Accordion.Control>{t('howItWorks.matchModes.question')}</Accordion.Control>
          <Accordion.Panel>{t('howItWorks.matchModes.answer')}</Accordion.Panel>
        </Accordion.Item>
        <Accordion.Item value="templates">
          <Accordion.Control>{t('howItWorks.templates.question')}</Accordion.Control>
          <Accordion.Panel>{t('howItWorks.templates.answer')}</Accordion.Panel>
        </Accordion.Item>
        <Accordion.Item value="scopes">
          <Accordion.Control>{t('howItWorks.scopes.question')}</Accordion.Control>
          <Accordion.Panel>{t('howItWorks.scopes.answer')}</Accordion.Panel>
        </Accordion.Item>
      </Accordion>
      <Drawer
        opened={helpOpened}
        onClose={closeHelp}
        title={t('help.title')}
        position="right"
        size="lg"
      >
        <Stack gap="sm">
          {(['concepts', 'matchModes', 'templates', 'scopes'] as const).map((key) => (
            <Stack key={key} gap={4}>
              <Text fw={600} size="sm">{t(`howItWorks.${key}.question`)}</Text>
              <Text size="sm" c="dimmed">{t(`howItWorks.${key}.answer`)}</Text>
            </Stack>
          ))}
          <Stack gap={4}>
            <Text fw={600} size="sm">{t('help.gettingStarted')}</Text>
            <Text size="sm" c="dimmed">{t('help.gettingStartedBody')}</Text>
          </Stack>
        </Stack>
      </Drawer>
```

- [ ] **Step 5: Run tests + typecheck**

Run: `npm run test -- CustomLabelsUI && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/features/customLabels public/locales
git commit -m "feat(frontend): labelizer description, accordion, and guide drawer"
```

---

### Task 11: Frontend — rename "Custom Labels" to "Labelizer" (UI only)

**Files:**
- Modify: `frontend/public/locales/en/common.json`, `de/common.json`
- Modify: `frontend/src/app/AppShell.tsx`
- Modify: `frontend/src/features/plugin/PluginPage.tsx`
- Modify: `frontend/src/i18n/i18n.test.tsx`

**Interfaces:**
- Produces: nav label and page title resolve through
  `t(`pluginNames.${plugin.id}`, { defaultValue: <manifest label> })`.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/i18n/i18n.test.tsx`:

```tsx
  it('resolves plugin display names with manifest fallback', async () => {
    await i18n.changeLanguage('en');
    expect(i18n.t('pluginNames.custom_labels')).toBe('Labelizer');
    expect(i18n.t('pluginNames.rules', { defaultValue: 'Rules' })).toBe('Rules');
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- i18n`
Expected: FAIL — `pluginNames.custom_labels` returns the key, not "Labelizer".

- [ ] **Step 3: Implement**

`frontend/public/locales/en/common.json` — set the (already existing, empty)
`pluginNames` object to:

```json
  "pluginNames": { "custom_labels": "Labelizer" }
```

`frontend/public/locales/de/common.json` — same (brand name stays untranslated):

```json
  "pluginNames": { "custom_labels": "Labelizer" }
```

`frontend/src/app/AppShell.tsx` — in `pluginItems.map((plugin) => { ... })`,
change the `label` prop of the plugin `NavLink` from:

```tsx
                    label={scope?.menu_item ?? plugin.name}
```

to:

```tsx
                    label={t(`pluginNames.${plugin.id}`, {
                      defaultValue: scope?.menu_item ?? plugin.name,
                    })}
```

`frontend/src/features/plugin/PluginPage.tsx` — add a common-namespace `t`:

```tsx
  const { t: tCommon } = useTranslation('common');
```

and change the title element from:

```tsx
      <Title order={3}>{plugin.name}</Title>
```

to:

```tsx
      <Title order={3}>{tCommon(`pluginNames.${plugin.id}`, { defaultValue: plugin.name })}</Title>
```

- [ ] **Step 4: Run tests + typecheck**

Run: `npm run test && npm run typecheck`
Expected: PASS (full frontend suite — this is the rename's regression net).

- [ ] **Step 5: Commit**

```bash
git add src/app/AppShell.tsx src/features/plugin/PluginPage.tsx src/i18n/i18n.test.tsx public/locales
git commit -m "feat(frontend): display name Labelizer for custom_labels"
```

---

### Task 12: Docs, ADR 0005, and full verification

**Files:**
- Create: `docs/decisions/0005-labelizer-scope-merge-and-value-pinning.md`
- Modify: `AGENTS.md` (documentation map)
- Modify: `frontend/docs/plugin-uis.md`
- Modify: `backend/docs/plugins.md`
- Modify: `backend/docs/architecture.md`

**Interfaces:**
- Consumes: everything above.
- Produces: documentation for the merged view, `config_merge` extension point,
  match modes, and the recorded pin-on-save trade-off.

- [ ] **Step 1: Create ADR 0005**

Create `docs/decisions/0005-labelizer-scope-merge-and-value-pinning.md`:

```markdown
# ADR-0005: Labelizer Scope Merge and Value Pinning

## Status
Accepted

## Context
The generic three-tier scope merge (`app/staging/config_resolver.py`) replaces
list values wholesale: a client-tier `slotRules` array would fully erase global
rules at run time, while the Labelizer UI needs to show global and client rules
merged. Spec review (2026-09-05) mandated a verification test proving the
frontend merge and the runtime resolution produce the same effective
`slotRules` (same ids, same per-slot winning order), with a backend
resolved-view endpoint as fallback if they diverge.

## Decision
1. **Manifest-declared list merge strategy.** Plugins may declare
   `"config_merge": {"<key>": {"strategy": "union_by_key", "key": "<id>"}}`.
   The resolver then unions lists by key: ancestor rules keep their positions,
   more-specific content wins by key, unseen entries are appended. Keys without
   a hint keep wholesale replacement.
2. **Equivalence gate.** Backend and frontend tests pin the same fixture
   (global + client rules) and assert identical merged id order and per-slot
   winning order. If the gate cannot be satisfied, the merge moves to a
   backend resolved-view endpoint instead of the frontend.
3. **Bulk-value pinning (owner-accepted trade-off).** The bulk-values tab saves
   the merged value dict to the current tier. Consequence: **ancestor-tier
   bulk-value edits stop propagating to a feed after its first save** — saved
   inherited values are pinned to the feed tier. Run-time overlay semantics make
   the effective values identical at save time.

## Consequences
- `custom_labels` with global + client configs now runs global rules
  (overridden per id) instead of dropping them; `config_hash` changes
  accordingly — intended behavior.
- The `config_merge` manifest key is a new, opt-in extension point validated by
  `parse_manifest`.
- Other plugins are unaffected (default semantics unchanged).
```

- [ ] **Step 2: Update the AGENTS.md documentation map**

In `AGENTS.md`, after the `0004-plugin-frontend-error-isolation.md` line, add:

```markdown
- `docs/decisions/0005-labelizer-scope-merge-and-value-pinning.md` — ADR: Labelizer scope merge + bulk-value pinning
```

- [ ] **Step 3: Update frontend docs**

Append to `frontend/docs/plugin-uis.md`:

```markdown
## Custom component scope behavior (custom_labels / "Labelizer")

- **Merged tier view:** `CustomLabelsUI` fetches every declared config tier
  reachable from the URL (global always, client when known) and merges
  `slotRules` union-by-id — identical to the run-time merge declared via the
  manifest's `config_merge` (see ADR-0005). Inherited rules render with a
  ScopeBadge and are read-only; saving writes only the editable tier's rules.
- **Bulk values:** data tiers merge per rule id; inherited values are badged.
  Saving pins the merged dict to the current tier (ADR-0005).
- **Rule modes:** `matchMode: "values"` (explicit value list, textarea relabels
  to the match field) or `"all"` (every product matches; the bulk tab shows a
  "controlled by rule" summary).
- **Help UI:** inline description, a "How it works" accordion, and a user-guide
  drawer per plugin page.
- **Nav entries for multi-scope plugins:** `AppShell` derives the target from
  the manifest scopes — feed-scoped plugins link to
  `` ${feedBase}/plugins/{id} `` (nav item hidden without a feed selected),
  client-scoped plugins to `/clients/:c/plugins/{id}`, otherwise
  `/plugins/{id}`. The label resolves through `pluginNames.*` i18n with the
  manifest `frontend.menu_item` as fallback (display name "Labelizer" for
  `custom_labels`).
```

- [ ] **Step 4: Update backend docs**

Append to `backend/docs/plugins.md` (manifest section):

```markdown
### Optional `config_merge` (list merge strategy)

```json
"config_merge": {"slotRules": {"strategy": "union_by_key", "key": "id"}}
```

Declared keys merge by union: ancestor entries keep their positions, more
specific tiers override entries with the same key, unseen entries are appended.
Undeclared keys keep the default wholesale-replacement semantics. `custom_labels`
uses this for `slotRules`; its rules additionally support
`matchMode: "values" | "all"` (`"all"` matches every product without a value
list).
```

Append to `backend/docs/architecture.md`, at the end of the
"Three-Tier Scope Merge" section:

```markdown
Lists are replaced wholesale by default. A manifest may declare
`config_merge` per config key to switch a list to `union_by_key` semantics
(ancestor order preserved, more-specific entries override by key, new entries
appended) — used by `custom_labels.slotRules` (ADR-0005).
```

- [ ] **Step 5: Full verification**

From `backend/`:

```bash
uv run ruff check .
uv run mypy .
uv run pytest -n auto
```

From `frontend/`:

```bash
npm run test
npm run typecheck
npm run build
```

Expected: all green. `uv run pytest tests/test_plugin_contract.py` is included
in `pytest -n auto`.

- [ ] **Step 6: Commit**

```bash
git add ../docs/decisions/0005-labelizer-scope-merge-and-value-pinning.md ../AGENTS.md ../frontend/docs/plugin-uis.md docs/plugins.md docs/architecture.md
git commit -m "docs: labelizer merged scope view, config_merge, ADR-0005"
```

---

## Plan self-review (executed 2026-09-05)

- **Spec coverage:** §1 merged view → Tasks 1/3/5/7; §1.1 runtime merge → Tasks
  1–3; §1.2 gate → Tasks 1/3/5 (+ stop-rule in Tasks 3 and 5); §2 scope UX →
  Task 6; §3 combobox → Task 8; §4 rule modes → Tasks 4/8/9; §5 active switch
  → Task 8; §6 help → Task 10; §7 rename → Task 11; §8 nav docs + ADR 0005 +
  docs-map update → Task 12. No gaps.
- **Placeholder scan:** no TBD/TODO/"add error handling" steps; every code step
  carries full code.
- **Type consistency:** `Tier` lives in `src/types/scope.ts` (Task 5) and is
  re-exported by `scopeMerge.ts`; `ScopeBadge`/`ScopeContextBar` (Task 6)
  import it from `types/scope`; `SlotRule`/`ScopedSlotRule` originate in
  `scopeMerge.ts` (Task 5) and are used by Tasks 7–9; `MatchFieldCombobox`
  props (Task 8) match its call site in `CustomLabelsUI`; backend
  `_resolve_declared(scopes, maps, merge_hints)` signature is identical in
  Tasks 1 and 3.
