# GMC Feed Master — Technical Specification

> Audience: Coding Agent (implementation)
> Reference document for GMC attributes: `gmc_def.md` (attached separately — required at implementation time to populate the Attribute Registry, see §5.6)


## 1. Purpose & Context

Modular delta-pipeline tool for generating GMC-compliant XML feeds. Replaces the existing static TSV-to-XML converter with a configurable, plugin-based system featuring a UI pipeline builder, quality scoring, and versioning. Feature-scope benchmark: Channable (reduced scope).

The tool generates **primary feeds** in the GMC sense: each exported XML feed is the authoritative product data source for its target market in the Merchant Center. GMC supplemental feeds (secondary layers matched via `id` on top of an existing primary feed) are out of MVP scope but architecturally anticipated (see `FeedSource.feed_type`, §4).

Greenfield implementation: a previous partial implementation exists but is discarded — no migration, no compatibility constraints.

## 2. Architecture Decisions (binding)

| Area | Decision |
|---|---|
| Backend | Python, FastAPI |
| Database | PostgreSQL, running as a Docker container |
| Backend/frontend deployment | Native on host (no container) |
| Frontend | React 19 + TypeScript (Vite), Mantine component library |
| Frontend server state | TanStack Query (caching, polling, invalidation after mutations). Server data is never duplicated into client-side stores |
| Frontend client state | React built-ins only (`useState`/`useReducer`/Context) — no global store library |
| Frontend tables & DnD | TanStack Table for data-dense tables; dnd-kit for the pipeline builder |
| Frontend forms | Schema-rendered forms (JSON Schema, Mantine-themed) for plugin UIs; TanStack Form for hand-built core forms |
| Tenancy model | Agency tool: 1 client → n feed sources |
| Feed type | Primary feeds only in MVP; `FeedSource.feed_type` keeps supplemental feeds extendable later |
| Feed structure | 1:1 — one feed source produces exactly one XML output |
| Feed delivery | Static XML file; Google retrieves it via scheduled HTTP fetch. Atomic publish: write to temp file, then `os.replace()` — Google never sees a partially written file |
| Extensibility | Plugin system: all product-processing logic lives in plugins, including the four core plugins (Labelizer, Rules, Category, Filter). Adding a plugin must never require core changes (§5). Core plugins ship in rudimentary form; full feature sets are defined in separate per-plugin specs (§5.9) |
| Pipeline configuration | UI pipeline builder (drag & drop of enabled plugins per feed source) |
| Module execution | Fixed order per feed source, as defined in the builder (no dynamic routing) |
| Background processing | FastAPI `BackgroundTasks` — no Celery/Redis |
| Scheduling | APScheduler in the FastAPI process; cron expression per feed source, interpreted in UTC; no catch-up after downtime (the next regular tick applies); UI offers presets (hourly/daily/weekly) plus free-text cron |
| Run concurrency | Lock per feed source: an overlapping run is skipped and logged ("previous run still active") |
| Access / auth | Single user (operator only), no client portal, no role model |
| Tool authentication | Simple login (username/password, session). Initial user seeded from env vars on first start; password changeable in the UI |
| Export endpoint security | Random, non-guessable URL token per feed source (no Basic Auth). Token rotation endpoint; the old URL becomes invalid immediately |
| Export history | Every XML export is versioned; field-based diff and rollback supported. Rollback is append-only: it creates a new version from the old state |
| Export history retention | Last N versions per feed source (default N=30, configurable); applies to rollback-created versions too |
| Field mapping | Auto mapper (registry-based suggestions) + manual mapper per feed source; no mapping templates (§6) |
| Custom labels | Labelizer plugin with dimensions (global + client scope, merged; client wins conflicts). No separate label matrix entity |
| Quality Check | Evaluative, not blocking: runs sequentially after the Module Runner, before the XML Writer; findings never prevent export; results shown only in the internal dashboard, no notifications |
| Quality Check rule scope | Full rule set from MVP, registry-driven where possible (§7) |
| Product variants | Full support for `item_group_id` including `color`/`size`/`gender`/`age_group` differentiation |
| Countries/languages | A client can have multiple feed sources targeting different countries/languages/currencies (one market per feed source) |
| Removed products | Omitted from the XML output (snapshot semantics). Known, accepted limitation: GMC expires items only 30 days after their last refresh |
| Shipping/tax | Out of MVP scope as a configuration layer — source data delivers complete `shipping`/`tax` values; nested structures pass through the pipeline unchanged (pass-through fidelity, §5.5) |
| Price normalization | Out of MVP scope — source data already delivers market-correct prices (net for US/CA, gross elsewhere), no conversion in the pipeline. Currency plausibility is still checked (§7, Currency consistency) |
| Ingestion error visibility | Status icon per feed source in the dashboard **and** a full error log with history |
| Implementation | Greenfield — the previous partial implementation is discarded |

