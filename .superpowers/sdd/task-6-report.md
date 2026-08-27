# Task 6 Report: Plugin API endpoints

**Status:** DONE
**Commit:** `37b0ae1 feat: plugin management API endpoints`

## What was built

- `backend/app/routes/plugins.py` — `plugins_router` with:
  - `GET /plugins` → all `Plugin` rows as `[{"id": <name column>, "name": manifest["name"], "version", "enabled", "manifest"}]`, ordered by id (includes disabled and multiple versions).
  - `PUT /plugins/{plugin_id}/enabled` → body `{"enabled": bool}`; 404 unknown; persists via ORM update in one transaction.
  - `GET/PUT /plugins/{plugin_id}/config` and `/data` → shared `_get_payload`/`_put_payload` helpers over `PluginConfig`/`PluginData`.
  - Shared `_resolve_target(plugin_id, client_id, feed_source_id, db_session, scope_kind)` implementing the exact validation order:
    1. `_require_db` → 503 (route entry)
    2. plugin row by `name == plugin_id` → 404 HTTPException
    3. both scope params → 422 JSONResponse `{"errors": ["pass at most one of client_id, feed_source_id"]}`
    4. non-global scope must be declared in manifest `config_scope`/`data_scope` → else 422 `{"errors": ["scope not declared for this plugin"]}`; global (no params) always allowed
    5. ownership existence via `session.get(Client/FeedSource, ...)` → 404
  - Storage: one row per (plugin, scope-owner) with `key = "default"`; PUT = validate (jsonschema against manifest `config_schema`/`data_schema`) → delete existing owner rows → insert, inside one `session.begin()` transaction. GET returns first payload or `{}`.
  - Payload validation catches both `jsonschema.ValidationError` and `jsonschema.SchemaError` → 422 `{"errors": [<message>]}`.
- `backend/app/schemas/plugins.py` — `EnabledPut(BaseModel)` with `enabled: bool`.
- Wired: `routes/__init__.py` exports `plugins_router`; `main.py` imports + `include_router(plugins_router)`.
- Auth: every route takes `Depends(require_user)` + `Depends(get_db_session)`.

## Implementation notes

- FastAPI rejects `dict | JSONResponse` return annotations without an explicit response model; the four config/data routes carry `response_model=None` (same pattern as returning JSONResponse from handlers in `field_mapping.py`).
- `_resolve_target`'s SELECTs implicitly begin a session transaction, so PUT wraps resolution + delete + insert in a single `session.begin()` block; early 422 returns inside the block commit an empty transaction (same as field_mapping's validation-error returns).
- Scope declaration normalization (`str | list | None → tuple`) mirrors `_normalize_scopes` semantics from `config_resolver.py`; an empty declared list yields `()`, so every scoped data/config request 422s while global stays allowed.
- Multiple `Plugin` rows can share a name across versions (uq is name+version); lookups use `order_by(Plugin.id)` + `.first()` rather than `scalar_one_or_none`.

## Tests

`backend/tests/test_plugins_api.py` — 16 tests mirroring `test_field_mapping_api.py` patterns (isolated DB engine, seeded user, `/auth/login`):

- list-all incl. disabled rows, id/name/version/enabled/manifest shape
- enabled toggle round-trip + unknown-plugin 404
- config global default `{}`, PUT/GET round-trip per scope, full-replace semantics
- unknown plugin 404 (GET+PUT), unknown client/feed-source 404
- both-scopes 422 with exact error string (GET+PUT)
- undeclared-scope 422 (feed_source not in config_scope)
- schema violation PUT → 422 `errors` key, nothing persisted
- data happy path round-trip; empty declared scopes reject every scoped request; data schema violation
- all endpoints 401 without auth

## Verification

- RED confirmed before implementation (import failure → 4 failures).
- Full suite: **463 passed** (447 baseline + 16 new) with `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres`.
- No lint/typecheck tooling configured in backend pyproject; nothing to run.

## Self-review

- Validation order matches spec exactly (503 → 404 → both-scopes 422 → undeclared-scope 422 → ownership 404). ✔
- Empty `data_scope` tuple → every scoped request 422s; global still allowed. ✔ (covered by test)
- Display `name` comes from `manifest["name"]` (fallback to column for malformed manifests); `id` is the `name` column. ✔
- No reserved-path routes defined here (only `/plugins*`). ✔

## Concerns

- None blocking. Minor observation: `jsonschema.validate` is skipped if a DB-seeded manifest lacks a valid schema dict — real plugins always have one per `parse_manifest`, so this only affects hand-seeded rows.
