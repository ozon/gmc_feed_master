# Backend API Reference

## Authorization (roles)

Two roles: `admin` and `user` (literal strings on `users.role`).

- The seed user created at startup (`INITIAL_USERNAME`/`INITIAL_PASSWORD`) is `admin`; the m11 migration promoted all pre-existing users to `admin`.
- A `user` can be assigned to multiple clients (`user_clients` join table) and has full functional scope inside them (runs, exports, plugin configs, monitoring).
- Non-DB fallback mode (session store injected, no PostgreSQL boundary): treated as admin/unrestricted.

### Enforcement matrix

| Resource | admin | user (assigned) | user (not assigned) |
|---|---|---|---|
| `GET /clients`, `GET /dashboard/summary` | all clients | assigned clients only | n/a (filtered out) |
| Client-scoped routes (`/clients/{id}/…`) and feed-source-scoped routes (`/feed-sources/{id}/…`, products, pipeline, monitoring, export-history, dry-run, plugin config/data with `client_id`/`feed_source_id` scope) | full | full | **404** (no existence leak) |
| Client create/update/delete | allowed | **403** | **404** |
| `/admin/*` | allowed | **403** | **403** |
| Public export endpoint (`/export/{token}.xml`) | token-auth, unchanged | unchanged | unchanged |

Enforcement lives in `app/access.py`: `get_current_user` (loads role + assigned client ids per request; 401 for missing/inactive users), `require_admin` (403), and router-level `enforce_scope_access` (reads `client_id`/`feed_source_id` from path AND query params — plugin scope params are query params). Role/assignment changes apply on the next request; a password reset bumps `revocation_generation`, invalidating existing sessions. Deactivated users (`is_active=false`) cannot log in and existing sessions die.

## Authentication
All endpoints (except `/health` and `/export/{token}.xml`) require a valid session cookie.
- `POST /auth/login` — `{username, password}` → sets `HttpOnly; Secure; SameSite=Lax` cookie; rejects inactive users (401)
- `POST /auth/logout` — clears session
- `POST /auth/password` — change password (requires PostgreSQL session store)
- `GET /auth/me` — returns `{"username": str, "role": "admin"|"user", "client_ids": list[int] | null}` (`null` = admin/unrestricted; a sorted list of assigned client ids for users)
- `POST /auth/interaction` — refreshes session idle timer

## Admin Area (admin only)

