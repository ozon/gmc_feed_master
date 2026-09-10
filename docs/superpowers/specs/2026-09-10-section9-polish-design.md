# Design: Section 9 Polish — P2 Cleanup Cycle

**Date:** 2026-09-10
**Branch:** `section9-polish` (suggested)
**Tasks:** 9.1, 9.2, 9.3, 9.5, 9.6, 9B.3
**Gates:** backend 1019, ruff 506 exact, mypy exit-0; frontend 417 + typecheck + build

---

## Overview

Six self-contained P2 tasks from the Section 9 backlog and the 9B review-remediation carry-forwards. No schema changes, no new dependencies, no pipeline changes. Each task is independently completable.

---

## Task 9.1 — Pluralization: `_one`/`_other` variants (grammatically meaningful splits only)

### Scope

Audit all frontend locale files for `{{count}}` strings that lack `_one`/`_other` variants and where the singular/plural distinction changes the grammar in English or German. Pure count-display labels (e.g. `"Total: {{count}}"`) are left flat — no grammatical distinction exists.

### Strings to split

| File | Key | en singular | en plural |
|---|---|---|---|
| `pipeline.json` | `inUse` | `Used by {{count}} feed source` | `Used by {{count}} feed sources` |
| `pipeline.json` | `disableBlocked` | `Plugin is in use by {{count}} feed source. Cannot disable.` | `Plugin is in use by {{count}} feed sources. Cannot disable.` |
| `pipeline.json` | `overviewTotal` | `{{count}} instance` | `{{count}} instances` |
| `pipeline.json` | `overviewEnabled` | `{{count}} enabled` | `{{count}} enabled` (same; add variants for correctness and de) |
| `pipeline.json` | `overviewDisabled` | `{{count}} disabled` | `{{count}} disabled` (same; add variants for correctness and de) |
| `rules.json` | `actions.deleteSelectedBody` | `Delete {{count}} rule? This cannot be undone after saving.` | `Delete {{count}} rules? This cannot be undone after saving.` |
| `plugins.json` | `saveFailedWithErrors` | `Could not save: {{count}} validation error.` | `Could not save: {{count}} validation errors.` |

**Strings left flat** (pure display labels, no grammar change needed):
- `monitoring.findings.total` — `"Total: {{count}}"`
- `monitoring.dryRun.processed` — `"Processed: {{count}}"`
- `monitoring.dryRun.dropped` — `"Dropped: {{count}}"`

### German equivalents

| Key | de singular | de plural |
|---|---|---|
| `pipeline.inUse` | `Wird von {{count}} Feed-Quelle verwendet` | `Wird von {{count}} Feed-Quellen verwendet` |
| `pipeline.disableBlocked` | `Plugin wird von {{count}} Feed-Quelle verwendet. Deaktivieren nicht möglich.` | `Plugin wird von {{count}} Feed-Quellen verwendet. Deaktivieren nicht möglich.` |
| `pipeline.overviewTotal` | `{{count}} Instanz` | `{{count}} Instanzen` |
| `pipeline.overviewEnabled` | `{{count}} aktiv` | `{{count}} aktiv` |
| `pipeline.overviewDisabled` | `{{count}} deaktiviert` | `{{count}} deaktiviert` |
| `rules.actions.deleteSelectedBody` | `{{count}} Regel löschen? Nach dem Speichern nicht rückgängig machbar.` | `{{count}} Regeln löschen? Nach dem Speichern nicht rückgängig machbar.` |
| `plugins.saveFailedWithErrors` | `Speichern fehlgeschlagen: {{count}} Validierungsfehler.` | `Speichern fehlgeschlagen: {{count}} Validierungsfehler.` |

### Already correct (no change)

`export.json` (findings.critical/warning/info, fieldsChanged), `customLabels.json` (idCount, activeRulesCount, labeledOf, shadowedCount, nProducts, matchedCount), `category.json` (rules.matchesCount).

### Test updates

Files asserting the old flat string value must be updated to assert the `_one` or `_other` form as appropriate for the count used in the test:
- `frontend/src/features/pipeline/PluginList.test.tsx`
- `frontend/src/features/admin/AdminSettingsPage.test.tsx`
- `frontend/src/api/hooks.admin.test.tsx`

### Acceptance

- All 7 keys above have `_one` and `_other` variants in both `en/` and `de/` locale files.
- `npm run build` (typecheck + build) passes.
- All updated tests pass.

