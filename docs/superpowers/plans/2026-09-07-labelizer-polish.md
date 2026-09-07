# Labelizer Polish Cycle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every still-open minor and recommendation from the two labelizer final reviews — dead code, stale-behavior preview hook, a11y/i18n gaps, weak tests, duplicated fixtures.

**Architecture:** Pure polish — no API surface, route, schema, or migration changes. Backend: delete test-only `merge_scopes`, redundant `preview.__annotations__` lines, and one dead manifest check; dedupe fixtures and the plugin-module load. Frontend: `mergeSlotIds` gains `sourceTier` (inherited badge derives its tier instead of hardcoding client), `usePreview` clears stale error/result, a11y and plural fixes. Docs: `docs/decisions.md` entries only.

**Tech Stack:** FastAPI + pytest (backend, `uv run pytest -n auto`, real PostgreSQL via `TEST_DATABASE_URL`), React 19 + Mantine 9.5.2 + vitest + RTL (frontend).

**Spec:** `docs/superpowers/specs/2026-09-07-labelizer-polish-design.md`

## Global Constraints

- No comments in production code (rationale comments in test files follow the existing style of those files).
- All UI strings via `t()`; en+de i18n trees identical.
- TDD per task where a behavior changes; dead-code deletions prove safety via the existing suite staying green.
- Gates — backend: from `backend/`, `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto`; frontend: from `frontend/`, `npm test -- --run && npm run typecheck && npm run build`.
- Lint gate: `uvx ruff check <touched files>` exits 0; `uvx mypy <touched backend files>` adds zero new errors vs. the pre-existing baseline.
- Run backend and frontend suites sequentially, never concurrently (load-induced jsdom flakes).
- RTL lesson: `rerender` REMOUNTS in this repo — prop-change scenarios use stateful harnesses (see `DraftProbe`).
- Work on `main` (session convention); commit after every green gate.
- Mantine 9.5.2: `Collapse` uses `expanded` (NOT `in`). Do not "fix" this.

---

### Task 1: Delete `merge_scopes`; hoist mid-file import

**Files:**
- Modify: `backend/app/staging/config_resolver.py:47-57` (delete `merge_scopes`)
- Modify: `backend/tests/test_config_merge.py` (rewrite `TestMergeScopes`, hoist import at line 33)
- Modify: `backend/tests/test_custom_labels_delta.py:1-18` (rewrite the two `merge_scopes` tests)

**Interfaces:**
- Consumes: `_resolve_declared(scopes: list[str], maps: dict[str, dict[str, Any]], merge_hints: dict[str, Any] | None) -> dict[str, Any]` (existing, `config_resolver.py:71`) — the internal function production calls at `config_resolver.py:143,148`.
- Produces: nothing consumed by later tasks. `merge_scopes` is REMOVED from the module surface.

**Operator amendment (2026-09-07):** the original Step 6 (delete the `preview.__annotations__` lines in `plugins/core/custom_labels/plugin.py`) was **refuted by experiment** — removing the lines breaks route registration (`PydanticUserError`; 4 preview tests fail). Under `from __future__ import annotations` the def-signature annotations are unresolved string ForwardRefs (`PreviewRequest` is class-local to `register_routes`), and the runtime assignments replace them with real objects. The lines are load-bearing and stay; the cycle-2 "dead `__annotations__` line" minor was a mis-review. Task 8 records this in `docs/decisions.md`.

- [ ] **Step 1: Rewrite `TestMergeScopes` to use `_resolve_declared` (test-first)**

In `backend/tests/test_config_merge.py`, replace the whole file header + `TestMergeScopes` class (lines 1-30) and hoist the mid-file import (line 33) so the file starts:

```python
from app.staging.config_resolver import _resolve_declared

ALL_SCOPES = ["global", "client", "feed_source"]


class TestScopeMerge:
    def _resolve(self, maps):
        return _resolve_declared(ALL_SCOPES, maps, None)

    def test_global_only(self):
        assert self._resolve({"global": {"a": 1}}) == {"a": 1}

    def test_client_overrides_global_per_key(self):
        assert self._resolve({
            "global": {"a": 1, "b": 2}, "client": {"b": 3},
        }) == {"a": 1, "b": 3}

    def test_feed_source_wins(self):
        assert self._resolve({
            "global": {"a": 1, "b": 2, "c": 3},
            "client": {"c": 30},
            "feed_source": {"a": 10},
        }) == {"a": 10, "b": 2, "c": 30}

    def test_non_dict_values_replace_wholesale(self):
        assert self._resolve({
            "global": {"rules": [1, 2, 3]}, "client": {"rules": [9]},
        }) == {"rules": [9]}

    def test_dict_values_merge_recursively(self):
        assert self._resolve({
            "global": {"limits": {"title": 150, "desc": 5000}},
            "client": {"limits": {"title": 100}},
        }) == {"limits": {"title": 100, "desc": 5000}}

    def test_missing_at_specific_scope_falls_through(self):
        assert self._resolve({
            "global": {"a": 1}, "feed_source": {"b": 2},
        }) == {"a": 1, "b": 2}

    def test_type_flip_replaces(self):
        assert self._resolve({
            "global": {"a": {"nested": 1}}, "client": {"a": "flat"},
        }) == {"a": "flat"}
```

Delete the old line 33 (`from app.staging.config_resolver import _resolve_declared`) — it is now at the top. Keep everything from the `# Shared equivalence fixture` comment (old line 35) downward unchanged.

- [ ] **Step 2: Run the rewritten tests — they must PASS against the current code**

Run: `cd backend && uv run pytest tests/test_config_merge.py -v`
Expected: PASS (the rewrite is mechanical; `_resolve_declared` already implements these semantics).

- [ ] **Step 3: Rewrite the two `merge_scopes` tests in `test_custom_labels_delta.py`**