### Users
- `GET /admin/users` — list `[{id, username, role, is_active, client_ids}]`
- `POST /admin/users` (201) — create `{username, password, role: "admin"|"user", client_ids?, is_active?}`; 409 on duplicate username
- `PATCH /admin/users/{user_id}` — update `{role?, is_active?, client_ids?}` (client_ids full-replaces assignments); 404 unknown user
- `POST /admin/users/{user_id}/password` (204) — set new password `{new_password}` (revokes the user's sessions); 404 unknown user

### Settings
- `GET /admin/settings` — `{staging_removal_retention_days, staging_history_retention_days, ingestion_run_retention_days, ai_usage_retention_days, ai_cache_retention_days}`; seeds the single `global_settings` row with 90s on first read
- `PUT /admin/settings` — update retention days (each ≥ 1; 422 otherwise). The nightly purge jobs read these values (fallback 90 while no row exists)

### AI Administration
All routes require the admin role. `api_key` is never included in any response.

- `GET /admin/ai/providers` — list provider configs `[{id, name, provider_type, base_url, model, input_price_per_mtok, output_price_per_mtok, max_concurrency, timeout_s, enabled, is_default}]`
- `POST /admin/ai/providers` — create `{name, provider_type="openai_compatible", base_url, api_key?, model, input_price_per_mtok?, output_price_per_mtok?, max_concurrency=4, timeout_s=30, enabled=true, is_default=false}`; setting `is_default` clears the flag on all other configs
- `PATCH /admin/ai/providers/{id}` — partial update; `api_key` absent = unchanged, explicit `""` = cleared
- `DELETE /admin/ai/providers/{id}` (204) — delete config; runs read config at call time, so deletion just makes the next AI call fall back
- `POST /admin/ai/providers/{id}/test` — live probe completion (`"Reply with OK"`); returns `{"status": "ok", latency_ms, prompt_tokens, completion_tokens}` or `{"status": "error", "error_code"}`
- `GET /admin/ai/usage?group_by=client|feed_source|task_type|day&client_id=&feed_source_id=&task_type=&from=&to=` — aggregated `{"rows": [{group_key, calls, cache_hits, prompt_tokens, completion_tokens, cost_usd}]}`; 422 on other group_by values

### Prompt Templates (admin only)

Versioned, immutable prompt templates per task type. Editing = creating a new version; old versions stay queryable. No PATCH/DELETE — deactivation happens only by activating another version. Placeholder syntax is `{{variable}}`; values are XML-escaped into `<data>` tags at render time (prompt-injection isolation), and placeholders must be canonical variables of the task type and declared in the template's `variables` list.

- `GET /admin/ai/prompt-templates?task_type=&client_id=` — all versions (ordered task_type, client_id, version desc)
- `GET /admin/ai/prompt-templates/{id}` — single version
- `POST /admin/ai/prompt-templates` — create new version `{task_type, client_id?, name, system_prompt, user_prompt, variables, activate=true}`; 422 with `{errors, warnings}` on placeholder violations; 404 unknown client; 409 on concurrent template modification (integrity conflict or DB deadlock); `activate` flips the single-active flag per (task_type, scope)
- `POST /admin/ai/prompt-templates/{id}/activate` — switch/rollback the active version in the template's scope; 409 on concurrent activation (integrity conflict or DB deadlock)
- `POST /admin/ai/prompt-templates/preview` — dry-run render, zero AI cost: `{task_type, template_id? | (system_prompt, user_prompt, variables?), product? | (feed_source_id, product_id?)}` → `{messages, used_variables, warnings, errors}`; 422 on validation errors; 404 when no staging sample matches

`AiService.run_task` resolves client-scoped active → global active → builtin registry default; the resolved version (`tmpl:{id}:v{version}` / `builtin`) is part of the AI result-cache key, so new versions invalidate and rollbacks resume old cache entries.

### Scheduler
- `GET /admin/scheduler` — registered job overview `[{id, trigger}]`; 503 when no scheduler is running (app lifespan not started)

## Health
- `GET /health` → `{"status": "ok"}`

## Clients
- `GET /clients` — list clients (admin: all; user: assigned only)
- `POST /clients` — create client `{name, status?}` — **admin only (403)**
- `PUT /clients/{id}` — update client `{name?, status?}` — **admin only (403)**
- `DELETE /clients/{id}` — delete client (cascades: feed sources, pipelines, staging, exports) — **admin only (403)**

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
- `GET /feed-sources/{id}/pipeline` — get active pipeline definition: `{instances: [{id, position, plugin_id, name, configuration, enabled}]}`
- `PUT /feed-sources/{id}/pipeline` — save pipeline definition (UI builder); upsert-by-id — instances carrying an `id` from a previous GET/PUT are updated in place (stable ids), instances without `id` are created, omitted instances are deleted. Input shape: `{instances: [{id?, plugin_id, name?, configuration, enabled?}]}`; `id` values not belonging to this pipeline are rejected (422 `{"errors": [...]}`). Reordering is safe against the `(pipeline_id, position)` unique constraint (two-pass positioning)
  ```
  {instances: [{id, plugin_id, position, name, configuration, enabled}]}
  ```
- `PATCH /feed-sources/{id}/pipeline/instances/{instance_id}` — toggle a single instance's `enabled` flag with immediate persist (per-instance Switch in the pipeline page). Body: `{"enabled": bool}` → `200 {"id": int, "enabled": bool}`; 404 for unknown feed source or instance (instance must belong to the feed source's active pipeline). Also rebuilds `pipeline.definition` so the JSONB mirrors the rows (string plugin ids, same as PUT)