---

## Task 9.2 — `usePreview` disabled-path test: fake timers

### Problem

`usePreview.test.tsx:117` uses `await new Promise((resolve) => setTimeout(resolve, 1500))` to prove no fetch fires when `enabled=false`. This is a 1.5s real-time wall-clock dependency per test run.

### Design

Replace the real sleep with `vi.useFakeTimers` controlled time advancement.

**Setup:**
```ts
beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => {
  vi.useRealTimers();
});
```

`shouldAdvanceTime: true` keeps RTL's internal `waitFor` polling (which uses real `setTimeout` under the hood) ticking correctly alongside fake-timer-controlled application code.

**Disabled-path test:**
```ts
it('sends no request when disabled', async () => {
  const calls: string[] = [];
  stubFetch((url) => { calls.push(url); return jsonResponse({}); });
  render(<Probe rules={RULES} enabled={false} />);
  await act(() => { vi.advanceTimersByTime(600); }); // debounce 500ms + margin
  expect(calls.some((u) => u.includes('/preview'))).toBe(false);
});
```

**Slow-response test (line 137):** The stub uses `setTimeout(resolve, 1500)` inside the fetch handler — this now runs under fake timers. Drive it with `vi.advanceTimersByTime(600)` to fire the debounce, then `vi.advanceTimersByTime(1500)` to resolve the slow first response, then `vi.advanceTimersByTime(600)` again for the second debounce if needed. Preserve the existing assertion logic.

**Other tests in this file** using `waitFor({ timeout: 5000 })`: these continue to work because `shouldAdvanceTime: true` allows real async resolution (promise microtasks) to proceed normally.

### Risk note

The TODO flagged `setTick`/debounce interplay. The risk is: if `vi.advanceTimersByTime` is called inside a React state update cycle before React flushes, the tick increment may not yet be reflected. Wrapping advances in `act(...)` resolves this — `act` flushes React's pending state updates before returning.

### Acceptance

- The disabled-path test uses `vi.advanceTimersByTime` and no real sleep.
- `npm run test` passes with no wall-clock delays for this test.

---

## Task 9.3 — `labels_equivalence.py`: deepcopy fixture rows

### Problem

`MERGED_SLOT_RULES` aliases rows of `GLOBAL_SLOT_RULES` and `CLIENT_SLOT_RULES` by reference. The docstring guards against mutation but does not prevent it structurally.

### Design

```python
import copy

MERGED_SLOT_RULES = [
    copy.deepcopy(CLIENT_SLOT_RULES[0]),
    copy.deepcopy(GLOBAL_SLOT_RULES[1]),
    copy.deepcopy(CLIENT_SLOT_RULES[1]),
    copy.deepcopy(CLIENT_SLOT_RULES[2]),
]
```

- `GLOBAL_SLOT_RULES` and `CLIENT_SLOT_RULES` remain unchanged (still plain list literals — no deepcopy needed there since nothing aliases into them).
- All consumers receive objects with the same shape and values; only object identity changes.
- No test changes needed.

### Acceptance

- `labels_equivalence.py` uses `copy.deepcopy` for each row of `MERGED_SLOT_RULES`.
- `uv run pytest -n auto` passes (backend gate).

---

## Task 9.5 — `manifest.py` `config_merge` key-check wording

### Problem

`backend/app/plugins/manifest.py:65`:
```python
raise ManifestError("config_merge keys must be non-empty strings")
```

The guard is `if not key:` — it catches falsy values (empty string, `None`, `0`) but not truthy non-strings. The message "must be non-empty strings" implies a type check that isn't there. Unreachable in production (JSON object keys are always strings), but misleading for code readers.

### Design

Change the message to:
```python
raise ManifestError("config_merge keys must be non-empty")
```

No logic change. The existing test that asserts this error path must update its expected message string to `"config_merge keys must be non-empty"`.

### Acceptance

- `manifest.py:65` message reads `"config_merge keys must be non-empty"`.
- The corresponding test passes with the updated expected string.
- `uv run mypy .` and `uv run ruff check .` pass (no new errors).

---

## Task 9.6 — Plugin re-exec: test + doc

### Problem

`load_plugin_class` execs `plugin.py` at app lifespan startup via `discover_and_mount`. Tests that also import the plugin module directly (e.g. via `tests/labels_plugin_module.py`) end up with the module cached in `sys.modules` before startup — so the `create_app(plugins_dir=...)` path calls `importlib.import_module`, which hits the cache and does not re-exec. This is already the correct behaviour; it just isn't documented or tested.

