# Section 9 Polish — P2 Cleanup Cycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close six self-contained P2 backlog items: pluralization i18n splits, usePreview fake-timer test, fixture deepcopy, manifest error message wording, plugin re-exec test+doc, and alembic DATABASE_URL guard.

**Architecture:** No schema changes, no new dependencies, no pipeline changes. Each task touches ≤4 files and is independently committable. Backend tasks run the standard ruff+mypy+pytest gate; frontend tasks run npm test+typecheck+build.

**Tech Stack:** Python 3.10+, pytest, vitest + React Testing Library, i18next (en/de), FastAPI, SQLAlchemy 2.0.

## Global Constraints

- No comments added to code unless they already exist in the file.
- All frontend strings via `t()` — no hardcoded UI text.
- en + de locale files must stay in lockstep (identical key trees).
- Backend ruff gate: exactly 506 errors (zero new).
- Backend mypy gate: exit-0 (hard, no baseline).
- Backend pytest gate: 1019 passing before task 9.6 adds 1 → 1020.
- Frontend test gate: 417 passing; typecheck + build clean.
- Spec: `docs/superpowers/specs/2026-09-10-section9-polish-design.md`

---

### Task 1: 9.3 — `labels_equivalence.py` deepcopy fixture rows

**Files:**
- Modify: `backend/tests/labels_equivalence.py`

**Interfaces:**
- Produces: `MERGED_SLOT_RULES` — same shape and values as before; object identity of rows is now independent of `GLOBAL_SLOT_RULES`/`CLIENT_SLOT_RULES`.

- [ ] **Step 1: Verify the current aliasing**

  Run:
  ```bash
  cd /home/ozon/gmc_feed_master/backend
  uv run python -c "
  from tests.labels_equivalence import GLOBAL_SLOT_RULES, CLIENT_SLOT_RULES, MERGED_SLOT_RULES
  print('aliased g1:', MERGED_SLOT_RULES[0] is CLIENT_SLOT_RULES[0])
  print('aliased g2:', MERGED_SLOT_RULES[1] is GLOBAL_SLOT_RULES[1])
  "
  ```
  Expected: both print `True`.

- [ ] **Step 2: Apply the fix**

  Replace `backend/tests/labels_equivalence.py` lines 1–31 with:
  ```python
  """Shared slot-rules equivalence fixture — keep in lockstep with
  frontend/src/features/customLabels/scopeMerge.test.ts (spec §1.2 gate).
  Read-only: consumers must not mutate these dicts in place."""

  import copy

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
      copy.deepcopy(CLIENT_SLOT_RULES[0]),
      copy.deepcopy(GLOBAL_SLOT_RULES[1]),
      copy.deepcopy(CLIENT_SLOT_RULES[1]),
      copy.deepcopy(CLIENT_SLOT_RULES[2]),
  ]
  EXPECTED_MERGED_IDS = ["g1", "g2", "c2", "c3"]
  EXPECTED_MERGED_NAMES = ["Client Mid", "Global Top", "Client Only", "Same Slot As G1"]
  EXPECTED_BY_SLOT = {
      "custom_label_1": ["g1", "c3"],
      "custom_label_0": ["g2", "c2"],
  }
  ```

- [ ] **Step 3: Verify aliasing is gone**

  Run:
  ```bash
  cd /home/ozon/gmc_feed_master/backend
  uv run python -c "
  from tests.labels_equivalence import GLOBAL_SLOT_RULES, CLIENT_SLOT_RULES, MERGED_SLOT_RULES
  print('still aliased:', MERGED_SLOT_RULES[0] is CLIENT_SLOT_RULES[0])
  print('values match:', MERGED_SLOT_RULES[0] == CLIENT_SLOT_RULES[0])
  "
  ```
  Expected: `still aliased: False`, `values match: True`.

- [ ] **Step 4: Run backend gate**

  ```bash
  cd /home/ozon/gmc_feed_master/backend
  uv run pytest tests/test_config_bundle.py tests/test_config_merge.py tests/test_custom_labels_plugin.py -v
  ```
  Expected: all pass.

- [ ] **Step 5: Commit**

  ```bash
  cd /home/ozon/gmc_feed_master
  git add backend/tests/labels_equivalence.py
  git commit -m "test: deepcopy MERGED_SLOT_RULES rows to prevent cross-suite aliasing"
  ```

