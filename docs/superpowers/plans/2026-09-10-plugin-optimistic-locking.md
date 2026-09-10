# Plugin Optimistic Locking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the read-modify-write race on plugin config/data PUTs via row-id optimistic versioning: GET exposes `X-Plugin-Data-Version`, PUT accepts optional `expected_version` (409 on mismatch), frontend save hooks auto-retry once on fresh state. Wire ManualTab, RulesTab, CustomLabelsUI transparently.

**Branch:** `plugin-optimistic-locking` (off main `9b8c8c7`)
**Design spec:** `docs/superpowers/specs/2026-09-10-plugin-optimistic-locking-design.md`
**Baseline gates:** backend 1009/ruff 506/mypy 42; frontend 412/typecheck/build.

## Global Constraints

- Work on `plugin-optimistic-locking`; fast-forward merge at cycle end.
- No inline comments; docstrings allowed.
- TDD: RED → GREEN → commit per step. Backend from `backend/` (`uv run pytest …`, needs `TEST_DATABASE_URL` from `../.env`); frontend from `frontend/` (`npx vitest run …`, `npm run typecheck`).
- Legacy behavior MUST be byte-for-byte preserved for PUTs without `expected_version` (existing tests are the regression net — do not modify them to accommodate new behavior).
- 409 body shape: `{"detail": {"message": ..., "current_version": <int|null>}}`.
- `uv run pytest tests/test_plugin_contract.py` green after every plugin-adjacent task.
- ruff zero-new-in-touched-files (506 baseline); mypy ≤ 42 baseline.
- Frontend: TanStack Query only for server state; all strings via `t()`; en+de parity.
- Docs update in the same commit as the behavior they describe.

---

### Task 1: Backend — GET version header + PUT expected_version + 409

**Files:**
- Modify: `backend/app/routes/plugins.py`
- Modify: `backend/tests/test_plugin_routes.py` (or the file holding scoped config/data route tests — locate via `grep -rn "plugins/.*/config" backend/tests/` first; the file with the app_factory route pattern)
- Modify: `backend/docs/api.md` (same commit)

**Interfaces:**
- `_get_payload(...)` → returns `tuple[dict[str, Any] | JSONResponse, int | None]` (payload, row id). GET handlers: `response: Response` parameter (FastAPI); set `response.headers["X-Plugin-Data-Version"] = str(version)` when version is not None; return body unchanged.
- `_put_payload(..., expected_version: str | None)`:
  - None → today's path unchanged.
  - `"null"` → `if row_exists: 409` else proceed.
  - integer-string → `if not row_exists or row.id != int(expected_version): 409`.
  - else → 422 `{"detail": "expected_version must be an integer or null"}`.
  - 409 JSON: `{"detail": {"message": "plugin data changed since read", "current_version": <row id or null>}}`.
  - The version check reads the CURRENT row (SELECT id before DELETE) inside the same transaction.

- [ ] **Step 1:** Locate the existing route-test file; read `_put_payload`/`_get_payload` and their tests fully.
- [ ] **Step 2 (RED):** Tests — header on GET after PUT; absent before write; stale-version 409 (assert `current_version` = fresh id); null-on-absent succeeds; null-on-existing 409; int on absent 409; legacy no-param replace (both onto existing and absent); bad value 422; client-scope row doesn't collide with global.
- [ ] **Step 3 (GREEN):** Implement header + param + checks; run the focused file; run `uv run pytest tests/test_plugin_contract.py`; full gates (`uv run pytest -n auto`, `uv run ruff check .`, `uv run mypy .`).
- [ ] **Step 4:** api.md update in the same commit; commit.

---

