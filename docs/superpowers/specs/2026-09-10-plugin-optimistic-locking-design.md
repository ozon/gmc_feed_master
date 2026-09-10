# Plugin Config/Data Optimistic Locking — Design

**Date:** 2026-09-10
**Cycle branch:** `plugin-optimistic-locking` (off main `9b8c8c7`)
**Source:** M12 follow-ups cycle deferral (assignments read-modify-write race) + review of the generic plugin PUT surface

## §0 Context and operator decisions

The generic plugin storage routes are full-replace read-modify-write with no concurrency control: `PUT /plugins/{id}/config` and `/plugins/{id}/data` delete the scoped row and insert a new one carrying the client's whole JSONB payload. Two concurrent editors race silently — editor B's stale snapshot drops editor A's writes. Affected UIs: Category ManualTab (assignments), Category RulesTab (rules config), CustomLabelsUI (label maps). `PluginData`/`PluginConfig` rows have no version/updated_at; only `created_at` (reset by delete+insert) and a surrogate `id` that strictly increases per write — a natural revision token.

Operator decisions (2026-09-10 brainstorming, binding):

1. **Scope: all plugin scopes** — fix the generic routes; wire all three UI consumers. No half-versioned surface.
2. **Conflict semantics: 409 + retry-on-fresh** — server rejects stale writes with 409 carrying `current_version`; the client refetches and re-applies the same edit once on fresh state. No work lost; last-writer-wins per edit.
3. **Version token: row surrogate id** — no schema change, no migration; every write creates a new row, so `id` orders revisions.
4. **Empty case: `null` = absent row** — GET exposes `null` version when no row exists; PUT with `expected_version=null` succeeds only if still absent. Two racing first-writers: one wins, one 409s.
5. **Frontend: hooks own the protocol** — save hooks auto-attach the version and auto-retry once on 409; consumers change minimally.
6. **Back-compat: optional opt-in param** — PUT without `expected_version` behaves exactly as today (unchecked full-replace). Existing tests/scripts/curl unaffected.
7. **Version transport: response header** — `X-Plugin-Data-Version` on GET; body unchanged; no breaking body-wrap.

## §1 Backend — version exposure + conditional PUT

**Files:** `backend/app/routes/plugins.py` (+ tests).