---

### Task 2: 9.5 — `manifest.py` config_merge key-check wording

**Files:**
- Modify: `backend/app/plugins/manifest.py:65`
- Modify: `backend/tests/test_plugins_manifest.py:260`

**Interfaces:**
- Produces: `ManifestError("config_merge keys must be non-empty")` — message no longer implies a type check.

- [ ] **Step 1: Update the error message in `manifest.py`**

  In `backend/app/plugins/manifest.py`, change line 65 from:
  ```python
          raise ManifestError("config_merge keys must be non-empty strings")
  ```
  to:
  ```python
          raise ManifestError("config_merge keys must be non-empty")
  ```

- [ ] **Step 2: Update the test assertion**

  In `backend/tests/test_plugins_manifest.py`, line 260 currently reads:
  ```python
          with pytest.raises(ManifestError, match="non-empty string"):
  ```
  Change to:
  ```python
          with pytest.raises(ManifestError, match="non-empty"):
  ```

- [ ] **Step 3: Run targeted tests**

  ```bash
  cd /home/ozon/gmc_feed_master/backend
  uv run pytest tests/test_plugins_manifest.py -v
  ```
  Expected: all pass.

- [ ] **Step 4: Run ruff + mypy**

  ```bash
  cd /home/ozon/gmc_feed_master/backend
  uv run ruff check .
  uv run mypy .
  ```
  Expected: ruff exits 0 with count matching 506; mypy exits 0.

- [ ] **Step 5: Commit**

  ```bash
  cd /home/ozon/gmc_feed_master
  git add backend/app/plugins/manifest.py backend/tests/test_plugins_manifest.py
  git commit -m "fix: config_merge key-check error message no longer overstates type check"
  ```

---

### Task 3: 9B.3 — `alembic/env.py` DATABASE_URL guard + conftest warning

**Files:**
- Modify: `backend/alembic/env.py:13-14`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/AGENTS.md`

**Interfaces:**
- Produces: `_database_url` in `env.py` — prefers `config.attributes["database_url"]` over env var with explicit two-step logic; conftest session fixture warns when both `DATABASE_URL` and `TEST_DATABASE_URL` are set.

- [ ] **Step 1: Update `env.py`**

  In `backend/alembic/env.py`, replace line 13:
  ```python
  _database_url = config.attributes.get("database_url") or os.environ.get("DATABASE_URL")
  ```
  with:
  ```python
  _database_url = config.attributes.get("database_url")
  if _database_url is None:
      _database_url = os.environ.get("DATABASE_URL")
  ```

- [ ] **Step 2: Add the conftest warning fixture**

  Open `backend/tests/conftest.py`. At the top of the file, ensure `import os` and `import warnings` are present (add them after the existing imports if not already there). Then add this fixture near the top of the file, after the imports and before the first existing fixture:

  ```python
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

- [ ] **Step 3: Update `backend/AGENTS.md`**

  In the `## Testing` section of `backend/AGENTS.md`, add after the sentence about `TEST_DATABASE_URL` and `isolated_database_url`:

  > Do not export `DATABASE_URL` while running tests; if both `DATABASE_URL` and `TEST_DATABASE_URL` are set, pytest will warn at session start.

- [ ] **Step 4: Run backend gate**

  ```bash
  cd /home/ozon/gmc_feed_master/backend
  uv run ruff check .
  uv run mypy .
  uv run pytest tests/test_migrations.py -v
  ```
  Expected: ruff 506 exact, mypy exit-0, migration tests pass.

- [ ] **Step 5: Commit**

  ```bash
  cd /home/ozon/gmc_feed_master
  git add backend/alembic/env.py backend/tests/conftest.py backend/AGENTS.md
  git commit -m "fix: make alembic env.py DATABASE_URL fallback explicit; warn when both DB env vars set"
  ```

---

### Task 4: 9.6 — Plugin re-exec: test + doc

**Files:**
- Modify: `backend/tests/test_plugins_startup.py`
- Modify: `backend/docs/plugins.md`

**Interfaces:**
- Consumes: `create_app` from `backend/app/main.py`; `labels_plugin_module` registered under `sys.modules["custom_labels_plugin"]`
- Produces: one new test asserting `sys.modules["custom_labels_plugin"]` identity is preserved across `create_app(plugins_dir=...)` startup.

