# Backend API Reference

## Authorization (roles)

Two roles: `admin` and `user` (literal strings on `users.role`).

- The seed user created at startup (`INITIAL_USERNAME`/`INITIAL_PASSWORD`) is `admin`; the m11 migration promoted all pre-existing users to `admin`.
- A `user` can be assigned to multiple clients (`user_clients` join table) and has full functional scope inside them (runs, exports, plugin configs, monitoring).
- Non-DB fallback mode (session store injected, no PostgreSQL boundary): treated as admin/unrestricted.

### Enforcement matrix

| Resource | admin | user (assigned) | user (not assigned) |
|---|---|---|---|
| `GET /api/clients`, `GET /api/dashboard/summary` | all clients | assigned clients only | n/a (filtered out) |
| Client-scoped routes (`/api/clients/{id}/…`) and feed-source-scoped routes (`/api/feed-sources/{id}/…`, products, pipeline, monitoring, export-history, dry-run, plugin config/data with `client_id`/`feed_source_id` scope) | full | full | **404** (no existence leak) |
| Client create/update/delete | allowed | **403** | **404** |
| `/api/admin/*` | allowed | **403** | **403** |
| Public export endpoint (`/export/{token}.xml`) | token-auth, unchanged | unchanged | unchanged |

Enforcement lives in `app/access.py`: `get_current_user` (loads role + assigned client ids per request; 401 for missing/inactive users), `require_admin` (403), and router-level `enforce_scope_access` (reads `client_id`/`feed_source_id` from path AND query params — plugin scope params are query params). Role/assignment changes apply on the next request; a password reset bumps `revocation_generation`, invalidating existing sessions. Deactivated users (`is_active=false`) cannot log in and existing sessions die.

## Authentication
All backend routes are served under the `/api` prefix, except the public root `GET /health` and `GET /export/{token}.xml`. Interactive docs are at `/api/docs`.
All endpoints (except `/health` and `/export/{token}.xml`) require a valid session cookie.
- `POST /api/auth/login` — `{username, password}` → sets `HttpOnly; Secure; SameSite=Lax` cookie; rejects inactive users (401)
- `POST /api/auth/logout` — clears session
- `POST /api/auth/password` — change password (requires PostgreSQL session store)
- `GET /api/auth/me` — returns `{"username": str, "role": "admin"|"user", "client_ids": list[int] | null}` (`null` = admin/unrestricted; a sorted list of assigned client ids for users)
- `POST /api/auth/interaction` — refreshes session idle timer

## Logs
Paths live under `/api/logs/*`. The SPA owns the bare `/logs` route, and the backend API is namespaced under `/api`, so the two no longer collide: both `Caddyfile` and `Caddyfile.dev` proxy `/api/*` to the backend, while `/logs` loads the admin viewer from the SPA.

- `GET /api/logs/entries` — **admin-only** (`require_admin`). Query params: `category`, `level`, `source`, `logger`, `actor`, `client_id`, `feed_source_id`, `request_id`, `run_id`, `q` (literal message substring — `%`/`_` are escaped, not treated as LIKE wildcards), `from`, `to`, `limit` (default 100, clamped 1–500), `cursor` (id). Returns `{items: [...], next_cursor}` ordered by `id desc`; `next_cursor` is the last returned id when more rows exist.
- `POST /api/logs/client` — **any authenticated user** (`require_user`). Accepts a batch of frontend error entries (redacted server-side, each `context` capped at 8000 chars), writes `category=client_error`, returns `204`. A numeric `Content-Length` over 32 000 bytes is rejected with 413; a chunked request without a numeric `Content-Length` isn't transport-size-capped, but per-entry validation (8000-char `context` cap, 2000-char `message`) and the 20-entry batch maximum still apply. Submissions are limited to 60 per 60 s per user (429 over) via an in-memory fixed window (single-worker assumption); windows older than the interval are evicted once the per-user map exceeds 256 entries.

`GET /api/admin/settings` / `PUT /api/admin/settings` include `event_log_retention_days` (default 180; the retention rows are described under Admin → Settings below).

## Admin Area (admin only)

