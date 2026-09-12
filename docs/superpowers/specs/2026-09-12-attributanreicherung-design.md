# Z4: Attributanreicherung (Attribute Enrichment) — Design

Date: 2026-09-12
Status: Approved in brainstorming (operator)
Baseline: main at 5abfd44 (Z1 + Z2 specs committed, not yet implemented)
Roadmap: `2026-09-12-ai-restarbeiten-design.md` — this is cycle Z4.

## Decisions (operator)
- **Core plugin `enrichment`** (pattern of rules/filter/category) — no new tables, three-tier scope merge and pipeline-editor integration come free.
- **Scan** on the plugin page against a missing-fields query; batched synchronous requests (default 20, max 50), repeatable.
- **Review flow per field** + bulk-accept buttons; suggestions never write product data directly — acceptance is the only write path.
- Pinned values **win over feed-provided values** (explicit user decision); "only if missing" mode out of scope.

## Plugin `enrichment`

### Manifest & registration
`plugins/core/enrichment/plugin.json` — `extension_point: pipeline_module`, frontend component + icon. Contract suite (`test_plugin_contract.py`) must pass.

### Config (PluginConfig, three-tier merge)
`{isActive: bool, targetFields: string[]}` — default `["color", "material", "size", "gtin"]`. `validate_config`: `targetFields` is a non-empty list of non-empty strings. `targetFields` drives the scan's missing-query only; the AI output schema comes from the prompt.

### Data (PluginData, feed_source scope)
`{"suggestions": {product_id: {field: value}}, "pinned": {product_id: {field: value}}}` — both keys optional, default `{}`.

### Prompt
Builtin `attribute_enrichment` task spec (extracts color/material/size/gtin as JSON from title+description). Admins override via the prompt template library (global or per client); the UI renders whatever fields the AI JSON returns.

### Pipeline application
`prepare_run` builds the pinned dict from merged data; `process(product)` applies `pinned[product_id]` to a copy — pinned fields overwrite feed values. Products without pins pass through untouched.

## Plugin routes (register_routes; all carry `feed_source_id` in the body → `ensure_feed_source_access`)

### POST /plugins/{id}/scan
`{feed_source_id, limit}` (limit 1–50, default 20).
Query: staging products `status=active, excluded=false`, **missing a targetField in `raw_data`** (null or empty), not fully pinned for the missing fields, ordered by id, limit.
For each: `AiService.run_task("attribute_enrichment", {title, description}, client_id, feed_source_id)` via `asyncio.gather` (AiService's per-provider semaphore throttles concurrency; breaker degrades per product).
- Non-null fields from the AI JSON are stored under `suggestions[product_id]` (re-scan overwrites pending suggestions for those products — AI cache makes it free).
- Per-product fallback (no provider, circuit open, invalid response) counts as `failed`; no suggestion stored.
- Response: `{scanned, with_suggestions, failed}`.
- Synchronous in-request batching is the deliberate ceiling (`ponytail:` background scans only when batch limits demonstrably fail).

### POST /plugins/{id}/accept
`{feed_source_id, expected_version, items: [{product_id, fields: [...]}]}` — moves the selected suggestion fields into `pinned`, removes them from `suggestions` (drop empty product keys).

### POST /plugins/{id}/discard
Same shape — deletes the selected fields from `suggestions`.

### POST /plugins/{id}/unpin
Same shape — deletes the selected fields from `pinned` (undo path for wrongly accepted values).

All three are read-modify-write on the PluginData row with `expected_version` → 409 on conflict (existing optimistic-locking pattern). Concurrent scan + accept → 409, UI retries.

## Frontend (plugin page surface, Two-Surface model)
- Scan button + limit Select; result toast (`scanned / with_suggestions / failed`).
- Suggestions grouped by product: field checkboxes with current vs. suggested value; "Ausgewählte übernehmen", "Alle übernehmen", per-field verwerfen.
- Pinned list per product with "Pin entfernen" (unpin).
- No Products-page integration in Z4.
- i18n en + de following the existing plugin-UI namespace pattern.

## Edge cases (documented behavior)
- No AI provider configured / circuit open → scan returns `failed` counts, UI shows a hint.
- Product vanishes from the feed between suggestion and accept → accept still works; the pin applies only when the product is present again.
- Feed source deletion cascades plugin data (existing FK behavior).
- AI JSON fields outside `targetFields` are stored and rendered all the same (prompt is the contract, not the config).

## Testing
- Backend: scan query (missing-field, pinned-skip, ordering, limit), gather + per-product fallback counting, suggestion overwrite on re-scan, accept/discard/unpin incl. 409, process() pinned precedence, contract suite.
- Frontend: EnrichmentUI renders suggestions + checkboxes, accept flow calls route, unpin; i18n parity.

## Docs (same commit)
`backend/docs/plugins.md` (new core plugin), `backend/docs/api.md` (4 plugin routes), `docs/decisions.md` (Z4 entry), `frontend/docs/architecture.md` / `frontend/docs/plugin-uis.md` (new plugin UI).

## Out of scope
Auto-mode without review; background scans; Products-page bulk selection; title_optimization / category_classification as suggestion tasks (same infrastructure, later cycle); per-suggestion provenance (which prompt version produced it).