- [ ] **Step 1: Inspect `test_plugins_startup.py` imports and existing fixtures**

  Read `backend/tests/test_plugins_startup.py` to understand the import pattern, how `create_app` is called, and which fixtures are used (e.g. `isolated_database_url`, lifespan context pattern). Note the exact lifespan invocation pattern used by existing tests.

- [ ] **Step 2: Add the re-exec test**

  At the end of `backend/tests/test_plugins_startup.py`, add:

  ```python
  @pytest.mark.asyncio
  async def test_plugin_module_not_reexeced_under_create_app(isolated_database_url: str) -> None:
      import sys
      import tests.labels_plugin_module  # noqa: F401 — ensures the module is pre-loaded
      pre_id = id(sys.modules["custom_labels_plugin"])

      app = create_app(
          db_session_factory=None,
          session_store=None,
          settings=None,
          plugins_dir=Path(__file__).resolve().parents[2] / "plugins",
      )
      async with app.router.lifespan_context(app):
          post_id = id(sys.modules["custom_labels_plugin"])

      assert pre_id == post_id, "plugin module was re-executed under create_app"
  ```

  Check the existing `create_app` call signature used in this file and match it exactly — the keyword arguments above are illustrative; use whatever the file already uses.

- [ ] **Step 3: Run the new test**

  ```bash
  cd /home/ozon/gmc_feed_master/backend
  uv run pytest tests/test_plugins_startup.py -v
  ```
  Expected: all existing tests pass + the new test passes.

- [ ] **Step 4: Update `backend/docs/plugins.md`**

  In the Plugin Discovery section, add one sentence:

  > Plugin modules are loaded via `importlib.import_module`; Python's `sys.modules` cache prevents re-execution when a test both imports the plugin directly and calls `create_app(plugins_dir=...)`.

- [ ] **Step 5: Run full backend gate**

  ```bash
  cd /home/ozon/gmc_feed_master/backend
  uv run ruff check .
  uv run mypy .
  uv run pytest -n auto --report-log=.report.jsonl
  FAILED=$(jq -c 'select(.["$report_type"]=="TestReport" and .when=="call" and .outcome=="failed")' .report.jsonl | wc -l)
  echo "Failed: $FAILED"
  ```
  Expected: ruff 506, mypy exit-0, FAILED=0, total tests = 1020.

- [ ] **Step 6: Commit**

  ```bash
  cd /home/ozon/gmc_feed_master
  git add backend/tests/test_plugins_startup.py backend/docs/plugins.md
  git commit -m "test: assert plugin module not re-exec'd under create_app; document sys.modules caching"
  ```

---

### Task 5: 9.2 — `usePreview` disabled-path test: fake timers

**Files:**
- Modify: `frontend/src/features/customLabels/usePreview.test.tsx`

**Interfaces:**
- Consumes: `useLabelizerPreview` from `usePreview.ts` — `DEBOUNCE_MS = 500`.
- Produces: deterministic, zero-wall-clock disabled-path test; slow-response test driven by `vi.advanceTimersByTime`.

- [ ] **Step 1: Add `beforeEach`/`afterEach` fake-timer hooks**

  In `usePreview.test.tsx`, locate the outer `describe` block (or the top-level test scope). Add these hooks at the top of the first `describe` block that contains the disabled-path test:

  ```ts
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });
  ```

  `shouldAdvanceTime: true` keeps RTL's internal `waitFor` polling working alongside fake-timer-controlled application code.

- [ ] **Step 2: Replace the real sleep in the disabled-path test**

  Find the test at line ~110:
  ```ts
  it('sends no request when disabled', async () => {
    ...
    await new Promise((resolve) => setTimeout(resolve, 1500));
    ...
  });
  ```

  Replace the `await new Promise(...)` line with:
  ```ts
    await act(async () => { vi.advanceTimersByTime(600); });
  ```

  Ensure `act` is imported from `@testing-library/react` — it is already imported in this file.