`_get_payload` (both config and data variants): when a row exists, the response carries header `X-Plugin-Data-Version: <row id>`; when absent, the header is omitted (client reads absence as `null`). Body stays the payload itself (today's shape). Implementation: the route handlers need the row id, so `_get_payload` returns `(payload, version_or_None)` and the two GET handlers attach the header via a `Response` parameter (FastAPI: declare `response: Response`, set `response.headers[...]`, still return the body).

`_put_payload` gains an `expected_version: str | None = None` query parameter on both PUT routes:

- **Absent** — legacy path: unchecked delete+insert, byte-for-byte today's behavior.
- **String `"null"`** — succeeds only if no row currently exists; else 409. (Query params are strings; the literal `"null"` encodes the absent-row expectation.)
- **Integer string** — succeeds only if the current row's `id` equals it; else 409.
- Any other non-integer value — 422 (FastAPI path/query validation style: plain `detail` string, matching the house `Query` usage).

409 body: `{"detail": {"message": "plugin data changed", "current_version": <int|null>}}` — the client can retry immediately without a second GET. The check runs inside the existing `async with session.begin()` transaction; the delete+insert cycle bumps the row id, which is exactly the next revision.

House precedent: 409 for plugin-disable-in-use (`test_plugin_enabled` flow); conditional-write semantics parallel HTTP `If-Match` without ETag parsing.

## §2 Frontend — hooks own the protocol

**Files:** `frontend/src/api/client.ts`, `frontend/src/api/hooks.ts` (+ tests).

- `client.ts`: new `apiGetWithHeaders<T>(url): Promise<{ data: T; headers: Headers }>` — `request` gains an optional flag to return the response envelope; existing `apiGet` unchanged.
- `usePluginConfig` / `usePluginData`: queryFn switches to `apiGetWithHeaders`; the query cache stores `{ payload, version }` (version: `number | null` from the header). A `select` on the hook keeps the consumer-facing shape: `data` remains the raw payload (so `rulesOf`/`assignmentsOf` and every existing test keep working); the version is exposed as a second hook field (`dataVersion`) alongside.
- `useSavePluginConfig` / `useSavePluginData`: mutation gains an internal retry:
  1. Attach `?expected_version=<version|null>` from the query cache (via `queryClient.getQueryData` on the paired GET key; `undefined` cache ⇒ no param ⇒ legacy behavior — first-ever UI write still safe under decision 4 because a fresh UI always GETs first).
  2. On 409: `invalidateQueries` the paired GET (refetch fresh), wait for the fresh version, re-apply the SAME payload once with the new `expected_version`.
  3. Second 409 (double conflict) or re-apply error: surface the conflict toast and stop — mutation errors with the original error so the consumer's `onError` toast fires; the draft state (RulesTab dirty guard, ManualTab input, CustomLabelsUI editor state) is untouched, so the user can retry manually.
- Retry legibility: one console-free, notification-driven UX — consumers pass an optional `conflictMessage` i18n key already in their namespace (`plugins.conflict` common fallback); v1 uses the generic `notifyApiError` path with the 409 detail.

## §3 Consumers

- **ManualTab** (`assignments`): no structural change — `persist()` already goes through the save hook. The 409-then-retry is invisible in the happy path; on double-conflict the toast fires and the input/lookup state survives.
- **RulesTab** (`rules` config): save flow unchanged; on double-conflict the draft survives (dirty guard) and the baseline refetches — the user re-clicks Save.
- **CustomLabelsUI** (label maps): same hook-based path; its bulk edit flows gain the same protection without UI changes.
- No per-UI conflict banner in v1 (deferred unless dogfood shows double-conflicts are common).

## §4 Testing

- **Backend** (`backend/tests/test_plugin_config_data.py` or the existing plugin-routes test file, app_factory pattern):
  - GET returns header with row id after a PUT; header absent before any write.
  - PUT with matching `expected_version` succeeds and bumps the version.
  - PUT with stale `expected_version` → 409 with `current_version` = fresh id.
  - PUT with `expected_version=null` on absent row succeeds; same call when a row exists → 409.
  - PUT without the param: legacy unchecked replace (both over existing and onto absent rows).
  - Non-integer non-null param → 422.
  - Scope variants: the check keys on the scoped row (client scope write doesn't collide with global row).
- **Frontend** (`src/api/hooks` tests + one ManualTab conflict-path test):
  - `usePluginData` captures version from header (queryFn assertion).
  - Save hook: 409 → refetch → retry once with fresh version → success; assert exactly two PUTs, second carrying the fresh version.
  - Save hook: double 409 → mutation errors; no third PUT.
  - ManualTab: assign with a mid-flight conflicting PUT (stub returns 409 with `current_version`, fresh GET) → success toast, assignment applied on fresh map (other editor's assignment preserved).
- **Gates:** backend pytest (1009+new), ruff 506 zero-new, mypy 42 zero-new; frontend vitest (412+new), typecheck, build. Contract suite (`test_plugin_contract.py`) must stay green — plugins themselves are untouched.

## §5 Documentation

- `backend/docs/api.md`: GET header + `expected_version` param + 409 semantics on both routes.
- `backend/docs/data-model.md`: note the row-id-as-revision token on plugin_configs/plugin_data.
- `docs/decisions.md`: 2026-09-10 entry recording decisions 1–7.
- `TODO.md`: cycle log; close the assignments-race deferral.

## §6 Out of scope

- ETag/If-Match generic middleware (the query-param approach covers the plugin surface only).
- Feed-source-scope UIs (none exist yet; the routes cover all scopes uniformly).
- Server-side merge semantics.
- Conflict banner UX per consumer.
- Any change to plugin runtime (`process()`/`validate_config`) — untouched.