Replace lines 3 and 7-18 of `backend/tests/test_custom_labels_delta.py`:

```python
from app.staging.config_resolver import _resolve_declared
from app.staging.hashing import content_hash


class TestSlotIdsPerKeyMerge:
    def test_feed_source_overrides_only_its_rule(self):
        resolved = _resolve_declared(
            ["global", "client", "feed_source"],
            {
                "client": {"slotIds": {"r1": "a\nb", "r2": "x\ny"}},
                "feed_source": {"slotIds": {"r2": "z"}},
            },
            None,
        )
        assert resolved["slotIds"] == {"r1": "a\nb", "r2": "z"}

    def test_client_overrides_global_only_its_rule(self):
        resolved = _resolve_declared(
            ["global", "client"],
            {
                "global": {"slotIds": {"r1": "a", "r2": "x"}},
                "client": {"slotIds": {"r1": "b"}},
            },
            None,
        )
        assert resolved["slotIds"] == {"r1": "b", "r2": "x"}
```

(Leave `_bundle` and `TestConfigHashSensitivity` below unchanged.)

- [ ] **Step 4: Delete `merge_scopes` from `config_resolver.py`**

Delete lines 47-58 of `backend/app/staging/config_resolver.py` (the `merge_scopes` function plus its surrounding blank lines, leaving exactly one blank line between `_merge_list` and `_SCOPE_ORDER`):

```python
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
```

Keep `_merge_dicts` and `_merge_list` — `_resolve_declared` uses them.

- [ ] **Step 5: Prove no production code imports `merge_scopes`**

Run: `rg -n "merge_scopes" backend/ plugins/`
Expected: matches ONLY in docs (`docs/`, `backend/docs/`) if any — zero in `backend/app/`, `backend/tests/`, `plugins/`. If a test still references it, fix that test to use `_resolve_declared` as in Steps 1/3.

- [ ] **Step 6: Run the focused backend tests for all touched areas**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest tests/test_custom_labels_preview.py tests/test_config_merge.py tests/test_custom_labels_delta.py -v`
Expected: PASS — the preview route is untouched but stays green (config resolver change must not affect it).

- [ ] **Step 7: Full backend gate + lint**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto`
Expected: 882 passed (the pre-cycle baseline; no tests removed or added in this task).

Run: `uvx ruff check app/staging/config_resolver.py tests/test_config_merge.py tests/test_custom_labels_delta.py`
Expected: exit 0.

Run: `uvx mypy app/staging/config_resolver.py`
Expected: zero new errors vs. baseline.

- [ ] **Step 8: Commit**

```bash
git add backend/app/staging/config_resolver.py backend/tests/test_config_merge.py backend/tests/test_custom_labels_delta.py
git commit -m "refactor(custom_labels): drop test-only merge_scopes"
```

---

### Task 2: Shared equivalence fixture + single plugin-module load + stale comment

**Files:**
- Create: `backend/tests/labels_equivalence.py`
- Create: `backend/tests/labels_plugin_module.py`
- Modify: `backend/tests/test_config_merge.py` (import fixture from the shared module)
- Modify: `backend/tests/test_custom_labels_plugin.py` (preamble, `TestMergedStateWinningOrder`, stale comment at line 528)
- Modify: `backend/tests/test_config_bundle.py` (inline fixture at lines ~210-229 → imports)
- Modify: `backend/tests/test_custom_labels_preview.py` (preamble at lines 22-30)

**Interfaces:**
- Produces: `tests.labels_equivalence` exports `GLOBAL_SLOT_RULES`, `CLIENT_SLOT_RULES`, `UNION_HINTS`, `MERGED_SLOT_RULES`, `EXPECTED_MERGED_IDS`, `EXPECTED_MERGED_NAMES`, `EXPECTED_BY_SLOT` — consumed by three test files (Task 2 itself) and available for future suites.
- Produces: `tests.labels_plugin_module` exports `labels_plugin` (the single loaded `plugins/core/custom_labels/plugin.py` module). Both custom_labels test files import it instead of loading the file themselves.

- [ ] **Step 1: Create the shared fixture module**

Create `backend/tests/labels_equivalence.py`:

```python
"""Shared slot-rules equivalence fixture — keep in lockstep with
frontend/src/features/customLabels/scopeMerge.test.ts (spec §1.2 gate)."""

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

MERGED_SLOT_RULES = [
    CLIENT_SLOT_RULES[0],
    GLOBAL_SLOT_RULES[1],
    CLIENT_SLOT_RULES[1],
    CLIENT_SLOT_RULES[2],
]
EXPECTED_MERGED_IDS = ["g1", "g2", "c2", "c3"]
EXPECTED_MERGED_NAMES = ["Client Mid", "Global Top", "Client Only", "Same Slot As G1"]
EXPECTED_BY_SLOT = {
    "custom_label_1": ["g1", "c3"],
    "custom_label_0": ["g2", "c2"],
}
```

(`MERGED_SLOT_RULES` is the union-by-id result: the client g1 overrides the global g1 in place, ancestors keep their positions, unseen ids append — matching `config_resolver._merge_list`.)

- [ ] **Step 2: Create the shared plugin loader (kills the double module load)**

Create `backend/tests/labels_plugin_module.py`:

```python
"""Single shared load of plugins/core/custom_labels/plugin.py for tests."""

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "custom_labels_plugin",
    Path(__file__).resolve().parents[2] / "plugins/core/custom_labels/plugin.py",
)
assert _spec is not None and _spec.loader is not None
labels_plugin = importlib.util.module_from_spec(_spec)
sys.modules["custom_labels_plugin"] = labels_plugin
_spec.loader.exec_module(labels_plugin)
```