### Users
- `GET /api/admin/users` — list `[{id, username, role, is_active, client_ids}]`
- `POST /api/admin/users` (201) — create `{username, password, role: "admin"|"user", client_ids?, is_active?}`; 409 on duplicate username
- `PATCH /api/admin/users/{user_id}` — update `{role?, is_active?, client_ids?}` (client_ids full-replaces assignments); 404 unknown user
- `POST /api/admin/users/{user_id}/password` (204) — set new password `{new_password}` (revokes the user's sessions); 404 unknown user

### Settings
- `GET /api/admin/settings` — `{staging_removal_retention_days, staging_history_retention_days, ingestion_run_retention_days, ai_usage_retention_days, event_log_retention_days}`; seeds the single `global_settings` row with 90s (and 180 for `event_log_retention_days`) on first read
- `PUT /api/admin/settings` — update retention days (each ≥ 1; 422 otherwise). The nightly purge jobs read these values (fallback 90 while no row exists; `event_log_retention_days` falls back to 180)

### AI Administration
All routes require the admin role. `api_key` is never included in any response.

- `GET /api/admin/ai/providers` — list provider configs `[{id, name, provider_type, base_url, model, tier, input_price_per_mtok, output_price_per_mtok, max_concurrency, timeout_s, enabled}]`
- `POST /api/admin/ai/providers` — create `{name, provider_type="litellm"|"openai_compatible", base_url, api_key?, model, tier="bulk"|"precision", input_price_per_mtok?, output_price_per_mtok?, max_concurrency=4, timeout_s=30, enabled=true}`; enabled rows are grouped by `tier` into Router model groups with `bulk → precision` failover
- `PATCH /api/admin/ai/providers/{id}` — partial update; `api_key` absent = unchanged, explicit `""` = cleared
- `DELETE /api/admin/ai/providers/{id}` (204) — delete config; runs read config at call time, so deletion just makes the next AI call fall back
- `POST /api/admin/ai/providers/{id}/test` — live probe completion (`"Reply with OK"`); returns `{"status": "ok", latency_ms, prompt_tokens, completion_tokens}` or `{"status": "error", "error_code"}`
- `GET /api/admin/ai/provider-presets` — wizard presets `[{vendor_key, label, model_prefix, default_base_url, requires_base_url, api_key_env_hint, docs_url, supports_catalog}]`
- `GET /api/admin/ai/model-catalog?vendor=&mode=chat` — `{entries: [{model_id, vendor, display_name, context_window, max_output_tokens, input_price_per_mtok, output_price_per_mtok, supports_vision, supports_function_calling, is_recommended}], sync: {last_attempt_at, last_success_at, last_error, source}}`; lazily seeds from the installed LiteLLM price data when empty
- `POST /api/admin/ai/model-catalog/refresh` — fetch the upstream LiteLLM catalog; on failure keeps the last-good catalog and records `last_error` in the sync payload
- `POST /api/admin/ai/providers` / `PATCH /api/admin/ai/providers/{id}` — `provider_type` is normalized to `litellm` on write; a legacy `openai_compatible` payload with an unprefixed model is stored as `openai/<model>`
- `GET /api/admin/ai/usage?group_by=client|feed_source|task_type|day&client_id=&feed_source_id=&task_type=&from=&to=` — aggregated `{"rows": [{group_key, calls, cache_hits, prompt_tokens, completion_tokens, cost_usd}]}`; 422 on other group_by values
- `GET /api/admin/ai/usage/summary?client_id=&feed_source_id=&task_type=&from=&to=` — totals `{calls, cache_hits, hit_ratio, prompt_tokens, completion_tokens, cost_usd, saved_prompt_tokens, saved_completion_tokens, cost_saved_usd}` (savings are the cache-hit portion)
- `GET /api/admin/ai/usage/timeseries?from=&to=` — per-day aggregated rows (`group_by=day` shape) for charting
- `GET /api/admin/ai/settings` — AI runtime settings; seeds defaults on first read. Returns the DB settings plus `redis_from_env` and `effective_cache_backend` (never the Redis credentials)
- `PUT /api/admin/ai/settings` — same body minus the derived fields; persists then **hot-applies** (rebuilds the LiteLLM cache and Router on the running service). A build failure returns 422 and the previous config stays active (the DB write rolls back)
- `GET /api/admin/ai/cache` — `{effective_backend, redis_from_env, healthy, namespace, entries}`; health is a fail-open set/get probe; `entries` is `null` for redis (needs a SCAN)
- `GET /api/admin/ai/cache/stats?from=&to=` — cache-hit ratio and saved tokens/cost from `ai_usage_logs`
- `POST /api/admin/ai/cache/clear` — `{namespace?}` clears one task-type namespace (by cache-key prefix) or all AI namespaces; returns `{removed}`

### Prompt Templates (admin only)

Versioned, immutable prompt templates per task type. Editing = creating a new version; old versions stay queryable. No PATCH/DELETE — deactivation happens only by activating another version. Placeholder syntax is `{{variable}}`; values are XML-escaped into `<data>` tags at render time (prompt-injection isolation), and placeholders must be canonical variables of the task type and declared in the template's `variables` list.

- `GET /api/admin/ai/prompt-templates?task_type=&client_id=` — all versions (ordered task_type, client_id, version desc)
- `GET /api/admin/ai/prompt-templates/{id}` — single version
- `POST /api/admin/ai/prompt-templates` — create new version `{task_type, client_id?, name, system_prompt, user_prompt, variables, activate=true}`; 422 with `{errors, warnings}` on placeholder violations; 404 unknown client; 409 on concurrent template modification (integrity conflict or DB deadlock); `activate` flips the single-active flag per (task_type, scope)
- `POST /api/admin/ai/prompt-templates/{id}/activate` — switch/rollback the active version in the template's scope; 409 on concurrent activation (integrity conflict or DB deadlock)
- `POST /api/admin/ai/prompt-templates/preview` — dry-run render, zero AI cost: `{task_type, template_id? | (system_prompt, user_prompt, variables?), product? | (feed_source_id, product_id?)}` → `{messages, used_variables, warnings, errors}`; 422 on validation errors; 404 when no staging sample matches

`AiService.run_task` resolves client-scoped active → global active → builtin registry default; the resolved version (`tmpl:{id}:v{version}` / `builtin:<12 hex>` content hash) is part of the AI result-cache key, so new versions invalidate and rollbacks resume old cache entries.

### Scheduler
- `GET /api/admin/scheduler` — registered job overview `[{id, trigger}]`; 503 when no scheduler is running (app lifespan not started)

### Chat
- `POST /api/chat` — `{messages: [{role: "user"|"assistant", content}]}` → `{content}`. Any authenticated user; tenancy is enforced inside the tools (client-scoped users only see their clients' data, admins see everything). The server prepends a fixed system prompt and runs the tool loop (max 5 rounds): the model may call `list_feed_sources`, `query_staging_products` (title search, status/limit filters), `query_qc_findings` (severity filter), `query_export_runs` — all read-only, limit ≤ 50, results truncated at 500 chars. 422 on bad payloads or a non-user last message; 502 `tool_loop_exhausted` after 5 tool rounds without a final answer; 503 when no AI provider is configured or the AI service is unavailable. Chat is stateless per request — the client sends the full conversation each time.

## Health
- `GET /health` → `{"status": "ok"}`

## Clients
- `GET /api/clients` — list clients (admin: all; user: assigned only)
- `POST /api/clients` — create client `{name, status?}` — **admin only (403)**
- `PUT /api/clients/{id}` — update client `{name?, status?}` — **admin only (403)**
- `DELETE /api/clients/{id}` — delete client (cascades: feed sources, pipelines, staging, exports) — **admin only (403)**

## Feed Sources
- `GET /api/clients/{client_id}/feed-sources` — list feed sources for client
- `POST /api/clients/{client_id}/feed-sources` — create feed source
  ```
  {name, source_format, cron_expression?, target_country?, target_language?, currency?, source_url?, history_retention_count?, volume_drop_threshold_pct?}
  ```
- `GET /api/feed-sources/{id}` — get feed source detail
- `PUT /api/feed-sources/{id}` — update feed source
- `DELETE /api/feed-sources/{id}` — delete feed source
- `POST /api/feed-sources/{id}/run` — manual pipeline trigger → returns `{run_id}` (202)

### Pipeline Configuration
- `GET /api/feed-sources/{id}/pipeline` — get active pipeline definition: `{instances: [{id, position, plugin_id, name, configuration, enabled}]}`
- `PUT /api/feed-sources/{id}/pipeline` — save pipeline definition (UI builder); upsert-by-id — instances carrying an `id` from a previous GET/PUT are updated in place (stable ids), instances without `id` are created, omitted instances are deleted. Input shape: `{instances: [{id?, plugin_id, name?, configuration, enabled?}]}`; `id` values not belonging to this pipeline are rejected (422 `{"errors": [...]}`). Reordering is safe against the `(pipeline_id, position)` unique constraint (two-pass positioning)
  ```
  {instances: [{id, plugin_id, position, name, configuration, enabled}]}
  ```
- `PATCH /api/feed-sources/{id}/pipeline/instances/{instance_id}` — toggle a single instance's `enabled` flag with immediate persist (per-instance Switch in the pipeline page). Body: `{"enabled": bool}` → `200 {"id": int, "enabled": bool}`; 404 for unknown feed source or instance (instance must belong to the feed source's active pipeline). Also rebuilds `pipeline.definition` so the JSONB mirrors the rows (string plugin ids, same as PUT)

### Field Mapping
- `GET /api/feed-sources/{id}/field-mapping` — get mapping document: `{version, auto_mapped, source_fields, mappings, custom_fields}`
- `PUT /api/feed-sources/{id}/field-mapping` — save manual mappings `{mappings: {source_path: {target: registry_path}}, custom_fields: ["<flat name>", ...]}`. `source_path` is a source field name or a dotted sub-field path `parent.sub` (parent must be a structured/repeated-structured source field, `sub` one of its sub-fields; a whole-field mapping of `parent` and its sub-field mappings are mutually exclusive). `target` is `attr`, `attr.subfield`, or an indexed path `attr.N` / `attr.N.sub` (N is 1-based; requires a `repeated_*` registry kind — 422 on scalar/structured attributes). Indexed targets coexist with whole/broadcast claims on the same attribute (kind-compatible); apply evaluates non-indexed mappings first, then indexed assignments sorted by target, so indexed values override broadcast values in their exact slot; exact duplicate indexed targets still 422. A whole-attribute target `X` and any `X.subfield` target are mutually exclusive claims across all sources (422 on overlap, regardless of payload key order). Empty strings are stripped from repeated-scalar target values at apply time. `custom_fields`: flat names (`[a-z_][a-z0-9_]*`, ≤ 64), no duplicates, no overlap with observed `source_fields`. Flat mapping source keys must be observed or custom (422 otherwise). Custom fields are dormant in the pipeline until the ingested feed supplies the key. Errors: 422 `{"errors": ["key: message", ...]}`
- `POST /api/feed-sources/{id}/field-mapping/auto` — run auto-mapper on demand (whole-field passes first — auto, then synonym — then a sub-field pass; whole-field mappings suppress sub matching for their parent, and existing sub-mappings block whole-field claims; a whole-attribute target `X` and any `X.subfield` target are mutually exclusive claims in the matcher as well — a claimed whole `X` blocks sub claims on `X.*` and vice versa, mirroring the PUT 422 rule). Only triggered by the operator button (pipeline runs and dry-runs never auto-match). Preserves manual entries and `custom_fields`.

### Ingestion Runs
- `GET /api/feed-sources/{id}/ingestion-runs` — history (limit=50 default), includes error details

### Quality Findings
- `GET /api/feed-sources/{id}/quality-findings` — current findings grouped by severity/rule. Response: `{ingestion_run_id, counts: {critical, warning, info}, product_count, delta: {fixed, new, remaining}, has_previous: bool, prev_counts: {critical, warning, info} | null, findings: [...]}`. `delta` carries the latest run's fixed/new/remaining counters; `has_previous`/`prev_counts` hold whether an older run exists and its per-severity counts (null when no previous run). Delta key is `(code, product_id, field)` — a message-only change counts as remaining.
- `GET /api/feed-sources/{id}/quality-history?limit=30` — per-run severity + delta counters for charting. Response `{rows: [{id, started_at, product_count, critical, warning, info, fixed, new, remaining}]}`, rows **ascending** (oldest first). `limit` 1–100 (default 30). 404 unknown feed source.

### Products
- `GET /api/feed-sources/{id}/products` — paginated staged products. Params: `stage` (`raw` default / `processed`), `page`, `page_size` (≤200), `q` (id/title substring — matches `raw_data` title in raw stage, `processed_data` title in processed stage), `status` (`active`/`removed`/`all`), `sort` (`product_id`/`title`/`status`/`last_seen_at`, `-` prefix for descending; title sorts by the stage's data). Response: `{items, fields, total, page, page_size}` where `fields` is the sorted union of the stage's data keys across the returned rows (drives the UI column picker) and each item carries its full `raw_data` alongside the baseline fields (`title`, `description`, `link`, `image_link`, `availability`, `price`, `condition`). In `processed` stage, baseline/dynamic values resolve from `processed_data` (the post-pipeline-module state; falls back to `raw_data` for rows not yet processed), and items additionally carry `processed` (bool), `excluded` (bool — product dropped/errored by a pipeline module), and the full `processed_data` object
- `GET /api/feed-sources/{id}/products/{product_id}` — single product with status, hashes, full `raw_data`, `processed_data` (nullable) and `excluded`
- `POST /api/feed-sources/{id}/products/lookup` — batch value lookup over staged products. Body: `{field (registry attribute path, default "id"), values (1–10 000, deduped server-side), extraFields (0–20)}`. `field` supports the 1-based indexed grammar `attr | attr.sub | attr.N | attr.N.sub` (N ≤ 10 000; indexed paths match one list element exactly). Response `{matches: {<value>: {count, sample: {product_id, status, excluded, title, brand, availability, <extraFields…>} | null}}}` — `count` = staged products (any status) whose `raw_data[field]` contains the value (scalar equality, repeated fields match any element, `attr.sub` subfields resolve; mirrors the custom_labels plugin's match semantics); `sample` = the match with the lowest `product_id`. 404 unknown feed source; 422 invalid body; 503 database unavailable.
- `GET /api/feed-sources/{id}/fields` — unified field descriptors for the field pickers. Response: `{fields: [{name, kind, sub_fields: [{name, kind?}], max_repeats}]}` — source fields from the persisted mapping document (sub-kind `repeated_scalar` under `repeated_structured` parents, `scalar` otherwise; `max_repeats` = observed maximum for `repeated_*` kinds, 1 for non-repeated), baseline fields merged as scalars when absent, sorted by name. **Breaking change (2026-09-10):** previously returned `{fields: string[]}`.


### Export History
- `GET /api/feed-sources/{id}/export-history` — list versions (`source` ∈ `scheduled` | `manual` | `rollback`)
- `GET /api/feed-sources/{id}/export-history/{v}/diff?against={v2}` — field-based diff (per product + attribute, old vs new) plus `findings`: QC findings delta grouped by rule (`a_qc`/`b_qc`, `totals {added, fixed, persisted}`, `rules[{code, severity, added, fixed, persisted, sample_added, sample_fixed, sample_persisted}]`, samples capped at 20 product ids)
- `GET /api/feed-sources/{id}/export-history/{v}/content` — raw stored XML for a version, `application/xml`. 404 when the version row or its stored file is gone (retention-pruned). Auth + scope required.
- `POST /api/feed-sources/{id}/export-history/{v}/rollback` — append-only rollback, creates new version

### Export Token
- `POST /api/feed-sources/{id}/export-token/rotate` — rotates to a new random token, old URL invalid immediately. Returns `{export_token, export_url}`
- `PUT /api/feed-sources/{id}/export-token` — **admin only**. Sets a custom token. Body `{export_token}`; charset `[A-Za-z0-9_~-]`, length 1–64. 403 non-admin, 404 unknown feed source, 409 token already in use, 422 invalid value. Returns `{export_token, export_url}`

### Dashboard Summary
- `GET /api/dashboard/summary` — aggregated view for dashboard (clients, feed sources, last run status, `runs_by_day`: 14-day `{date, success, error}` counts, ascending). Each `clients[].feed_sources[]` entry carries `quality: {critical, warning, info}` read from that feed source's latest export run (zeros when it has none; the counts drive the feed-card badge).

### Feed Dashboard
- `GET /api/feed-sources/{id}/dashboard` — single aggregate for the per-feed dashboard. Response: `{kpi: {raw_items, valid_items, excluded_items, last_duration_s, readiness_rate}, volume_trend: [{date, raw, exportable}] (30 days, ascending), stage_funnel: [{stage, passed, dropped}] (ingest → mapping → staging → run_plugins → quality_check → export; cumulative passed from the latest run's statistics), quality: {critical, warning, info, readiness_rate}, recent_runs: [{id, status, started_at, duration_s, failed_count}] (last 10, ascending)}. `kpi.raw_items` is the latest run's ingested product count from its mapping statistics (`statistics.mapping.applied`), falling back to `processed_count` for legacy runs without statistics. Empty feed → zeroed KPIs, empty arrays, readiness 1.0. 404 unknown feed source.

## Plugins
- `GET /api/plugins` — manifests of all registered plugins (enabled + disabled)
  Returns: `[{id, name, version, enabled, manifest, used_by_feed_sources}]`
- `PUT /api/plugins/{plugin_id}/enabled` — enable/disable plugin (admin only; registry-wide state); returns 409 when disabling a plugin used by ≥1 feed source, 403 for non-admin users

### Plugin Config (Reserved Routes)
- `GET /api/plugins/{plugin_id}/config?client_id=&feed_source_id=` — get config at scope (omitted = global). Response carries `X-Plugin-Data-Version: <row id>` when a stored row exists (header absent = no row, version null); the id is the revision token — every PUT creates a new row, so the id strictly increases per write.
- `PUT /api/plugins/{plugin_id}/config?client_id=&feed_source_id=&expected_version=` — full-replace config, validated against `config_schema`
  Returns 422 `{"errors":[...]}` on validation failure. `expected_version` (optional, optimistic locking): absent = unchecked legacy replace; `"null"` succeeds only if no row exists; an integer row id succeeds only if it matches the current row. Mismatch → 409 `{"detail": {"message", "current_version"}}`. Non-integer value → 422.

### Plugin Data (Reserved Routes)
- `GET /api/plugins/{plugin_id}/data?client_id=&feed_source_id=` — get data at scope. Carries `X-Plugin-Data-Version` identically to config.
- `PUT /api/plugins/{plugin_id}/data?client_id=&feed_source_id=&expected_version=` — full-replace data, validated against `data_schema`; `expected_version` semantics identical to config.

**Scope rules:**
- At most one of `client_id`, `feed_source_id` (400 if both)
- Scope must be declared in manifest (`config_scope` / `data_scope`)
- `global` = neither parameter provided

### Plugin-Contributed Routes
Plugins may register custom routes under `/api/plugins/{plugin_id}/...` via `register_routes(router)`. All plugin-contributed routers are mounted behind the central `enforce_scope_access` dependency, so every plugin route requires authentication and validates any `client_id`/`feed_source_id` it carries (path or query) against the caller's assigned clients — isolation is not opt-in per plugin.
**Reserved sub-paths (enforced by contract test):**
- `/api/plugins/{plugin_id}/config` — core config endpoints
- `/api/plugins/{plugin_id}/data` — core data endpoints

Plugin routes must not use these prefixes. Example: Category plugin uses `/api/plugins/category/stats`, `/api/plugins/category/matches`.

- `POST /api/plugins/category/validate` — validates a draft set of category rules before saving. Body: `{rules}`. Returns `{status: "ok"}` or 422 `{"errors": [...]}` listing **every** invalid rule (bad id, unknown operator, empty source_value, or a taxonomy_id not found in the taxonomy) — one entry per problem, `rules[i]: …`-prefixed.
- `GET /api/plugins/category/taxonomy/languages` — lists available taxonomy languages currently loaded from the plugin's CSV files.
- `GET /api/plugins/category/taxonomy/search?language=&q=&limit=&offset=` — searches taxonomy entries by path segment, with startswith matches ranked ahead of contains matches. 422 for an unknown language.
- `GET /api/plugins/category/taxonomy/validate?taxonomy_id=` — checks a single taxonomy id against the loaded taxonomy; returns `{valid, path}`.
- `POST /api/plugins/category/taxonomy/fetch` — **admin-only (403 for non-admins)**. Fetches Google's official taxonomy file for a requested language and replaces the local CSV (de-DE only). 422 for non-fetchable languages; 502 on upstream fetch failure or invalid/too-small upstream data; 500 if the local taxonomy file cannot be written.
- `GET /api/plugins/category/stats?feed_source_id=` — categorization statistics for a feed source. Response `{total, buckets: {manual, auto, excluded, uncategorized}, rules: {rule_id: count}}`, computed over active, non-excluded staged products; products with no recorded provenance count as `uncategorized`, and rule counts include every product carrying a `_category_rule_id`.
- `GET /api/plugins/category/matches?feed_source_id=&rule_id=&limit=&offset=` — paged list of products matched by a rule. Response `{total, items: [{product_id, title}]}` with titles coalesced from processed then raw data, ordered by product_id; limit 1–200 (default 50), offset ≥ 0.
- `GET /api/plugins/category/product?feed_source_id=&product_id=` — full categorization state for a single staged product. Response `{product_id, title, provenance, rule_id, google_product_category, status}`. 404 if the product is unknown, removed, or excluded.
- All category routes carrying a `feed_source_id` are scope-enforced: 404 on unknown feed sources and on feed sources not assigned to the requesting user; 503 when the database is unavailable.

- `POST /api/plugins/filter/preview` — live filter preview. Body: `{feed_source_id, conditions}` (same condition shape as the filter config). Response `{total, pass, fail}` counting active, non-excluded staged products. 404 unknown or unassigned feed source (scope checked on the body param); 422 `{"errors": [...]}` on invalid conditions.
- `POST /api/plugins/custom_labels/preview` — live custom-labels preview. Body: `{feed_source_id, rules, slotIds, sample_size}` (1–50, default 5). Response `{total, labeledAny, rules: {id: {matched, labeled, sample}}, slots: {slot: {labeled, coverage, rules}}}` over active, non-excluded staged products; `labeledAny` counts products labeled in at least one slot (fallback wins included). Evaluation mirrors the plugin's run-time `process()` exactly (first-match-wins per slot, token skip, first-rule fallback); `labeled` per rule counts only template-rendered wins, fallback wins credit the slot. 404 unknown or unassigned feed source (scope checked on the body param); 422 `{"errors": [...]}` on invalid rules; 503 database unavailable.

- `POST /api/plugins/enrichment/scan` — AI attribute scan. Body: `{feed_source_id, limit}` (1–50, default 20). Finds active, non-excluded staged products missing any configured `targetFields` value (skipping products whose missing fields are all pinned), asks the AI service per product (`attribute_enrichment` task, `{title, description}` inputs), and stores successful values as pending suggestions in the plugin's feed-source-scoped data. Response `{scanned, with_suggestions, failed}`. 503 when no AI provider is configured; 404 unknown or unassigned feed source (scope checked on the body param).
- `POST /api/plugins/enrichment/accept` — accept suggestions into pinned values. Body: `{feed_source_id, expected_version, items: [{product_id, fields}]}`. Moves the selected suggestion fields into `pinned` and clears them from `suggestions` (empty product keys dropped). Pinned values win over feed values in the pipeline.
- `POST /api/plugins/enrichment/discard` — same shape as accept; deletes the selected suggestion fields.
- `POST /api/plugins/enrichment/unpin` — same shape; deletes the selected pinned fields.
- All enrichment mutation routes: 409 on stale `expected_version` (optimistic locking via the generic plugin-data helpers), 404 unknown or unassigned feed source, 503 database unavailable; unknown product/field items are a no-op.

- `GET /api/plugins/rules/ai/templates?feed_source_id=&task_type=` — prompt templates usable by a feed source for one task type. Returns `{items: [{id, name, task_type, client_id, version, is_active}]}`: global templates plus the feed source's client templates, newest `version` first. `task_type=rule_value` returns `{items: []}` (no templates apply); a `task_type` outside the rules-consumable structured set (`policy_check`, `image_quality`, unknown) → 422; 404 unknown or unassigned feed source; 503 database unavailable.
- `POST /api/plugins/rules/ai/preview` — **render-only** preview of an `op=ai` rule action (zero AI cost, no usage row). Body: `{feed_source_id, taskType, templateId? | (system, user, variables?), product_id?}`. Exactly one of `templateId` or an inline draft (`system`/`user`/`variables`) must be provided — both or neither → 422; an inline draft additionally requires `taskType: "rule_value"`, and a template preview requires `taskType` in the rules-consumable structured set (`policy_check`/`image_quality` → 422). The sample product is the first active, non-excluded staged product (optionally narrowed by `product_id`). Response `{messages, used_variables, warnings, errors}`; placeholders render through the injection-safe engine (`{{var}}` → XML-escaped `<data>` tags, lenient — a variable missing from the sample renders empty and is reported in `warnings`). 422 with `{errors, warnings}` on template validation failures; distinct 404 details: `"feed source not found"` vs `"no sample product found"`; 503 database unavailable. Scope is checked on the body-carried `feed_source_id` (`ensure_feed_source_access`).

## Registry
- `GET /api/registry/attributes` — full GMC Attribute Registry (from `backend/registry/attributes.json`)
  Each attribute includes `baseline_required: boolean` — true for the baseline-required set (spec §7: `id`, `link`, `image_link`, `availability`, `price`, `condition`, and the `title`/`structured_title`, `description`/`structured_description` alternative-pair members); false otherwise.
  Regeneration is a CLI script: `cd backend && uv run python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json`
- `GET /api/registry/attributes?feed_source_id=N` — same registry, plus per-feed-source `max_repeats` (max observed element count of `repeated_*` attributes, derived per request from staged `processed_data` with `raw_data` fallback, `yield_per=1000` streaming) and sub-field `kind` (`repeated_scalar` under `repeated_structured` parents, `scalar` otherwise). Drives the four field pickers (Mapping/Rules/Filter/Labelizer) so their lists are identical. Client-scoped users (ADR 0009) only see feed sources assigned to their clients — unknown *or unassigned* `feed_source_id` returns 404.

## Public Export Endpoint
- `GET /export/{token}.xml` — **unauthenticated**, serves static XML file
  - Token = `FeedSource.export_token` (non-guessable, 32 bytes URL-safe)
  - File path: `{export_dir}/published/{feed_source_id}.xml`
  - Atomic publish: written to temp → `os.replace()`
  - No feed source ID exposed in URL
  - 404 if token not found or file missing

## Dry Run
- `POST /api/feed-sources/{id}/dry-run` — execute pipeline without export, returns findings preview plus AI enrichment suggestions
  `{limit: number}` — max products to process
  Response includes `ai_suggestions: {product_id: {field: value}}` when `configuration.ai_enrichment` is enabled (generated but **not persisted**; the normal run does persist into the Enrichment review store)

## Error Responses
- `401` — invalid/missing session, or deactivated user
- `403` — admin-only operation by a non-admin (e.g., client CRUD, `/api/admin/*`)
- `404` — resource not found; also unassigned client/feed-source access (no existence leak)
- `422` — validation error: `{"errors": ["message", ...]}`
- `503` — database unavailable

## Key Files
- `app/routes/*.py` — all route definitions
- `app/routes/plugins.py` — plugin config/data endpoints with scope resolution
- `app/routes/export_public.py` — public export endpoint
- `app/schemas/*.py` — Pydantic request/response models