### Design

**Test** — add to `backend/tests/test_plugins_startup.py` (or a new `test_plugin_reexec.py`):

```python
async def test_plugin_module_not_reexeced_under_create_app(isolated_database_url):
    import sys
    from tests.labels_plugin_module import labels_plugin as pre_loaded
    # labels_plugin_module registers the module under "custom_labels_plugin"
    pre_id = id(sys.modules["custom_labels_plugin"])

    app = create_app(plugins_dir=Path("../plugins"))
    async with app.router.lifespan_context(app):
        post_id = id(sys.modules["custom_labels_plugin"])

    assert pre_id == post_id, "plugin module was re-executed under create_app"
```

**Doc** — add one sentence to `backend/docs/plugins.md` under the Plugin Discovery section:

> Plugin modules are loaded via `importlib.import_module`; Python's `sys.modules` cache prevents re-execution when a test both imports the plugin directly and calls `create_app(plugins_dir=...)`.

### Acceptance

- The new test passes.
- `backend/docs/plugins.md` has the added sentence.
- No changes to `load_plugin_class` or `discover_and_mount`.

---

## Task 9B.3 — `alembic/env.py` DATABASE_URL guard + conftest warning

### Problem

`backend/alembic/env.py:13`:
```python
_database_url = config.attributes.get("database_url") or os.environ.get("DATABASE_URL")
```

If a developer runs pytest with `DATABASE_URL` exported (e.g. `set -a; source .env`), and a test calls `_load_alembic_schema` which sets `config.attributes["database_url"]` to the pytest-postgresql template DB URL, the `or` short-circuits correctly. **However**, any alembic call that does *not* go through `config.attributes` (e.g. a direct `alembic upgrade head` during the test session, or a conftest path that doesn't set the attribute) silently picks up `DATABASE_URL` and migrates the dev DB.

Additionally, the current wording is subtle — the preference of `config.attributes` over env is implicit in `or`, not explicit.

### Design

**`backend/alembic/env.py`** — make preference explicit:
```python
_database_url = config.attributes.get("database_url")
if _database_url is None:
    _database_url = os.environ.get("DATABASE_URL")
```

Semantically identical to the current code; intent is now unambiguous.

**`backend/tests/conftest.py`** — session-scoped autouse warning fixture:
```python
import os
import warnings

@pytest.fixture(scope="session", autouse=True)
def _warn_ambient_database_url() -> None:
    if os.environ.get("DATABASE_URL") and os.environ.get("TEST_DATABASE_URL"):
        warnings.warn(
            "Both DATABASE_URL and TEST_DATABASE_URL are set. "
            "Alembic in tests uses TEST_DATABASE_URL; DATABASE_URL is ignored by test paths. "
            "Unset DATABASE_URL to silence this warning.",
            stacklevel=2,
        )
```

This is a warning, not an error — it does not break CI in environments where both are legitimately set.

**`backend/AGENTS.md`** — add one sentence to the Testing section:
> Do not export `DATABASE_URL` while running tests; if both `DATABASE_URL` and `TEST_DATABASE_URL` are set, pytest will warn at session start.

### Acceptance

- `env.py` uses the explicit two-step pattern.
- `conftest.py` session fixture emits a `UserWarning` when both env vars are set.
- `AGENTS.md` has the added sentence.
- `uv run pytest -n auto` passes (backend gate).

---

## Task ordering

These tasks are independent and can be executed in any order or in parallel. Suggested order for a single-agent run:

1. 9.3 (one-liner, zero risk — warmup)
2. 9.5 (one-liner + one test string update)
3. 9B.3 (two files + doc)
4. 9.6 (new test + doc)
5. 9.2 (test refactor — most nuanced)
6. 9.1 (most files touched — do last to avoid locale conflicts)

## Gates (per task and final)

- **Backend tasks (9.3, 9.5, 9.6, 9B.3):** `uv run ruff check .` (506 exact), `uv run mypy .` (exit-0), `uv run pytest -n auto` (1019 passing; 9.6 adds 1 → 1020)
- **Frontend tasks (9.1, 9.2):** `npm run test` (417 passing; 9.1 may add 0, 9.2 adds 0), `npm run typecheck`, `npm run build`
- **Final:** all of the above clean on main