Previously `test_custom_labels_plugin.py` and `test_custom_labels_preview.py` each ran `exec_module` on the same file under two names — the module body executed twice per pytest process. Now it executes once.

- [ ] **Step 3: Point `test_custom_labels_plugin.py` at the shared loader and fixture**

In `backend/tests/test_custom_labels_plugin.py`:
1. Replace the preamble (lines 3-18: the `import importlib.util`, `import sys`, `from pathlib import Path`, the `_spec = ...` block, and `sys.modules[...] = _plugin`) with:

```python
from tests.labels_equivalence import EXPECTED_BY_SLOT, MERGED_SLOT_RULES
from tests.labels_plugin_module import labels_plugin as _plugin
```

(Keep the `_plugin.X` bindings — `compile_template = _plugin.compile_template` etc. — unchanged. Remove `import importlib.util` / `import sys` / `from pathlib import Path` only if nothing else in the file uses them; `uvx ruff check` in Step 8 will catch any now-unused import.)

2. In `TestMergedStateWinningOrder`, delete the inline `MERGED_CONFIG` ClassVar (the hand-synced copy at lines ~481-496 — the class has a single test method) and rewrite the class to use the shared constants:

```python
class TestMergedStateWinningOrder:
    """Spec §1.2 gate: state built from the union-merged config must preserve
    the fixture order of labels_equivalence / frontend scopeMerge.test.ts."""

    def test_state_per_slot_order_matches_merged_list(self, plugin):
        state = plugin.prepare_run({"slotRules": MERGED_SLOT_RULES}, {"slotIds": {}}, _ctx())
        by_slot: dict[str, list[str]] = {}
        for rule in state["rules"]:
            by_slot.setdefault(rule["targetSlot"], []).append(rule["id"])
        assert by_slot == EXPECTED_BY_SLOT
```

3. Fix the stale comment at line 528 — it references fixture ids (`g2`) that no longer appear in that test's rule list. Replace:

```python
        # g2 wins custom_label_0 because it comes first in the list —
        # the values-mode rule never gets a turn.
```

with:

```python
        # all1 wins custom_label_0 because it comes first in the list —
        # the values-mode rule never gets a turn.
```

- [ ] **Step 4: Point `test_custom_labels_preview.py` at the shared loader**

In `backend/tests/test_custom_labels_preview.py`, replace the preamble block (lines 22-30: `_spec = importlib.util.spec_from_file_location("custom_labels_plugin_preview", ...)`, `_labels_module = ...`, `sys.modules[...]`, `exec_module`) with:

```python
from tests.labels_plugin_module import labels_plugin as _labels_module
```

Keep `CustomLabelsPlugin = _labels_module.CustomLabelsPlugin` and `evaluate_rules = _labels_module.evaluate_rules` unchanged. Remove `import importlib.util`, `import sys`, `from pathlib import Path` if unused elsewhere in the file (ruff will catch).

- [ ] **Step 5: Point `test_config_merge.py` at the shared fixture**

In `backend/tests/test_config_merge.py`, add this import at the TOP of the file, directly under the existing `from app.staging.config_resolver import _resolve_declared` (do NOT leave a mid-file import — that is the exact defect this cycle removes):

```python
from tests.labels_equivalence import (
    EXPECTED_BY_SLOT,
    EXPECTED_MERGED_IDS,
    EXPECTED_MERGED_NAMES,
    GLOBAL_SLOT_RULES,
    CLIENT_SLOT_RULES,
    UNION_HINTS,
)
```

Then DELETE the inline fixture block (the lockstep comment, `GLOBAL_SLOT_RULES`, `CLIENT_SLOT_RULES`, `UNION_HINTS` — everything left of the old fixture section) so the `TestUnionByKey` class follows the imports directly. Update its first test to use the expected constants:

```python
class TestUnionByKey:
    def test_hinted_list_unions_by_id_in_ancestor_order(self):
        merged = _resolve_declared(
            ["global", "client"],
            {"global": {"slotRules": GLOBAL_SLOT_RULES},
             "client": {"slotRules": CLIENT_SLOT_RULES}},
            UNION_HINTS,
        )
        rules = merged["slotRules"]
        assert [r["id"] for r in rules] == EXPECTED_MERGED_IDS
        assert [r["name"] for r in rules] == EXPECTED_MERGED_NAMES
        by_slot: dict[str, list[str]] = {}
        for rule in rules:
            by_slot.setdefault(rule["targetSlot"], []).append(rule["id"])
        assert by_slot == EXPECTED_BY_SLOT
```

(`test_client_only_config_extends_global`, `test_ancestor_only_config_passes_through`, `test_without_hint_lists_still_replace_wholesale`, `test_unknown_strategy_replaces_wholesale`, `test_non_dict_items_are_appended` keep their own inline literals — they test partial/malformed variants, not the lockstep fixture.)

- [ ] **Step 6: Point `test_config_bundle.py` at the shared fixture**

In `backend/tests/test_config_bundle.py`, inside `test_bundle_slotrules_union_by_id_matches_frontend`, delete the inline `global_rules` and `client_rules` literals (lines ~210-229) and the lockstep comment above them, and add at the top of the file (with the other imports):

```python
from tests.labels_equivalence import (
    EXPECTED_MERGED_IDS,
    EXPECTED_MERGED_NAMES,
    GLOBAL_SLOT_RULES,
    CLIENT_SLOT_RULES,
)
```

Then use `GLOBAL_SLOT_RULES` / `CLIENT_SLOT_RULES` in the two `PluginConfig(...)` rows and replace the trailing assertions:

```python
    rules = bundle["instances"][0]["resolved_config"]["slotRules"]
    assert [r["id"] for r in rules] == EXPECTED_MERGED_IDS
    assert [r["name"] for r in rules] == EXPECTED_MERGED_NAMES
```