### Field Mapping
- `GET /feed-sources/{id}/field-mapping` — get mapping document: `{version, auto_mapped, source_fields, mappings, custom_fields}`
- `PUT /feed-sources/{id}/field-mapping` — save manual mappings `{mappings: {source_path: {target: registry_path}}, custom_fields: ["<flat name>", ...]}`. `source_path` is a source field name or a dotted sub-field path `parent.sub` (parent must be a structured/repeated-structured source field, `sub` one of its sub-fields; a whole-field mapping of `parent` and its sub-field mappings are mutually exclusive). `target` is `attr`, `attr.subfield`, or an indexed path `attr.N` / `attr.N.sub` (N is 1-based; requires a `repeated_*` registry kind — 422 on scalar/structured attributes). Indexed targets coexist with whole/broadcast claims on the same attribute (kind-compatible); apply evaluates non-indexed mappings first, then indexed assignments sorted by target, so indexed values override broadcast values in their exact slot; exact duplicate indexed targets still 422. A whole-attribute target `X` and any `X.subfield` target are mutually exclusive claims across all sources (422 on overlap, regardless of payload key order). Empty strings are stripped from repeated-scalar target values at apply time. `custom_fields`: flat names (`[a-z_][a-z0-9_]*`, ≤ 64), no duplicates, no overlap with observed `source_fields`. Flat mapping source keys must be observed or custom (422 otherwise). Custom fields are dormant in the pipeline until the ingested feed supplies the key. Errors: 422 `{"errors": ["key: message", ...]}`
- `POST /feed-sources/{id}/field-mapping/auto` — run auto-mapper on demand (whole-field passes first — auto, then synonym — then a sub-field pass; whole-field mappings suppress sub matching for their parent, and existing sub-mappings block whole-field claims; a whole-attribute target `X` and any `X.subfield` target are mutually exclusive claims in the matcher as well — a claimed whole `X` blocks sub claims on `X.*` and vice versa, mirroring the PUT 422 rule). Only triggered by the operator button (pipeline runs and dry-runs never auto-match). Preserves manual entries and `custom_fields`.

### Ingestion Runs
- `GET /feed-sources/{id}/ingestion-runs` — history (limit=50 default), includes error details

### Quality Findings
- `GET /feed-sources/{id}/quality-findings` — current findings grouped by severity/rule