## 3. Data Flow (reference)

```
Input Reader (XML/TSV/CSV/wide-format TSV → canonical product model, §5.5)
  → Field Mapping (auto mapper + manual mapper, §6)
  → Staging DB (delta-capable, hash-based: content_hash + config_hash)
  → Module Runner (fixed pipeline of enabled plugins, from the UI builder)
  → Quality Check (evaluative, sequential, non-blocking)
  → XML Writer (GMC-compliant, versioned, atomic publish)
  → Output (static file, retrieved via HTTP by Google)
```

## 4. Data Model (conceptual — the coding agent derives the concrete schema)

**Core entities:**

- **User** — single operator account (username, password hash). Seeded from env vars on first start.
- **Client** — name, contact details, status.
- **FeedSource** — belongs to a client; `feed_type ∈ {primary, supplemental}` (MVP: only `primary`; default `primary`); source format (XML/TSV/CSV/wide-format TSV); target country, language, currency; cron expression (UTC); source URL/upload reference; `field_mapping` (JSONB: source field → registry attribute path, §6); active pipeline reference; random `export_token` (non-guessable, part of the public export URL); `history_retention_count` (default 30); `volume_drop_threshold_pct` (default 20, see §7).
- **IngestionRun** — log entry per run: timestamp, feed source, status (success/error/skipped), error message/stack trace on failure, number of products processed/failed. Retention: 90 days. The dashboard shows both the current status (icon) and the list of these runs (history).
- **Plugin** — registry entry per discovered plugin: id, version, `enabled` (global toggle), manifest (JSONB), source path. Core plugins ship enabled; third-party plugins start disabled.
- **PluginConfig** — structural configuration per plugin (JSONB, validated against the manifest's `config_schema`), scoped per manifest (`global` / `client` / `feed_source`; three-tier merge, §5.3).
- **PluginData** — operational data per plugin (JSONB, validated against `data_schema`), scoped per manifest; edited via the plugin's menu item in the frontend.
- **ModulePipeline** — belongs to a feed source; ordered list of ModuleInstance (result of the UI builder).
- **ModuleInstance** — `plugin_id` reference (not a type enum), instance configuration (JSON), position in the sequence.
- **StagingProduct** — current normalized state per product/feed source in the canonical product model (§5.5), with `content_hash`, `config_hash`, `status` (active/removed), `last_seen_at`.
- **StagingHistory** — change history per product (a new entry is written only when a hash changes). Retention: 90 days; rows of `removed` products are purged together with the product.
- **QualityFinding** — result of the QC rules per product/run: rule ID, severity, affected field, message. Detailed findings are kept for the latest run per feed source only; per-severity counts persist in ExportRun.
- **ExportRun** — log per export: timestamp, feed source, number of products, number of findings by severity, reference to the stored XML version.
- **ExportVersion** — versioned XML snapshots per feed source for rollback/diff. Retention: last N (default 30). Rollback creates a new version (append-only).

**Delta mechanics:** Ingestion compares two hashes against the stored state:

- `content_hash` — SHA-256 over the canonical normalized product (sorted keys; includes nested structures). Field-mapping changes alter the normalized data and are therefore captured here automatically.
- `config_hash` — SHA-256 over everything output-relevant that applies **after** staging, resolved per feed source: the ordered pipeline definition (plugin instances incl. instance configs), the resolved PluginConfig + PluginData (including the three-tier scope merge, §5.3), and the plugin versions.

Unchanged (both hashes match) → only update `last_seen_at`, no re-run of the pipeline. Changed → re-run the pipeline for that product. Any plugin config, data, or version change therefore triggers reprocessing of the affected products on the next run — no manual trigger needed. Note: a **global**-scope config change (e.g. a shared Labelizer dimension) changes the resolved config for every feed source of every client using that plugin, and therefore triggers full reprocessing across all of them on their next run — an accepted trade-off for MVP simplicity over a more granular, per-scope hash.

Products missing from the source feed are set to `status=removed` (not deleted) and omitted from the XML output. If a removed product's id reappears in the source, it flips back to `active` and is reprocessed (hash comparison continues for removed products). Staging rows with `status=removed` are purged 90 days after removal.

## 5. Plugin System

**Core principle:** The system has no fixed module types. All product-processing functionality is provided by plugins. The four former modules ship as **core plugins** in exactly the same format as any future plugin — adding a plugin must never require changes to core code.

### 5.1 Package & discovery

- A plugin is a directory under `plugins/` containing `plugin.json` (manifest) + Python module + optional React component (TSX).
- At startup the core scans `plugins/`, validates manifests, and registers plugins in the `Plugin` table. Invalid manifest → plugin rejected, error logged, startup continues.
- Core plugins live in `plugins/core/` and ship enabled; third-party plugins start disabled.

### 5.2 Manifest (`plugin.json`)

```json
{
  "id": "labelizer",
  "name": "Labelizer",
  "version": "1.0.0",
  "extension_point": "pipeline_module",
  "config_schema": {},
  "config_scope": ["global", "client"],
  "data_schema": {},
  "data_scope": "client",
  "frontend": { "menu_item": "Labelizer", "icon": "tag", "component": "Editor.tsx" }
}
```

- `extension_point`: MVP implements only `pipeline_module`. The framework must allow adding further extension points (e.g. `quality_rule`, `input_reader`) later without contract changes.
- `config_scope` / `data_scope ∈ {global, client, feed_source}`; a plugin may declare any subset (e.g. `["global", "client"]` or `["global", "client", "feed_source"]`) — resolution follows the three-tier merge, §5.3.
- `frontend.component` is optional; without it, config/data UIs are auto-rendered from the JSON Schemas.

### 5.3 Three-level model

1. **Activation** — global toggle (`Plugin.enabled`). Only enabled plugins appear in the pipeline builder and the frontend menu.
2. **PluginConfig** — structural configuration, rarely changed (e.g. Labelizer dimensions). Validated against `config_schema`.
3. **PluginData** — operational data behind the plugin's menu item (rules, ID lists). Validated against `data_schema`, stored per declared scope.

**Scope resolution (three-tier, generic — applies to any plugin declaring more than one scope in its manifest):** `feed_source` wins where present, `client` is next, `global` is the fallback/merge base. The merge is per key: a key missing at `feed_source` level is taken from `client`; missing there too, from `global`. The generic merge replaces non-dict values per key — the more specific scope wins wholesale; plugins needing finer-grained merging of ordered lists define that in their own config resolution (as Labelizer does for dimensions, §5.9). A plugin need not declare all three scopes — e.g. Labelizer and Category declare only `["global", "client"]` for MVP (deliberate: their dimensions/rules are shared across all feed sources of a client, not per-market; see §5.9). `feed_source`-scoped configuration only applies to plugins that declare it.

### 5.4 Runtime contract

```python
class PipelineModulePlugin(Protocol):
    def validate_config(self, config: dict) -> None: ...
    def process(self, product: dict, config: dict, data: dict, ctx: RunContext) -> dict | None: ...
    def migrate_config(self, old_version: str, config: dict) -> dict: ...  # optional
    def register_routes(self, router) -> None: ...  # optional, namespaced under /plugins/{id}/ — the sub-paths `config` and `data` are reserved for the core-provided endpoints (§8) and MUST NOT be used by plugin-contributed routes
```

- `RunContext` provides: `client_id`, `feed_source`, `original_product` (read-only deep copy of the staged normalized product, post-mapping / pre-pipeline), run/logger references.
- Plugins may create any registry-known attribute on the product, regardless of the input feed's schema ("virtual fields", §5.7).
- Returning `None` drops the product from the pipeline. Any pipeline plugin may drop; every drop is logged with `plugin_id` and reason.
- Error isolation: an exception in `process()` marks the product as errored, the run continues, and the error is logged to the IngestionRun.
- Execution order: fixed per feed source, as arranged in the pipeline builder; `ModuleInstance` references `plugin_id`.

### 5.5 Canonical product model & nested/multi-value attributes

All components downstream of the readers work on exactly one JSON-native representation. Four attribute kinds:

| Kind | Example |
|---|---|
| Scalar | `"title": "…"` |
| Repeated scalar | `"additional_image_link": ["…", "…"]` |
| Structured (single) | `"installment": {"months": "12", "amount": "49.99 EUR"}` |
| Structured (repeated) | `"shipping": [{"country": "US", "price": "6.49 USD"}, …]` |

Pass-through fidelity is a hard requirement: nested structures that no plugin touches (e.g. `shipping`/`tax` delivered complete by the source) must reach the XML output unchanged.

### 5.6 GMC Attribute Registry

Core-owned, machine-readable registry derived from `gmc_def.md` (required at implementation time). Per attribute: kind (§5.5), ordered typed sub-fields, and constraints (enums, lengths, formats, cardinality, conditionality). Single source of truth driving:

- Readers: parsing + validation of the flat notation
- Field mapping: auto-mapper matching and the manual mapper's target dropdown, including sub-fields (§6)
- Quality Check: enum/length/format/cardinality rules evaluated declaratively (§7)
- XML Writer: element order, repetition, `g:` namespace

### 5.7 Path grammar & virtual fields

The addressable field universe is the Attribute Registry, not the input feed's schema — any registry attribute can be populated by plugins even if the source never delivers it. Uniform positional path grammar (1-based), used by field mapping, Rules, Filter, and Labelizer:

| Path | Meaning |
|---|---|
| `title` | scalar |
| `product_highlight.2` | 2nd element of a repeated scalar |
| `installment.months` | sub-field of a single structured attribute |
| `shipping.1.price` | sub-field of the 1st element of a repeated structured attribute |

Semantics: setting a position beyond the current length auto-extends the array (intermediate slots stay empty); empty elements are stripped from repeated fields before export; reading a non-existent position yields empty/null, not an error. Wildcards (`shipping.*.price`) are v1.1 scope — same dot notation as indexed paths, `*` in place of the index.

### 5.8 Input formats & flat-notation parsing (wide-format TSV)

- General: UTF-8 (BOM-tolerant); TSV = tab-delimited; CSV = delimiter sniffing (comma/semicolon), RFC-4180 quoting; source fetch over HTTP(S), optional Basic Auth, 60 s timeout, 500 MB size limit.
- Header `attr(sub1:sub2:…)`: values are split left-to-right by header arity; surplus colons in a value → row-level ingestion error (logged, row skipped).
- Same header column n times → repeated structured attribute (array of n structs, column order preserved).
- Comma-separated cell values → repeated scalar; quoted values may contain commas.
- Only the explicit `attr(sub:…)` notation is supported; bare structured columns relying on implicit sub-field order are rejected with a clear error.
- XML input maps natively onto the same canonical model.
- Naming note: "wide-format TSV" refers to one TSV file per feed source using repeated/annotated columns to encode structured attributes — not multiple external feeds merged into one (feed structure remains strictly 1:1, §2).

### 5.9 Core plugins (MVP — rudimentary scope)

The core plugins ship in **rudimentary form** for the MVP. This section defines only the minimal, contract-conforming behavior plus the binding design decisions already made; each plugin will receive its own detailed spec for the full feature set (authored separately).

1. **Labelizer** — populates `custom_label_0`–`custom_label_4` via **dimensions**. A dimension (PluginConfig, scopes global + client, merged) carries: `id`, `name`, `target_label` (the slot assignment lives in the dimension — there is no separate label matrix), `condition`, `label_value`. PluginData (client scope) supplies the operational payloads, e.g. product-ID lists per dimension. Slot conflicts: client dimensions evaluate before global ones; the first dimension matching a product claims the slot for that product. Validation: only `custom_label_0..4`, values ≤100 characters. **Scope decision:** deliberately client-scope only for MVP — dimensions are shared across all feed sources (markets) of a client; per-market labeling is out of MVP scope (would require declaring `feed_source` in the manifest and using the three-tier merge, §5.3). **MVP scope:** condition type `id_in_list` only; further condition types (`price_range`, `field_match`, derived buckets) per plugin spec.
2. **Rules (find/replace & set)** — operations on fields addressed via the path grammar (§5.7), evaluated in list order. `operation ∈ {replace, set}`: `replace` = regex or plain find/replace; `set` = assigns a value, creating the attribute if absent (virtual fields); `set` values support `{field}` placeholders interpolated from the product. Per-rule `source: original | current` (default `current`) selects whether matching reads `original_product` (§5.4, read-only pre-pipeline snapshot) or the live product as modified so far in the pipeline. **MVP scope:** flat rule list, no rule groups or bulk operations (per plugin spec).
3. **Category** — maps a source field (default `product_type`) → `google_product_category` (ID preferred over path, see `gmc_def.md`) via an ordered rule list (PluginData, client scope): `{id, source_field, operator ∈ {eq, ne, contains, regex, in}, source_value, taxonomy_id, is_excluded}`, walked top-to-bottom, first-match-wins; `eq`/`ne` case-insensitive (`strip().casefold()`), the rest case-sensitive; `is_excluded=true` sets `google_product_category=""`. Manual per-product assignments (`product_id → taxonomy_id`) are stored as PluginData as well and evaluate before rules. The plugin attaches a `_category_provenance` sidecar (`manual` | `auto` | `excluded` | absent → uncategorized) that feeds the 4-bucket dashboard, is stripped before content hashing (derived metadata, not content), and never reaches the XML export. Rule changes trigger reprocessing via the `config_hash` (§4). The plugin ships the Google Product Taxonomy as a data file with an in-memory index for autocomplete/validation, refreshable via its UI; its stats/matches endpoints are contributed via `register_routes` (cross-tenant guarded: 404 on a feed source not owned by the client). **Scope decision:** client-scope only for MVP, same rationale as Labelizer — the Google Product Taxonomy itself does not vary by market, so client-wide sharing is intentional, not a placeholder. **MVP scope:** rules + manual assignments + taxonomy autocomplete + 4-bucket stats; AI/generate features per plugin spec (UI placeholders disabled).
4. **Filter** — exclusion criteria; returns `None` on match → the product leaves the pipeline (logged with reason). **MVP scope:** conjunctive (AND) conditions on scalar fields only; nested boolean logic per plugin spec.

### 5.10 Frontend integration & contract tests

- `GET /plugins` returns the enabled plugins' manifests; the frontend builds menu entries and routes dynamically. Config/data UIs default to forms auto-rendered from the JSON Schemas (Mantine-themed renderer); complex plugins may ship a React component (`frontend.component`).
- Plugin frontend components are discovered at **build time**: the Vite build scans `plugins/*/frontend/` and registers the components — no runtime module federation, a single build pipeline.
- The core ships a contract test suite executed against every plugin: manifest validity, schema validity, `process()` honors the dict|None contract, `original_product` is not mutated, invalid configs are rejected, and no plugin-contributed route under `register_routes()` uses the reserved sub-paths `config` or `data`. Plugin authors (including LLMs) should only need to write plugin-specific fixtures.

## 6. Field Mapping

Two components, **no mapping templates** — mappings are stored per feed source (`FeedSource.field_mapping`, JSONB) and are not shared across feed sources.

- **Auto Mapper** — runs automatically on first ingestion of a feed source and on demand (`POST /feed-sources/{id}/field-mapping/auto`). Matches source field names against the Attribute Registry (§5.6): exact/normalized name matches (case-insensitive, separator-insensitive) are applied automatically; known synonyms (e.g. `ean`/`upc`/`barcode` → `gtin`) are applied and marked as suggestions; everything else stays unmapped.
- **Manual Mapper** — mapping table in the UI: every auto assignment is reviewable and adjustable. Targets are addressed via the path grammar (§5.7), including sub-fields of structured attributes. Unmapped baseline-required GMC attributes (§7) are highlighted.

Mapping changes alter the normalized product and are therefore covered by the `content_hash` (§4) — reprocessing happens automatically on the next run.

## 7. Quality Check Rule Set (based on `gmc_def.md`)

Runs **after** the Module Runner, **sequentially before** the XML Writer. "Non-blocking" means findings never prevent an export; the ExportRun therefore always carries consistent per-severity counts. Where possible, rules are evaluated declaratively over the Attribute Registry (§5.6) instead of being hand-coded per attribute. Result per product: a list of `QualityFinding`.

**Rule categories, complete from MVP:**

- **Baseline required fields:** `id`, (`title` or `structured_title`), (`description` or `structured_description`), `link`, `image_link`, `availability`, `price`, `condition` — missing any of these → severity `critical`.
- **Brand requirement:** `brand` required except for exempt categories (movies/books/music) — otherwise `warning`.
- **GTIN/MPN logic:** if `gtin` is missing, `mpn` **and** `brand` must be set, otherwise `warning`. If `gtin` is set: GS1 checksum validation (modulo-10 weighting per the GS1 spec, no special cases) — invalid checksum → `critical`.
- **Enum validation** (registry-driven): `availability`, `condition`, `gender`, `age_group`, `identifier_exists`, `is_bundle`, `adult`, etc., validated against the exact enum values defined in `gmc_def.md` (case-sensitive) → `critical` on mismatch.
- **Conditional required fields:** e.g. `availability_date` required when `availability=preorder`; `unit_pricing_base_measure` only valid together with `unit_pricing_measure` → `warning`.
- **Date formats:** all date fields (`availability_date`, `expiration_date`, `sale_price_effective_date`, `loyalty_program.member_price_effective_date`) validated strictly against ISO 8601 including timezone offset → `critical` on format error.
- **Variant consistency:** for a set `item_group_id`, all variants within a group must share consistent base attributes (e.g. `brand`, `google_product_category`) and differ in at least one variant attribute (`color`/`size`/`gender`/`age_group`) → `warning` on violation.
- **Length limits** (registry-driven): `title` ≤150, `description` ≤5000, `mpn`/`brand` ≤70, `custom_label_*` ≤100 characters, etc., per `gmc_def.md` → `warning`.
- **Cardinality** (registry-driven): repeated attributes validated against min/max counts, e.g. `product_highlight`: if present, 2–100 values, each 1–150 characters → `warning`.
- **Currency consistency:** the currency component of `price` and (if present) `sale_price` must match `FeedSource.currency` → `critical` on mismatch. Catches broken/misconfigured source feeds in multi-market setups that price normalization (§2) does not otherwise guard against. Nested price fields (e.g. `shipping.price`) are not checked in MVP.
- **Image requirements:** `image_link` set, allowed format; minimum size 500×500 px. Severity is date-dependent: `warning` before `2027-01-31` (GMC currently issues warnings only, since 2026-04-14), automatically escalating to `critical` from `2027-01-31` onward (GMC enforcement/rejection date) — implemented as a runtime comparison against a named constant `IMAGE_SIZE_ENFORCEMENT_DATE` in the rule module (not a DB/config field, since it is a one-off, well-known date). The comparison must use an injectable time source (not a direct `datetime.now()`/`date.today()` call) so both the pre- and post-enforcement behavior are unit-testable without waiting for the date. The 1500×1500 px recommendation stays `info` regardless of date. Image dimensions are fetched asynchronously with caching keyed by image URL — dimensions are re-fetched only when the URL changes; products whose images could not be fetched receive `info`, not `warning`.
- **Volume-drop safeguard:** product count dropped by more than `volume_drop_threshold_pct` (default 20 %, configurable per feed source) compared to the previous export → `warning`. Typical cause: broken or empty source feed; also relevant to GMC's item-deletion protection.

Severity levels: `critical` (feed rejection likely), `warning` (policy/data-quality risk), `info` (optimization hint). The dashboard shows findings grouped by feed source, severity, and rule.

## 8. API Structure (rough shape, FastAPI)

- `POST /auth/login`, `POST /auth/logout` — session-based login for the single user; all subsequent endpoints require a valid session.
- `POST/GET /clients` — client management.
- `POST/GET /clients/{id}/feed-sources` — feed sources per client.
- `POST /feed-sources/{id}/run` — manual trigger of the full pipeline (ingest → plugins → QC → export).
- `GET /feed-sources/{id}/ingestion-runs` — history of runs including error details.
- `GET/PUT /feed-sources/{id}/pipeline` — read/write pipeline configuration (UI builder).
- `GET/PUT /feed-sources/{id}/field-mapping` — read/write the per-feed-source mapping; `POST /feed-sources/{id}/field-mapping/auto` — run the auto mapper on demand.
- `GET /plugins` — manifests of enabled plugins; `PUT /plugins/{id}/enabled` — activation toggle.
- `GET/PUT /plugins/{id}/config`, `GET/PUT /plugins/{id}/data` — scope-aware (`?client_id=` / `?feed_source_id=`, omitted = `global`); validated against the manifest schemas; full-replace PUTs return 422 with `{"errors":[...]}` on validation failure. **Reserved:** these two sub-paths (`config`, `data`) under `/plugins/{id}/…` must not be reused by plugin-contributed routes (§5.4, §5.10).
- Plugin-contributed routes live under `/plugins/{id}/…` (e.g. the Category plugin's rules/stats/matches endpoints, cross-tenant guarded) — excluding the reserved `config`/`data` sub-paths above.
- `GET /feed-sources/{id}/quality-findings` — current findings for the dashboard.
- `GET /feed-sources/{id}/export-history` — version list.
- `GET /feed-sources/{id}/export-history/{v}/diff?against={v2}` — field-based diff: per product and changed GMC attribute, old vs. new (not a line-based XML diff).
- `POST /feed-sources/{id}/export-history/{v}/rollback` — append-only: creates a new version from the old state and republishes atomically.
- `POST /feed-sources/{id}/export-token/rotate` — rotates the public token; the old URL becomes invalid immediately.
- `GET /export/{export_token}.xml` — public endpoint for Google's fetch (unauthenticated, but only reachable with a valid, non-guessable token; no internal feed-source ID exposed in the URL). The served file is published atomically (temp file + `os.replace()`).

## 9. Frontend Areas (React 19 / Mantine)

1. **Login** — session-based.
2. **Client overview** — list, create/edit.
3. **Feed sources per client** — source format, target country/language/currency, cron schedule (presets + free text), export URL with copy button and token rotation.
4. **Plugins** — overview of discovered plugins with activation toggle; enabled plugins inject their menu items dynamically.
5. **Pipeline builder** — drag & drop of enabled `pipeline_module` plugins (dnd-kit), instance configuration forms (schema-rendered from the manifest). Builder workspace state is local React state (dirty tracking, reset).
6. **Field mapping** — auto-mapper run button, suggestions marked as such, manual mapping table (TanStack Table) including sub-field paths (§5.7); unmapped baseline-required attributes highlighted. No template save/load.
7. **Plugin menu items** — contributed by plugins, e.g.: Labelizer (dimension editor with global/client scope switch + ID lists per dimension), Category (4-bucket progress dashboard auto/manual/excluded/uncategorized, drag-and-drop rule editor with taxonomy autocomplete, per-rule match counts, matched-products modal, dirty-state guard with snapshot + Reset + Save; v1 scope: Manual Categorization tab working, AI/Uncategorized tabs and Generate/Copy/Bulk-delete as disabled-with-tooltip placeholders), Rules (rule list with operation, target path, value/pattern). Depth per the separate per-plugin specs.
8. **Quality dashboard** — findings per feed source, filterable by severity and rule (TanStack Query polling for live status).
9. **Export history** — version list, field-based diff view, rollback action.
10. **Ingestion status** — status icon per feed source plus error log/history.

## 10. Final Decisions (formerly open questions)

- **Frontend stack:** React 19 + TypeScript (Vite), Mantine, TanStack Query (server state), TanStack Table, dnd-kit; client state via React built-ins, no store library. Plugin frontends: build-time discovery via Vite scan of `plugins/*/frontend/`.
- **Scheduling:** APScheduler in the FastAPI process; cron expressions in UTC; UI presets plus free text; no catch-up after downtime.
- **Concurrency:** per-feed-source lock; overlapping runs are skipped and logged.
- **GTIN validation:** standard GS1 checksum (modulo-10 weighting), no special cases.
- **Export diff:** field-based — per product and changed GMC attribute, old vs. new.
- **Rollback:** append-only — creates a new version from the old state; retention N=30 applies to all versions.
- **Removed products:** omitted from the XML output; the 30-day GMC expiry delay is a known, accepted limitation; reactivation via delta detection; staging purge 90 days after removal.
- **QC execution:** sequential between Module Runner and XML Writer; findings never block the export; ExportRun always carries consistent counts.
- **Flat notation:** explicit `attr(sub:…)` headers only; implicit-order columns are rejected.
- **Field mapping:** auto mapper + manual mapper per feed source; no mapping templates.
- **Core plugins:** rudimentary MVP scope; full feature sets are defined in separate per-plugin specs.
- **Persistence:** JSONB columns for `ModuleInstance.config`, `PluginConfig`, `PluginData`, `QualityFinding`, `FeedSource.field_mapping`, and plugin manifests.
- **Retention:** ExportVersion last N (default 30, configurable); IngestionRun 90 days; StagingHistory 90 days; QualityFinding details for the latest run only (per-severity counts persist in ExportRun).
- **Plugin scope resolution:** three-tier merge (`feed_source > client > global`, per key) defined generically for any plugin declaring more than one scope (§5.3); the generic merge replaces non-dict values per key — finer-grained merging of ordered lists is plugin-defined (e.g. Labelizer dimensions). Labelizer and Category deliberately stay `[global, client]` only for MVP — no per-feed-source (per-market) granularity.
- **Reserved plugin routes:** `config` and `data` sub-paths under `/plugins/{id}/…` are reserved for core endpoints; enforced by the contract test suite (§5.10).
- **Image size QC escalation:** severity auto-escalates from `warning` to `critical` at the GMC enforcement date (2027-01-31) via a code-level date comparison against a named constant, with an injectable time source for testability; image dimensions are fetched asynchronously with URL-keyed caching, unfetchable images yield `info` (§7).
- **Currency check:** QC rule validates `price`/`sale_price` currency against `FeedSource.currency` → `critical` on mismatch; nested price fields (e.g. `shipping.price`) are not checked in MVP (§7).
- **Naming:** "multifeed TSV" renamed to "wide-format TSV" throughout — the format is one TSV per feed source with repeated/annotated columns, not multiple external feeds merged (feed structure stays strictly 1:1, §2).