- [ ] **Step 7: Run the touched backend tests**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest tests/test_config_merge.py tests/test_config_bundle.py tests/test_custom_labels_plugin.py tests/test_custom_labels_preview.py -v`
Expected: PASS — identical assertions, shared constants.

- [ ] **Step 8: Full backend gate + lint**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto`
Expected: 882 passed.

Run: `uvx ruff check tests/labels_equivalence.py tests/labels_plugin_module.py tests/test_config_merge.py tests/test_config_bundle.py tests/test_custom_labels_plugin.py tests/test_custom_labels_preview.py`
Expected: exit 0.

- [ ] **Step 9: Commit**

```bash
git add backend/tests/labels_equivalence.py backend/tests/labels_plugin_module.py backend/tests/test_config_merge.py backend/tests/test_config_bundle.py backend/tests/test_custom_labels_plugin.py backend/tests/test_custom_labels_preview.py
git commit -m "test(custom_labels): shared equivalence fixture + single plugin module load"
```

---

### Task 3: Manifest dead-check adjudication + missing branch tests

**Files:**
- Modify: `backend/app/plugins/manifest.py:63` (`_parse_config_merge` key check)
- Test: `backend/tests/test_plugins_manifest.py` (add two tests after `test_rejects_empty_key`)

**Interfaces:**
- Consumes: `parse_manifest(data: Any) -> PluginManifest` and `ManifestError` (existing, `backend/app/plugins/manifest.py`).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the two missing-coverage tests (both should PASS — they lock live branches)**

In `backend/tests/test_plugins_manifest.py`, add after `test_rejects_empty_key`:

```python
    def test_rejects_empty_config_merge(self):
        doc = {
            **minimal_manifest(),
            "config_merge": {},
        }
        with pytest.raises(ManifestError, match="non-empty object"):
            parse_manifest(doc)

    def test_rejects_non_string_merge_key_value(self):
        doc = {
            **minimal_manifest(),
            "config_merge": {"slotRules": {"strategy": "union_by_key", "key": 123}},
        }
        with pytest.raises(ManifestError, match="non-empty string"):
            parse_manifest(doc)
```

- [ ] **Step 2: Run them — expected PASS (coverage gap, not a bug)**

Run: `cd backend && uv run pytest tests/test_plugins_manifest.py -v`
Expected: all PASS, including the two new tests. If either FAILS, stop: the branch behaves differently than the review claimed — report the actual behavior before changing production code.

- [ ] **Step 3: Probe the "dead non-string-key check" claim**

Run: `rg -n "json.loads|json.load" backend/app/plugins/loader.py backend/app/plugins/registry.py backend/app/plugins/discovery.py 2>/dev/null`
Expected: the manifest document is produced by `json.loads` (JSON object keys are always strings — the `isinstance(key, str)` half of the check at `manifest.py:63` is unreachable from the only production entry point).
Also run: `rg -n "parse_manifest" backend/app/ backend/tests/`
Expected: production callers pass JSON-parsed docs only; test callers pass Python literals (where an int key is technically constructible but not representative of any real input).

- [ ] **Step 4: Delete the dead half of the key check**

In `backend/app/plugins/manifest.py`, line 63, change:

```python
        if not isinstance(key, str) or not key:
            raise ManifestError("config_merge keys must be non-empty strings")
```

to:

```python
        if not key:
            raise ManifestError("config_merge keys must be non-empty strings")
```

(Keep the `merge_key` isinstance check at line 71 — Step 1 proved it is live: JSON values can be non-strings.)

- [ ] **Step 5: Run manifest tests + full backend gate**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest tests/test_plugins_manifest.py -q && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto`
Expected: 884 passed (882 + 2 new).

Run: `uvx ruff check app/plugins/manifest.py` and `uvx mypy app/plugins/manifest.py`
Expected: exit 0 / zero new errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/plugins/manifest.py backend/tests/test_plugins_manifest.py
git commit -m "test(plugins): cover empty config_merge and non-string key; drop dead dict-key check"
```

---

### Task 4: `mergeSlotIds` tracks `sourceTier`; inherited badge derives its tier

**Files:**
- Modify: `frontend/src/features/customLabels/scopeMerge.ts` (`mergeSlotIds`)
- Modify: `frontend/src/features/customLabels/scopeMerge.test.ts` (`describe('mergeSlotIds')`)
- Modify: `frontend/src/features/customLabels/SlotGroup.tsx` (props type line 12, badge lines 105/111-115)
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx` (`inheritedFor` prop, lines 315-318)
- Test: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx` (new inherited-badge test)

**Interfaces:**
- Produces: `mergeSlotIds(tiers) → Record<string, { value: string; inherited: boolean; sourceTier: Tier }>` — `sourceTier` is the most specific tier containing the id. Consumed only by `CustomLabelsUI` (`serverIds`) in production.
- Produces: `SlotGroupProps.inheritedFor: (id: string) => Tier | null` (was `(id: string) => boolean`) — `null` means "not inherited"; a `Tier` value names the ancestor the value came from and drives the badge label.

- [ ] **Step 1: RED — update the `mergeSlotIds` tests with `sourceTier`**

In `frontend/src/features/customLabels/scopeMerge.test.ts`, replace the two tests in `describe('mergeSlotIds')`:

```ts
  it('client-only values are inherited, current-tier values are not', () => {
    const merged = mergeSlotIds([
      { tier: 'client', ids: { r1: 'a', r2: 'x' } },
      { tier: 'feed_source', ids: { r2: 'y' } },
    ]);
    expect(merged).toEqual({
      r1: { value: 'a', inherited: true, sourceTier: 'client' },
      r2: { value: 'y', inherited: false, sourceTier: 'feed_source' },
    });
  });

  it('single-tier chain has no inherited values', () => {
    const merged = mergeSlotIds([{ tier: 'client', ids: { r1: 'a' } }]);
    expect(merged).toEqual({
      r1: { value: 'a', inherited: false, sourceTier: 'client' },
    });
  });
```