- [ ] **Step 3: Fix the slow-response test**

  The test at line ~137 ("discards stale responses") has a stub that returns a slow promise:
  ```ts
  return new Promise<Response>((resolve) => {
    setTimeout(() => resolve(jsonResponse({ total: 1, rules: {}, slots: {} })), 1500);
  });
  ```

  This `setTimeout` now runs under fake timers. After the `render(...)` call in that test, the test must advance time to fire debounces and resolve the stub promise. The existing test likely already uses `waitFor` — add `act`-wrapped time advances before each `waitFor` that expects a fetch result. For example, after render:

  ```ts
  // Fire first debounce → triggers first (slow) fetch
  await act(async () => { vi.advanceTimersByTime(600); });
  // (change the rules to trigger second fetch here, as the test currently does)
  // Fire second debounce
  await act(async () => { vi.advanceTimersByTime(600); });
  // Resolve the slow first response (it should be discarded by the seq guard)
  await act(async () => { vi.advanceTimersByTime(1500); });
  ```

  Read the test body carefully before editing — preserve the exact assertion logic, only replace timing mechanisms.

- [ ] **Step 4: Run the tests**

  ```bash
  cd /home/ozon/gmc_feed_master/frontend
  npm run test -- --reporter=verbose src/features/customLabels/usePreview.test.tsx
  ```
  Expected: all tests in the file pass, no real-time delays.

- [ ] **Step 5: Run full frontend gate**

  ```bash
  cd /home/ozon/gmc_feed_master/frontend
  npm run test -- --run
  npm run typecheck
  npm run build
  ```
  Expected: all pass.

- [ ] **Step 6: Commit**

  ```bash
  cd /home/ozon/gmc_feed_master
  git add frontend/src/features/customLabels/usePreview.test.tsx
  git commit -m "test: replace 1500ms sleep with vi.useFakeTimers in usePreview disabled-path test"
  ```

---

### Task 6: 9.1 — Pluralization `_one`/`_other` variants

**Files:**
- Modify: `frontend/public/locales/en/pipeline.json`
- Modify: `frontend/public/locales/de/pipeline.json`
- Modify: `frontend/public/locales/en/rules.json`
- Modify: `frontend/public/locales/de/rules.json`
- Modify: `frontend/public/locales/en/plugins.json`
- Modify: `frontend/public/locales/de/plugins.json`

**Interfaces:**
- Produces: i18next-compatible `_one`/`_other` plural forms for all grammatically meaningful `{{count}}` strings in the above namespaces.

- [ ] **Step 1: Update `en/pipeline.json`**

  Replace the following flat keys with split forms. Keep all other keys unchanged.

  Replace:
  ```json
  "inUse": "Used by {{count}} feed sources",
  ```
  with:
  ```json
  "inUse_one": "Used by {{count}} feed source",
  "inUse_other": "Used by {{count}} feed sources",
  ```

  Replace:
  ```json
  "disableBlocked": "Plugin is in use by {{count}} feed sources. Cannot disable.",
  ```
  with:
  ```json
  "disableBlocked_one": "Plugin is in use by {{count}} feed source. Cannot disable.",
  "disableBlocked_other": "Plugin is in use by {{count}} feed sources. Cannot disable.",
  ```

  Replace:
  ```json
  "overviewTotal": "{{count}} instances",
  ```
  with:
  ```json
  "overviewTotal_one": "{{count}} instance",
  "overviewTotal_other": "{{count}} instances",
  ```

  Replace:
  ```json
  "overviewEnabled": "{{count}} enabled",
  ```
  with:
  ```json
  "overviewEnabled_one": "{{count}} enabled",
  "overviewEnabled_other": "{{count}} enabled",
  ```

  Replace:
  ```json
  "overviewDisabled": "{{count}} disabled",
  ```
  with:
  ```json
  "overviewDisabled_one": "{{count}} disabled",
  "overviewDisabled_other": "{{count}} disabled",
  ```

- [ ] **Step 2: Update `de/pipeline.json`**

  Replace the same five keys:
  ```json
  "inUse_one": "Wird von {{count}} Feed-Quelle verwendet",
  "inUse_other": "Wird von {{count}} Feed-Quellen verwendet",
  ```
  ```json
  "disableBlocked_one": "Plugin wird von {{count}} Feed-Quelle verwendet. Deaktivieren nicht möglich.",
  "disableBlocked_other": "Plugin wird von {{count}} Feed-Quellen verwendet. Deaktivieren nicht möglich.",
  ```
  ```json
  "overviewTotal_one": "{{count}} Instanz",
  "overviewTotal_other": "{{count}} Instanzen",
  ```
  ```json
  "overviewEnabled_one": "{{count}} aktiv",
  "overviewEnabled_other": "{{count}} aktiv",
  ```
  ```json
  "overviewDisabled_one": "{{count}} deaktiviert",
  "overviewDisabled_other": "{{count}} deaktiviert",
  ```

