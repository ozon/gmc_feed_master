# Backend API Reference

## Authentication
All endpoints (except `/health` and `/export/{token}.xml`) require a valid session cookie.
- `POST /auth/login` — `{username, password}` → sets `HttpOnly; Secure; SameSite=Lax` cookie
- `POST /auth/logout` — clears session
- `POST /auth/password` — change password (requires PostgreSQL session store)
- `GET /auth/me` — returns `{username}`
- `POST /auth/interaction` — refreshes session idle timer

## Health
- `GET /health` → `{"status": "ok"}`

## Clients
- `GET /clients` — list all clients
- `POST /clients` — create client `{name, status?}`
- `GET /clients/{id}` — get client
- `PUT /clients/{id}` — update client `{name?, status?}`
- `DELETE /clients/{id}` — delete client (cascades: feed sources, pipelines, staging, exports)

## Feed Sources
- `GET /clients/{client_id}/feed-sources` — list feed sources for client
- `POST /clients/{client_id}/feed-sources` — create feed source
  ```
  {name, source_format, cron_expression?, target_country?, target_language?, currency?, source_url?, history_retention_count?, volume_drop_threshold_pct?}
  ```
- `GET /feed-sources/{id}` — get feed source detail
- `PUT /feed-sources/{id}` — update feed source
- `DELETE /feed-sources/{id}` — delete feed source
- `POST /feed-sources/{id}/run` — manual pipeline trigger → returns `{run_id}` (202)

### Pipeline Configuration
- `GET /feed-sources/{id}/pipeline` — get active pipeline definition
- `PUT /feed-sources/{id}/pipeline` — save pipeline definition (UI builder)
  ```
  {name, version, instances: [{plugin_id, position, name, configuration}]}
  ```

### Field Mapping
- `GET /feed-sources/{id}/field-mapping` — get mapping document
- `PUT /feed-sources/{id}/field-mapping` — save manual mappings `{mappings: {source_path: {target: registry_path}}}`. `source_path` is a source field name or a dotted sub-field path `parent.sub` (parent must be a structured/repeated-structured source field, `sub` one of its sub-fields; a whole-field mapping of `parent` and its sub-field mappings are mutually exclusive). `target` is `attr` or `attr.subfield` only. A whole-attribute target `X` and any `X.subfield` target are mutually exclusive claims across all sources (422 on overlap, regardless of payload key order). Empty strings are stripped from repeated-scalar target values at apply time. Errors: 422 `{"errors": ["key: message", ...]}`
- `POST /feed-sources/{id}/field-mapping/auto` — run auto-mapper on demand (whole-field passes first — auto, then synonym — then a sub-field pass; whole-field mappings suppress sub matching for their parent, and existing sub-mappings block whole-field claims)

### Ingestion Runs
- `GET /feed-sources/{id}/ingestion-runs` — history (limit=50 default), includes error details

### Quality Findings
- `GET /feed-sources/{id}/quality-findings` — current findings grouped by severity/rule

### Products
- `GET /feed-sources/{id}/products` — paginated staged products (raw stage only). Params: `page`, `page_size` (≤200), `q` (id/title substring), `status` (`active`/`removed`/`all`), `sort` (`product_id`/`title`/`status`/`last_seen_at`, `-` prefix for descending). Response: `{items, fields, total, page, page_size}` where `fields` is the sorted union of `raw_data` keys across the returned rows (drives the UI column picker) and each item carries its full `raw_data` alongside the baseline fields (`title`, `description`, `link`, `image_link`, `availability`, `price`, `condition`)
- `GET /feed-sources/{id}/products/{product_id}` — single product with status, hashes and full `raw_data`

### Export History
- `GET /feed-sources/{id}/export-history` — list versions
- `GET /feed-sources/{id}/export-history/{v}/diff?against={v2}` — field-based diff (per product + attribute, old vs new)
- `POST /feed-sources/{id}/export-history/{v}/rollback` — append-only rollback, creates new version

### Export Token
- `POST /feed-sources/{id}/export-token/rotate` — rotates token, old URL invalid immediately
  Returns `{export_token, export_url}`

### Dashboard Summary
- `GET /dashboard/summary` — aggregated view for dashboard (clients, feed sources, last run status)

## Plugins
- `GET /plugins` — manifests of all registered plugins (enabled + disabled)
  Returns: `[{id, name, version, enabled, manifest, used_by_feed_sources}]`
- `PUT /plugins/{plugin_id}/enabled` — enable/disable plugin; returns 409 when disabling a plugin used by ≥1 feed source

### Plugin Config (Reserved Routes)
- `GET /plugins/{plugin_id}/config?client_id=&feed_source_id=` — get config at scope (omitted = global)
- `PUT /plugins/{plugin_id}/config?client_id=&feed_source_id=` — full-replace config, validated against `config_schema`
  Returns 422 `{"errors":[...]}` on validation failure

### Plugin Data (Reserved Routes)
- `GET /plugins/{plugin_id}/data?client_id=&feed_source_id=` — get data at scope
- `PUT /plugins/{plugin_id}/data?client_id=&feed_source_id=` — full-replace data, validated against `data_schema`

**Scope rules:**
- At most one of `client_id`, `feed_source_id` (400 if both)
- Scope must be declared in manifest (`config_scope` / `data_scope`)
- `global` = neither parameter provided

### Plugin-Contributed Routes
Plugins may register custom routes under `/plugins/{plugin_id}/...` via `register_routes(router)`.
**Reserved sub-paths (enforced by contract test):**
- `/plugins/{plugin_id}/config` — core config endpoints
- `/plugins/{plugin_id}/data` — core data endpoints

Plugin routes must not use these prefixes. Example: Category plugin uses `/plugins/category/rules/stats`, `/plugins/category/matches`.

## Registry
- `GET /registry/attributes` — full GMC Attribute Registry (from `backend/registry/attributes.json`)
  Each attribute includes `baseline_required: boolean` — true for the baseline-required set (spec §7: `id`, `link`, `image_link`, `availability`, `price`, `condition`, and the `title`/`structured_title`, `description`/`structured_description` alternative-pair members); false otherwise.
- `POST /registry/generate` — regenerate from `gmc_def.md` (admin only)

## Public Export Endpoint
- `GET /export/{token}.xml` — **unauthenticated**, serves static XML file
  - Token = `FeedSource.export_token` (non-guessable, 32 bytes URL-safe)
  - File path: `{export_dir}/published/{feed_source_id}.xml`
  - Atomic publish: written to temp → `os.replace()`
  - No feed source ID exposed in URL
  - 404 if token not found or file missing

## Dry Run
- `POST /feed-sources/{id}/dry-run` — execute pipeline without export, returns findings preview
  `{limit: number}` — max products to process

## Error Responses
- `401` — invalid/missing session
- `403` — cross-tenant access (e.g., plugin route for feed source not owned by client)
- `404` — resource not found
- `422` — validation error: `{"errors": ["message", ...]}`
- `503` — database unavailable

## Key Files
- `app/routes/*.py` — all route definitions
- `app/routes/plugins.py` — plugin config/data endpoints with scope resolution
- `app/routes/export_public.py` — public export endpoint
- `app/schemas/*.py` — Pydantic request/response models