Run: `cd frontend && npm test -- --run src/features/customLabels/scopeMerge.test.ts`
Expected: FAIL — current `mergeSlotIds` returns no `sourceTier`.

- [ ] **Step 2: GREEN — implement `sourceTier`**

In `frontend/src/features/customLabels/scopeMerge.ts`, replace the `mergeSlotIds` body:

```ts
export function mergeSlotIds(
  tiers: ReadonlyArray<{ tier: Tier; ids: Readonly<Record<string, string>> }>,
): Record<string, { value: string; inherited: boolean; sourceTier: Tier }> {
  const current = tiers[tiers.length - 1];
  const merged: Record<string, { value: string; inherited: boolean; sourceTier: Tier }> = {};
  for (const { tier, ids } of tiers) {
    for (const [id, value] of Object.entries(ids)) {
      merged[id] = {
        value,
        inherited: current === undefined || !(id in current.ids),
        sourceTier: tier,
      };
    }
  }
  return merged;
}
```

(The old trailing loop that re-set current-tier entries was redundant — the main loop already marks them `inherited: false`; dropping it also lets `sourceTier` stay the most recent writer's tier. `inherited` semantics are unchanged.)

Run: `cd frontend && npm test -- --run src/features/customLabels/scopeMerge.test.ts`
Expected: PASS.

- [ ] **Step 3: Change `SlotGroup`'s prop contract and badge**

In `frontend/src/features/customLabels/SlotGroup.tsx`:

1. Props type (line 12): `inheritedFor: (id: string) => boolean;` → `inheritedFor: (id: string) => Tier | null;` (`Tier` is already imported on line 5.)

2. In the rule map (line 105), `const inherited = inheritedFor(rule.id);` → `const inheritedFrom = inheritedFor(rule.id);`

3. Badge (lines 111-115):

```tsx
                    {inheritedFrom !== null && (
                      <Badge size="xs" variant="light" color="teal">
                        {t('inheritedFrom', { tier: tCommon(`scope.${inheritedFrom}`) }) }
                      </Badge>
                    )}
```

(Replaces the hardcoded `tCommon('scope.client')` — the badge now names the actual source tier. `tCommon` is already bound on line 32.)

- [ ] **Step 4: Update the `inheritedFor` producer in `CustomLabelsUI.tsx`**

In `frontend/src/features/customLabels/CustomLabelsUI.tsx` (lines 315-318):

```tsx
                      inheritedFor={(id) =>
                        serverIds[id]?.inherited === true
                          && (effectiveIds[id] ?? '') === serverIds[id].value
                          ? serverIds[id].sourceTier
                          : null
                      }
```

Run: `cd frontend && npm run typecheck`
Expected: clean — if the slot-empty branch or anything else still assumes a boolean, fix it per the new contract (`!== null` where truthiness was assumed).

- [ ] **Step 5: Add the UI test proving the badge (feed data empty → values inherited from client)**

In `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`, add inside the main describe:

```tsx
  it('marks client-tier bulk values as inherited at feed tier with a Client badge', async () => {
    const handler = (url: string) => {
      if (url.includes('/plugins/custom_labels/data?feed_source_id=')) return jsonResponse({});
      return jsonResponseFor(url);
    };
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', handler);
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.getAllByText('Inherited from Client').length).toBe(2);
  });
```

(With the feed tier returning empty data, `r1` and `r3` come from the client tier → `inherited: true, sourceTier: 'client'` → two badges reading "Inherited from Client". This test FAILS before Step 3 only in that the old code produced the same string by hardcoding — it locks the derivation for any future data-scope change. It must PASS after this task.)

- [ ] **Step 6: Frontend gate**

Run: `cd frontend && npm test -- --run && npm run typecheck && npm run build`
Expected: all green, no chunk-size warning.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/customLabels/scopeMerge.ts frontend/src/features/customLabels/scopeMerge.test.ts frontend/src/features/customLabels/SlotGroup.tsx frontend/src/features/customLabels/CustomLabelsUI.tsx frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx
git commit -m "feat(custom_labels): inherited badge derives source tier via mergeSlotIds sourceTier"
```

---

### Task 5: a11y label fix, pluralized count, wrapping headers, stable chain memos

**Files:**
- Modify: `frontend/src/features/customLabels/SlotGroup.tsx:126-128` (aria-label), `:36` (header nowrap), `:41` (count string unchanged — locales change)
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx:71-72` (chain memos), `:251` (description row nowrap)
- Modify: `frontend/public/locales/en/customLabels.json` + `frontend/public/locales/de/customLabels.json` (`activeRulesCount`)
- Test: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`

**Interfaces:**
- Consumes: the `inheritedFor` contract from Task 4 (unchanged here).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: RED — plural test + aria-label test**

In `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`:

1. Fix the existing assertion in `it('info boxes show slot explanation and active rule count')` (line 128): `getAllByText('1 active rules')` → `getAllByText('1 active rule')`.

2. Add two tests:

```tsx
  it('active rule count pluralizes for more than one rule', async () => {
    const twoInOneSlot = {
      slotRules: [
        GLOBAL_CONFIG.slotRules[0],
        { id: 'r4', name: 'Second', isActive: true, targetSlot: 'custom_label_1',
          matchField: 'id', valueTemplate: 'X', fallbackTemplate: '' },
      ],
    };
    const handler = (url: string) => {
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(twoInOneSlot);
      return jsonResponseFor(url);
    };
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', handler);
    expect(await screen.findByText('2 active rules')).toBeInTheDocument();
  });

  it('values textarea accessible name matches the localized label plus rule name', async () => {
    renderUI({ feedSourceId: 1 });
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    expect(
      screen.getByRole('textbox', { name: 'Product IDs — Mid Funnel' }),
    ).toBeInTheDocument();
  });
```

Run: `cd frontend && npm test -- --run src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
Expected: FAIL — '1 active rule' not rendered yet (single key `activeRulesCount` renders "1 active rules"), and the textarea's aria-label is currently the hardcoded English `` `${rule.name} ids` `` ("Mid Funnel ids").

- [ ] **Step 2: GREEN — locales, aria-label, wrapping, memos**

1. `frontend/public/locales/en/customLabels.json` — replace `"activeRulesCount": "{{count}} active rules",` with:

```json
  "activeRulesCount_one": "{{count}} active rule",
  "activeRulesCount_other": "{{count}} active rules",
```

2. `frontend/public/locales/de/customLabels.json` — replace `"activeRulesCount": "{{count}} aktive Regeln",` with:

```json
  "activeRulesCount_one": "{{count}} aktive Regel",
  "activeRulesCount_other": "{{count}} aktive Regeln",
```

3. `frontend/src/features/customLabels/SlotGroup.tsx` lines 126-128 — replace the hardcoded-English aria-label with the localized visible-label expression plus the rule name (keeps per-rule disambiguation):

```tsx
                      aria-label={rule.matchField === 'id'
                        ? `${t('bulk.productIds')} — ${rule.name}`
                        : `${t('bulk.valuesFor', { field: rule.matchField })} — ${rule.name}`}
```

4. `SlotGroup.tsx` line 36 — the slot header group overflows on narrow viewports; allow wrapping: `<Group gap="xs" justify="space-between" wrap="nowrap">` → `<Group gap="xs" justify="space-between" wrap="wrap">` (the inner badge+explanation group on line 37 keeps `nowrap`).

5. `frontend/src/features/customLabels/CustomLabelsUI.tsx` line 251 — same narrow-viewport overflow for the description row + help button: `wrap="nowrap"` → `wrap="wrap"`. (Leave lines 382 and 429 alone — 382 is the deliberate two-column layout, 429 is a compact badge row.)

6. `CustomLabelsUI.tsx` lines 71-72 — `configTierChain` / `dataTierChain` return fresh arrays every render, so the `serverRules`/`serverIds` memos (lines 111-130) recompute every render. Memoize the chains on the primitive inputs:

```tsx
  const configChain = useMemo(
    () => configTierChain(scope, routeContext),
    [scope.clientId, scope.feedSourceId, routeContext.clientId, routeContext.feedSourceId],
  );
  const dataChain = useMemo(
    () => dataTierChain(scope, routeContext),
    [scope.clientId, scope.feedSourceId, routeContext.clientId, routeContext.feedSourceId],
  );
```

(`useMemo` is already imported on line 1. No lint rule enforces exhaustive-deps in this repo; primitives are the correct keys because `PluginScope` and `useParams` results get fresh identities every render. Behavior-neutral refactor — no test change.)

Run: `cd frontend && npm test -- --run src/features/customLabels/scopeMerge.test.ts src/features/customLabels/__tests__/CustomLabelsUI.test.tsx && npm run typecheck`
Expected: PASS including the two new tests.

- [ ] **Step 3: Verify en/de i18n trees are identical**

Run: `cd frontend && node -e "const en=require('./public/locales/en/customLabels.json'),de=require('./public/locales/de/customLabels.json');const k=o=>Object.keys(o).sort().join(',');const cmp=(a,b,p='')=>{for(const key of new Set([...Object.keys(a),...Object.keys(b)])){if(!(key in a)||!(key in b))throw new Error(p+key);if(typeof a[key]==='object')cmp(a[key],b[key],p+key+'.')}};cmp(en,de);console.log('identical')"`
Expected: `identical`.

- [ ] **Step 4: Frontend gate**

Run: `cd frontend && npm test -- --run && npm run typecheck && npm run build`
Expected: all green, no chunk-size warning.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/customLabels/SlotGroup.tsx frontend/src/features/customLabels/CustomLabelsUI.tsx frontend/public/locales/en/customLabels.json frontend/public/locales/de/customLabels.json frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx
git commit -m "fix(custom_labels): localized textarea label, plural counts, wrapping headers, stable chain memos"
```

---

### Task 6: `usePreview` clears stale error/result + de-flaked timing

**Files:**
- Modify: `frontend/src/features/customLabels/usePreview.ts` (firing effect, lines 55-82)
- Test: `frontend/src/features/customLabels/usePreview.test.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `PreviewState` shape unchanged (`{ result, isPending, errors, unavailable }`); behavior change — `errors` resets to `null` when a new request starts; `result` becomes `null` on a 422.

- [ ] **Step 1: RED — two behavior tests**

In `frontend/src/features/customLabels/usePreview.test.tsx`:

1. Extend `DraftProbe` (it currently renders only `total`) so both probes show errors too:

```tsx
function DraftProbe() {
  const [draft, setDraft] = useState<SlotRule[]>(RULES);
  const state = useLabelizerPreview({
    enabled: true,
    feedSourceId: 1,
    rules: draft,
    slotIds: {},
  });
  return (
    <div>
      <button onClick={() => setDraft([{ ...RULES[0], valueTemplate: 'y' }])}>
        change draft
      </button>
      <span data-testid="errors">{state.errors?.join('|') ?? ''}</span>
      <span data-testid="total">{state.result?.total ?? ''}</span>
    </div>
  );
}
```

2. Add two tests inside `describe('useLabelizerPreview')`:

```tsx
  it('clears a previous 422 error when a new request starts', async () => {
    let calls = 0;
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        calls += 1;
        if (calls === 1) return jsonResponse({ errors: ['bad rule'] }, 422);
        return new Promise<Response>((resolve) => {
          setTimeout(() => resolve(jsonResponse(RESULT)), 800);
        });
      }
      return jsonResponse({});
    });
    render(<DraftProbe />);
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="errors"]')?.textContent)
        .toBe('bad rule'),
      { timeout: 5000 },
    )).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /change draft/i }));
    // the second request has started and is still in flight — the stale
    // 422 must already be cleared at request start
    expect(await waitFor(() => expect(calls).toBe(2), { timeout: 5000 })).toBeTruthy();
    expect(document.querySelector('[data-testid="errors"]')?.textContent).toBe('');
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="total"]')?.textContent).toBe('10'),
      { timeout: 5000 },
    )).toBeTruthy();
  }, 10000);

  it('clears the previous result when the request is rejected with 422', async () => {
    let calls = 0;
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        calls += 1;
        return calls === 1 ? jsonResponse(RESULT) : jsonResponse({ errors: ['nope'] }, 422);
      }
      return jsonResponse({});
    });
    render(<DraftProbe />);
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="total"]')?.textContent).toBe('10'),
      { timeout: 5000 },
    )).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /change draft/i }));
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="total"]')?.textContent).toBe(''),
      { timeout: 5000 },
    )).toBeTruthy();
    expect(document.querySelector('[data-testid="errors"]')?.textContent).toBe('nope');
  }, 10000);
```

Run: `cd frontend && npm test -- --run src/features/customLabels/usePreview.test.tsx`
Expected: the two NEW tests FAIL (current code keeps the old error until the next success, and keeps the old result on 422); the four existing tests PASS.

- [ ] **Step 2: GREEN — reset error at request start, clear result on 422**

In `frontend/src/features/customLabels/usePreview.ts`, change the firing effect:

```ts
  useEffect(() => {
    if (!enabled || tick === 0) return;
    const mySeq = ++seq.current;
    setIsPending(true);
    setErrors(null);
    void apiPost<PreviewResult>('/plugins/custom_labels/preview', {
      feed_source_id: feedSourceId,
      rules,
      slotIds,
      sample_size: 5,
    })
      .then((res) => {
        if (mySeq !== seq.current) return;
        setResult(res);
        setErrors(null);
        setUnavailable(false);
        setIsPending(false);
      })
      .catch((err: unknown) => {
        if (mySeq !== seq.current) return;
        if (err instanceof ApiError && err.status === 422) {
          setErrors(err.errors ?? [err.detail ?? 'Invalid rules']);
          setResult(null);
          setUnavailable(false);
        } else {
          setUnavailable(true);
        }
        setIsPending(false);
      });
  }, [tick]);
```

(Two added lines: `setErrors(null);` before `apiPost`, `setResult(null);` in the 422 branch.)

Run: `cd frontend && npm test -- --run src/features/customLabels/usePreview.test.tsx`
Expected: all 6 PASS.

- [ ] **Step 3: De-flake the existing tests (event-driven waits, wider margins)**

In the same test file:

1. `it('fires one debounced preview request and renders the result')` — change `{ timeout: 2500 }` → `{ timeout: 5000 }`.
2. `it('surfaces 422 validation errors')` — change `{ timeout: 2500 }` → `{ timeout: 5000 }`.
3. `it('sends no request when disabled')` — change the sleep `await new Promise((resolve) => setTimeout(resolve, 700));` → `await new Promise((resolve) => setTimeout(resolve, 1500));` (debounce is 500ms; the wider margin removes the loaded-CI race where the timer fires after the assertion).
4. `it('discards stale responses (newest draft wins)')` — replace the racy pre-click sleep:

```tsx
    await new Promise((resolve) => setTimeout(resolve, 700));
    await userEvent.click(screen.getByRole('button', { name: /change draft/i }));
```

with an event-driven wait for the first request to have actually started:

```tsx
    await waitFor(() => expect(calls).toBe(1), { timeout: 5000 });
    await userEvent.click(screen.getByRole('button', { name: /change draft/i }));
```

and change the post-click `waitFor` timeout `{ timeout: 2500 }` → `{ timeout: 5000 }`. Keep the final `setTimeout(resolve, 2000)` sleep (it gives the delayed first response its chance to wrongly apply; the guard must discard it).

Run: `cd frontend && npm test -- --run src/features/customLabels/usePreview.test.tsx && npm test -- --run src/features/customLabels/usePreview.test.tsx`
Expected: all 6 PASS twice in a row.

- [ ] **Step 4: Frontend gate**

Run: `cd frontend && npm test -- --run && npm run typecheck && npm run build`
Expected: all green, no chunk-size warning.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/customLabels/usePreview.ts frontend/src/features/customLabels/usePreview.test.tsx
git commit -m "fix(custom_labels): preview resets error on request start and clears result on 422"
```

---

### Task 7: Test-strength pass — exact badge + data-URL assertions, origin-bearing integration test

**Files:**
- Test: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx` (lines 158-159 data URLs, line 290 badge count)
- Test: `backend/tests/test_custom_labels_preview.py` (new route test in `TestPreviewRoute`)

**Interfaces:**
- Consumes: the existing `_setup_feed` / `_rule` / `ROWS` helpers in `test_custom_labels_preview.py`; the `GLOBAL_CONFIG` / `jsonResponseFor` fixtures in the UI test.
- Produces: nothing.

- [ ] **Step 1: Strengthen the feed-tier data-URL assertion**

In `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`, inside `it('at feed tier fetches config at global AND client scope, data at feed scope')`, replace:

```tsx
    const dataUrls = captured.filter((u) => u.includes('/data'));
    expect(dataUrls).toContain('/plugins/custom_labels/data?feed_source_id=1');
```

with (exact, ordered — `dataChain` is `[client, feed_source]`, and `usePluginData(clientDataScope)` mounts before `usePluginData(feedDataScope)`):

```tsx
    const dataUrls = captured.filter((u) => u.includes('/data'));
    expect(dataUrls).toEqual([
      '/plugins/custom_labels/data?client_id=1',
      '/plugins/custom_labels/data?feed_source_id=1',
    ]);
```

Run: `cd frontend && npm test -- --run src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
Expected: PASS — the client-tier data fetch at feed tier is now directly asserted (it was only implied before).

- [ ] **Step 2: Strengthen the global-badge assertion**

In the same file, inside `it('at client tier shows global rules with a Global badge and keeps them read-only')`, replace:

```tsx
    expect(screen.getAllByTestId('scope-badge-global').length).toBeGreaterThan(0);
```

with (the fixture has exactly two global-origin rules at client tier — `r1 Mid Funnel` and `r2 Off` — and the client-origin `r3 Client Only` must not carry one):

```tsx
    expect(screen.getAllByTestId('scope-badge-global').length).toBe(2);
    const clientRow = screen.getByText('Client Only').closest('div');
    expect(clientRow?.querySelector('[data-testid="scope-badge-global"]')).toBeNull();
```

Run: `cd frontend && npm test -- --run src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
Expected: PASS (this tightens a currently-weak assertion; if the count is not 2, read the fixture and adjust the expectation to the true count — do not weaken back to `toBeGreaterThan`).

- [ ] **Step 3: Add the origin-bearing-rules integration test (backend)**

In `backend/tests/test_custom_labels_preview.py`, add inside `class TestPreviewRoute` (after the existing `test_mounted_route_returns_counts` style tests):

```python
    async def test_preview_accepts_frontend_scoped_rules_with_origin_key(self, app_factory):
        client = await logged_in_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [
            {**_rule("r1", "custom_label_0", matchMode="all"), "origin": "global"},
        ]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"],
            "rules": rules,
            "slotIds": {},
            "sample_size": 5,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] > 0
        assert body["rules"]["r1"]["matched"] > 0
```

(The live hook sends `ScopedSlotRule`s that carry the extra `origin` key; tolerance was verified by review but never asserted against the real route. This locks it: no 422, real match counts.)

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest tests/test_custom_labels_preview.py -v`
Expected: PASS. If it FAILS with 422, `validate_config` is stricter than the live traffic — stop and report; do not loosen `validate_config` without operator sign-off.

- [ ] **Step 4: Both gates**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto`
Expected: 885 passed (884 + 1 new).

Run: `cd frontend && npm test -- --run && npm run typecheck && npm run build`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx backend/tests/test_custom_labels_preview.py
git commit -m "test(custom_labels): exact badge/data-URL assertions + origin-bearing route test"
```

---

### Task 8: Decisions log

**Files:**
- Modify: `docs/decisions.md` (append a `## 2026-09-07` section at the end)

**Interfaces:**
- Consumes: all prior tasks' outcomes.
- Produces: nothing.

- [ ] **Step 1: Append the decisions section**

Append to `docs/decisions.md`:

```markdown
## 2026-09-07

- **Labelizer polish cycle** (spec: `docs/superpowers/specs/2026-09-07-labelizer-polish-design.md`):
  - `merge_scopes` deleted from `config_resolver.py` — zero production callers (production resolves via `resolve_config_bundle`/`_resolve_declared`); its test consumers now exercise `_resolve_declared` directly.
  - `scopeMerge.ts` stays local to `features/customLabels` — promotion to a shared manifest-aware utility deferred until a second scoped plugin adopts the pattern (YAGNI; closes the final-review recommendation).
  - `useLabelizerPreview` behavior change: a new request clears any previous error at request start; a 422 clears the previous match-result panel (the UI never shows results contradicted by just-rejected input).
  - Redundant `preview.__annotations__` claim REFUTED: the two lines in `plugins/core/custom_labels/plugin.py` are load-bearing (future-annotations ForwardRefs resolved only by the runtime assignments — removal breaks route registration, proven by experiment); the cycle-2 "dead `__annotations__` line" minor was a mis-review and the lines stay.
  - Dead `isinstance(key, str)` dict-key check deleted from `_parse_config_merge` — manifests arrive via `json.loads`, whose object keys are always strings; the empty-`{}` and non-string `key`-value branches gained tests.
  - `mergeSlotIds` now tracks `sourceTier`; the inherited-value badge derives its tier label from it instead of hardcoding `scope.client`.
  - Slot-rules equivalence fixture deduplicated into `backend/tests/labels_equivalence.py` (was hand-synced across three backend suites); custom_labels plugin module now loads once per test process via `backend/tests/labels_plugin_module.py`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/decisions.md
git commit -m "docs: labelizer polish cycle decisions"
```

---

## Final gates (after Task 8)

- Backend: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto` — expect 885 passed.
- Frontend: `cd frontend && npm test -- --run && npm run typecheck && npm run build` — expect all green, no chunk-size warning.
- Lint: `uvx ruff check .` from `backend/` — touched files contribute zero findings.
- Whole-branch review (fresh reviewer; doubles as the deferred "fresh-agent re-review" recommendation from the previous cycle's final review), then cycle bookkeeping: TODO.md cycle-log entry + `.superpowers/sdd/progress.md` ledger update.

## Out of scope (do not add)

- Raw coverage interpolation (backend rounds — moot), locale-tab reformat, `matchedCount`/`idCount` pluralization (not flagged), non-labelizer backlog (findings-tooltip German plurals, ruff/mypy pin-or-drop, icon registry, TODO 6.2), the two-column rules layout (`CustomLabelsUI.tsx:382`), and the compact badge row (`:429`).