- [ ] **Step 3: Update `en/rules.json`**

  Replace:
  ```json
  "deleteSelectedBody": "Delete {{count}} rule(s)? This cannot be undone after saving.",
  ```
  with:
  ```json
  "deleteSelectedBody_one": "Delete {{count}} rule? This cannot be undone after saving.",
  "deleteSelectedBody_other": "Delete {{count}} rules? This cannot be undone after saving.",
  ```

- [ ] **Step 4: Update `de/rules.json`**

  Replace:
  ```json
  "deleteSelectedBody": "{{count}} Regel(n) löschen? Nach dem Speichern nicht rückgängig machbar.",
  ```
  with:
  ```json
  "deleteSelectedBody_one": "{{count}} Regel löschen? Nach dem Speichern nicht rückgängig machbar.",
  "deleteSelectedBody_other": "{{count}} Regeln löschen? Nach dem Speichern nicht rückgängig machbar.",
  ```

- [ ] **Step 5: Update `en/plugins.json`**

  Replace:
  ```json
  "saveFailedWithErrors": "Could not save: {{count}} validation error(s).",
  ```
  with:
  ```json
  "saveFailedWithErrors_one": "Could not save: {{count}} validation error.",
  "saveFailedWithErrors_other": "Could not save: {{count}} validation errors.",
  ```

- [ ] **Step 6: Update `de/plugins.json`**

  Replace:
  ```json
  "saveFailedWithErrors": "Speichern fehlgeschlagen: {{count}} Validierungsfehler.",
  ```
  with:
  ```json
  "saveFailedWithErrors_one": "Speichern fehlgeschlagen: {{count}} Validierungsfehler.",
  "saveFailedWithErrors_other": "Speichern fehlgeschlagen: {{count}} Validierungsfehler.",
  ```

- [ ] **Step 7: Run frontend tests and check for failures**

  ```bash
  cd /home/ozon/gmc_feed_master/frontend
  npm run test -- --run 2>&1 | tail -30
  ```

  If any tests fail due to string assertions against the old flat keys (e.g. asserting `"Plugin is in use by 3 feed sources"` exactly), update those assertions to match the `_other` plural form produced by i18next. Known candidates: `PluginList.test.tsx`, `AdminSettingsPage.test.tsx`. The tests in those files use `/i` regex matchers for the count strings, so they should pass without changes — but verify.

- [ ] **Step 8: Run full frontend gate**

  ```bash
  cd /home/ozon/gmc_feed_master/frontend
  npm run test -- --run
  npm run typecheck
  npm run build
  ```
  Expected: all pass.

- [ ] **Step 9: Commit**

  ```bash
  cd /home/ozon/gmc_feed_master
  git add \
    frontend/public/locales/en/pipeline.json \
    frontend/public/locales/de/pipeline.json \
    frontend/public/locales/en/rules.json \
    frontend/public/locales/de/rules.json \
    frontend/public/locales/en/plugins.json \
    frontend/public/locales/de/plugins.json
  git commit -m "i18n: add _one/_other plural variants for count-bearing strings in pipeline, rules, plugins"
  ```

---

## Final gate

After all tasks are committed:

```bash
cd /home/ozon/gmc_feed_master/backend
uv run ruff check .
uv run mypy .
uv run pytest -n auto --report-log=.report.jsonl
FAILED=$(jq -c 'select(.["$report_type"]=="TestReport" and .when=="call" and .outcome=="failed")' .report.jsonl | wc -l)
echo "Backend failed: $FAILED  (expected 0, total expected 1020)"

cd /home/ozon/gmc_feed_master/frontend
npm run test -- --run
npm run typecheck
npm run build
```

## TODO updates

After completion, mark in `TODO.md`:
- `9.1` → `[x]`
- `9.2` → `[x]`
- `9.3` → `[x]`
- `9.5` → `[x]`
- `9.6` → `[x]`
- `9B.3` → `[x]`

Add a cycle log entry summarising the branch, tasks, and final gate counts.