### Task 2: Frontend — apiGetWithHeaders + version in query cache

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/hooks.ts` (`usePluginConfig`, `usePluginData`)
- Modify: `frontend/src/api/hooks.test.tsx` (or wherever these hooks' tests live — locate via grep)
- Modify: `frontend/src/api/queryKeys.ts` only if the cached shape requires a paired key (prefer: same key, cache stores `{payload, version}`)

**Interfaces:**
- `apiGetWithHeaders<T>(url): Promise<{ data: T; headers: Headers }>` — refactor `request` to optionally return the envelope; `apiGet` unchanged.
- `usePluginConfig`/`usePluginData`: queryFn → `apiGetWithHeaders`; cache `{ payload, version }` (version `number | null`, header absent ⇒ null). Hook returns `data` = payload (via select or direct field) AND `dataVersion` = version. Consumer access patterns (`(data as {rules?}).rules`, `assignmentsOf`) must keep working — verify with the existing tests untouched.
- `useSavePluginConfig`/`useSavePluginData`: build `?expected_version=` from `queryClient.getQueryData` (paired key): cache miss ⇒ omit the param (legacy); cache hit ⇒ version or the literal string `"null"`.

- [ ] **Step 1:** Read `client.ts`, `hooks.ts` (plugin config/data/save hooks + queryKeys), their tests, and the three consumers' access patterns.
- [ ] **Step 2 (RED):** Hook tests — version captured from header (present); null when absent; `data` still the raw payload.
- [ ] **Step 3 (GREEN):** Implement; run the focused hook tests + consumers' existing tests (CategoryUI/RulesTab/ManualTab/CustomLabelsUI) — ALL must pass unmodified; typecheck.
- [ ] **Step 4:** Commit.

---

### Task 3: Frontend — save hooks 409 retry-once

**Files:**
- Modify: `frontend/src/api/hooks.ts` (the two save hooks)
- Modify: `frontend/src/api/hooks.test.tsx` (+ conflict tests)
- Modify: `frontend/public/locales/en/plugins.json`, `frontend/public/locales/de/plugins.json` (conflict toast key, only if a dedicated key is used; otherwise rely on notifyApiError's detail rendering and skip)

**Interfaces:**
- Retry flow: PUT with `expected_version` → 409 → `await queryClient.refetchQueries({queryKey: paired})` → PUT same payload with the fresh `expected_version` (from the refetched cache) → success propagates.
- Double 409 → mutation errors (original 409 ApiError surfaces; consumer onError toast fires). No third PUT.
- Non-409 errors: no retry (today's behavior).
- RulesTab dirty draft, ManualTab inputs, CustomLabelsUI editor state must be untouched by the retry path (they are — retry is inside the hook).

- [ ] **Step 1 (RED):** Conflict tests — one 409 then success (assert exactly 2 PUTs, second carries fresh version from refetched GET; refetch URL asserted); double 409 → error, 2 PUTs total, no third; non-409 → single PUT, no refetch.
- [ ] **Step 2 (GREEN):** Implement the retry in both save hooks (shared helper if clean — e.g. `mutateWithVersion` internal function); run focused tests; typecheck.
- [ ] **Step 3:** Consumer smoke: ManualTab assign test with mid-flight 409 → retry applies onto fresh map (other editor's assignment preserved in the second PUT body); RulesTab save test unchanged-passing.
- [ ] **Step 4:** Commit (i18n keys if added; en+de parity).

---

### Task 4: Backend+frontend integration proof + docs + cycle bookkeeping

**Files:**
- Modify: `backend/docs/data-model.md` (row id as revision token)
- Modify: `docs/decisions.md` (2026-09-10 entry, decisions 1–7)
- Modify: `TODO.md` (cycle log; close the assignments-race deferral)
- Modify: `docs/superpowers/specs/...` — no, spec already committed; skip.

- [ ] **Step 1:** Full gates: backend `uv run pytest -n auto` (1009+new), `ruff check .` (506), `mypy .` (42); frontend full suite (412+new), typecheck, build.
- [ ] **Step 2:** ManualTab conflict integration test if not already in Task 3 Step 3 (mid-flight 409 → success, both editors' assignments in final state).
- [ ] **Step 3:** data-model.md + decisions.md + TODO.md updates; commit.
- [ ] **Step 4:** Final whole-branch review (inline, per SDD): diff review against this plan + spec §4 checklist; verdict.
- [ ] **Step 5:** Merge `plugin-optimistic-locking` → main (ff-only), push, delete branch; ledger close-out.