### Products
- `GET /feed-sources/{id}/products` — paginated staged products. Params: `stage` (`raw` default / `processed`), `page`, `page_size` (≤200), `q` (id/title substring — matches `raw_data` title in raw stage, `processed_data` title in processed stage), `status` (`active`/`removed`/`all`), `sort` (`product_id`/`title`/`status`/`last_seen_at`, `-` prefix for descending; title sorts by the stage's data). Response: `{items, fields, total, page, page_size}` where `fields` is the sorted union of the stage's data keys across the returned rows (drives the UI column picker) and each item carries its full `raw_data` alongside the baseline fields (`title`, `description`, `link`, `image_link`, `availability`, `price`, `condition`). In `processed` stage, baseline/dynamic values resolve from `processed_data` (the post-pipeline-module state; falls back to `raw_data` for rows not yet processed), and items additionally carry `processed` (bool), `excluded` (bool — product dropped/errored by a pipeline module), and the full `processed_data` object
- `GET /feed-sources/{id}/products/{product_id}` — single product with status, hashes, full `raw_data`, `processed_data` (nullable) and `excluded`
- `POST /feed-sources/{id}/products/lookup` — batch value lookup over staged products. Body: `{field (registry attribute path, default "id"), values (1–10 000, deduped server-side), extraFields (0–20)}`. `field` supports the 1-based indexed grammar `attr | attr.sub | attr.N | attr.N.sub` (N ≤ 10 000; indexed paths match one list element exactly). Response `{matches: {<value>: {count, sample: {product_id, status, excluded, title, brand, availability, <extraFields…>} | null}}}` — `count` = staged products (any status) whose `raw_data[field]` contains the value (scalar equality, repeated fields match any element, `attr.sub` subfields resolve; mirrors the custom_labels plugin's match semantics); `sample` = the match with the lowest `product_id`. 404 unknown feed source; 422 invalid body; 503 database unavailable.
- `GET /feed-sources/{id}/fields` — unified field descriptors for the field pickers. Response: `{fields: [{name, kind, sub_fields: [{name, kind?}], max_repeats}]}` — source fields from the persisted mapping document (sub-kind `repeated_scalar` under `repeated_structured` parents, `scalar` otherwise; `max_repeats` = observed maximum for `repeated_*` kinds, 1 for non-repeated), baseline fields merged as scalars when absent, sorted by name. **Breaking change (2026-09-10):** previously returned `{fields: string[]}`.


### Export History
- `GET /feed-sources/{id}/export-history` — list versions (`source` ∈ `scheduled` | `manual` | `rollback`)
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
- `PUT /plugins/{plugin_id}/enabled` — enable/disable plugin (admin only; registry-wide state); returns 409 when disabling a plugin used by ≥1 feed source, 403 for non-admin users

### Plugin Config (Reserved Routes)
- `GET /plugins/{plugin_id}/config?client_id=&feed_source_id=` — get config at scope (omitted = global). Response carries `X-Plugin-Data-Version: <row id>` when a stored row exists (header absent = no row, version null); the id is the revision token — every PUT creates a new row, so the id strictly increases per write.
- `PUT /plugins/{plugin_id}/config?client_id=&feed_source_id=&expected_version=` — full-replace config, validated against `config_schema`
  Returns 422 `{"errors":[...]}` on validation failure. `expected_version` (optional, optimistic locking): absent = unchecked legacy replace; `"null"` succeeds only if no row exists; an integer row id succeeds only if it matches the current row. Mismatch → 409 `{"detail": {"message", "current_version"}}`. Non-integer value → 422.

### Plugin Data (Reserved Routes)
- `GET /plugins/{plugin_id}/data?client_id=&feed_source_id=` — get data at scope. Carries `X-Plugin-Data-Version` identically to config.
- `PUT /plugins/{plugin_id}/data?client_id=&feed_source_id=&expected_version=` — full-replace data, validated against `data_schema`; `expected_version` semantics identical to config.

**Scope rules:**
- At most one of `client_id`, `feed_source_id` (400 if both)
- Scope must be declared in manifest (`config_scope` / `data_scope`)
- `global` = neither parameter provided

### Plugin-Contributed Routes
Plugins may register custom routes under `/plugins/{plugin_id}/...` via `register_routes(router)`.
**Reserved sub-paths (enforced by contract test):**
- `/plugins/{plugin_id}/config` — core config endpoints
- `/plugins/{plugin_id}/data` — core data endpoints

Plugin routes must not use these prefixes. Example: Category plugin uses `/plugins/category/stats`, `/plugins/category/matches`.

- `POST /plugins/category/validate` — validates a draft set of category rules before saving. Body: `{rules}`. Returns `{status: "ok"}` or 422 `{"errors": [...]}` listing **every** invalid rule (bad id, unknown operator, empty source_value, or a taxonomy_id not found in the taxonomy) — one entry per problem, `rules[i]: …`-prefixed.
- `GET /plugins/category/taxonomy/languages` — lists available taxonomy languages currently loaded from the plugin's CSV files.
- `GET /plugins/category/taxonomy/search?language=&q=&limit=&offset=` — searches taxonomy entries by path segment, with startswith matches ranked ahead of contains matches. 422 for an unknown language.
- `GET /plugins/category/taxonomy/validate?taxonomy_id=` — checks a single taxonomy id against the loaded taxonomy; returns `{valid, path}`.
- `POST /plugins/category/taxonomy/fetch` — fetches Google's official taxonomy file for a requested language and replaces the local CSV (de-DE only). 422 for non-fetchable languages; 502 on upstream fetch failure or invalid/too-small upstream data; 500 if the local taxonomy file cannot be written.
- `GET /plugins/category/stats?feed_source_id=` — categorization statistics for a feed source. Response `{total, buckets: {manual, auto, excluded, uncategorized}, rules: {rule_id: count}}`, computed over active, non-excluded staged products; products with no recorded provenance count as `uncategorized`, and rule counts include every product carrying a `_category_rule_id`.
- `GET /plugins/category/matches?feed_source_id=&rule_id=&limit=&offset=` — paged list of products matched by a rule. Response `{total, items: [{product_id, title}]}` with titles coalesced from processed then raw data, ordered by product_id; limit 1–200 (default 50), offset ≥ 0.
- `GET /plugins/category/product?feed_source_id=&product_id=` — full categorization state for a single staged product. Response `{product_id, title, provenance, rule_id, google_product_category, status}`. 404 if the product is unknown, removed, or excluded.
- All category routes carrying a `feed_source_id` are scope-enforced: 404 on unknown feed sources and on feed sources not assigned to the requesting user; 503 when the database is unavailable.

- `POST /plugins/filter/preview` — live filter preview. Body: `{feed_source_id, conditions}` (same condition shape as the filter config). Response `{total, pass, fail}` counting active, non-excluded staged products. 404 unknown or unassigned feed source (scope checked on the body param); 422 `{"errors": [...]}` on invalid conditions.
- `POST /plugins/custom_labels/preview` — live custom-labels preview. Body: `{feed_source_id, rules, slotIds, sample_size}` (1–50, default 5). Response `{total, labeledAny, rules: {id: {matched, labeled, sample}}, slots: {slot: {labeled, coverage, rules}}}` over active, non-excluded staged products; `labeledAny` counts products labeled in at least one slot (fallback wins included). Evaluation mirrors the plugin's run-time `process()` exactly (first-match-wins per slot, token skip, first-rule fallback); `labeled` per rule counts only template-rendered wins, fallback wins credit the slot. 404 unknown or unassigned feed source (scope checked on the body param); 422 `{"errors": [...]}` on invalid rules; 503 database unavailable.

## Registry
- `GET /registry/attributes` — full GMC Attribute Registry (from `backend/registry/attributes.json`)
  Each attribute includes `baseline_required: boolean` — true for the baseline-required set (spec §7: `id`, `link`, `image_link`, `availability`, `price`, `condition`, and the `title`/`structured_title`, `description`/`structured_description` alternative-pair members); false otherwise.
  Regeneration is a CLI script: `cd backend && uv run python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json`
- `GET /registry/attributes?feed_source_id=N` — same registry, plus per-feed-source `max_repeats` (max observed element count of `repeated_*` attributes, derived per request from staged `processed_data` with `raw_data` fallback, `yield_per=1000` streaming) and sub-field `kind` (`repeated_scalar` under `repeated_structured` parents, `scalar` otherwise). Drives the four field pickers (Mapping/Rules/Filter/Labelizer) so their lists are identical. Client-scoped users (ADR 0009) only see feed sources assigned to their clients — unknown *or unassigned* `feed_source_id` returns 404.

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
- `401` — invalid/missing session, or deactivated user
- `403` — admin-only operation by a non-admin (e.g., client CRUD, `/admin/*`)
- `404` — resource not found; also unassigned client/feed-source access (no existence leak)
- `422` — validation error: `{"errors": ["message", ...]}`
- `503` — database unavailable

## Key Files
- `app/routes/*.py` — all route definitions
- `app/routes/plugins.py` — plugin config/data endpoints with scope resolution
- `app/routes/export_public.py` — public export endpoint
- `app/schemas/*.py` — Pydantic request/response models