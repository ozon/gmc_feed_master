# M10 — Frontend Areas & Supporting Endpoints (Design)

> Date: 2026-08-28
> Implements: spec §2 (architecture), §5.10 (plugin frontend), §6 (field mapping),
> §8 (API), §9 (frontend areas); governed by `m10-frontend-instructions.md`
> (approved decisions D1–D5) and `i18n-agent-instructions.md` (binding in full).
> Status: design approved by the human 2026-08-28 (incl. second-pass review
> changes §0.5–0.8); implementation follows in four staged plans (M10-a … M10-d).

## 0. Context & resolved questions

State of the repo at design time: backend milestones M0–M9 complete (internal
numbering; the four core plugins of spec §5.9 are **deferred** per owner
instruction, recorded in `docs/decisions.md` 2026-08-27). The frontend is still
the M0 skeleton (session login only). The `plugins/` directory does not exist yet.

Questions resolved with the human during brainstorming:

1. **Plugin absence during M10.** The existing contract-suite fixture
   `example_upper` is copied to `plugins/example_upper/` as a demo plugin so the
   plugin UI infrastructure (nav items, routes, pipeline builder, schema forms)
   is verifiable end-to-end. This is not building a core plugin.
2. **Core-plugin-specific UIs deferred.** m10 §3.8 last bullet (Labelizer
   dimension editor, Category dashboard, Rules list) is deferred until the core
   plugins exist. M10 delivers the generic plugin infrastructure only.
3. **D3 contradiction flagged, D3 kept.** D3's rationale says post-pipeline
   state is "not persisted per spec §4", but the spec-owner decision
   "Persisted processed-output store" (2026-08-26, Option A) does persist it
   (`staging_products.processed_data`). The human chose to keep D3 as written:
   the Processed view stays a disabled placeholder with tooltip; the
   contradiction is recorded in `docs/decisions.md`.
4. **Build strategy.** One design doc, four staged implementation plans
   (M10-a backend, M10-b frontend foundation, M10-c areas I, M10-d areas II +
   plugin infra), each TDD with review checkpoints; `main` stays green.

Owner review changes (2026-08-28, second pass):

5. **`POST /auth/password` already exists — no backend work.** The review asked
   to add it to M10-a scope on the assumption it was missing. Verified: the
   endpoint exists (`backend/app/main.py:248`) and already implements the M1
   gate semantics — `change_password` increments `revocation_generation`
   (`backend/app/persistence/users.py:65`), session validation rejects stale
   generations (`backend/app/persistence/sessions.py:52`), and the M1
   acceptance test verifies pre-existing sessions return 401 after a change
   (`backend/tests/test_m1_acceptance.py:93–108`). M10 consumes it from the
   user-menu modal only (§2.4/§4.1).
6. **Mapping target grammar corrected.** Positional paths (`shipping.1.price`)
   are NOT valid mapping targets — M4 scope accepts `attr` / `attr.subfield`
   only; anything else is a guaranteed 422
   (`backend/app/routes/field_mapping.py:42–56`). This contradicts the
   `m10-frontend-instructions.md` §3.3 example (`shipping.1.price`); the
   owner's clarification wins, the contradiction is flagged and recorded
   (§7). §4.3 below is corrected accordingly.
7. **Rollback versions badged "not QC'd"** in the export history (§4.7) —
   finding counts of 0 on rollback-created versions would misread as "clean".
8. **Dry-run latency documented** (§1.3): full passes on large feeds are
   practically limited by the synchronous request; the UI prefills `limit=100`.

Document naming note: `m10-frontend-instructions.md` references
`i18n-agent-instructions-2.md` and `coding-agent-instructions-2.md`; the files on
disk are `i18n-agent-instructions.md` and `coding-agent-instructions.md`. The
on-disk files are treated as the binding ones (content matches the references).

## 1. Backend endpoints

All new endpoints require the session (`require_user`), follow existing route
conventions (`backend/app/routes/`), and return 503 when the DB is unavailable
(existing pattern).

### 1.1 D1 — `GET /dashboard/summary`

```jsonc
{
  "counts": {
    "clients": 3,
    "feed_sources": 7,
    "active_products": 12480,      // staging_products: status='active' AND NOT excluded
    "failed_last_exports": 1       // feed sources whose latest ExportRun.status = 'failed'
  },
  "clients": [
    {
      "id": 1, "name": "Acme", "status": "active",
      "feed_sources": [
        {
          "id": 5, "client_id": 1, "name": "Acme DE", "source_format": "wide_tsv",
          "item_count": 4200,            // same active-not-excluded count
          "last_export_at": "…",         // latest ExportRun.started_at or null
          "last_export_status": "completed", // 'completed' | 'failed' | 'rollback' | null
          "last_run_at": "…",            // latest IngestionRun.started_at or null
          "last_run_status": "success"   // 'success' | 'error' | 'skipped' | 'running' | null
        }
      ]
    }
  ]
}
```

- `active_products` counts the export-bound set (`status='active' AND NOT
  excluded`), consistent with how the XML writer assembles exports.
- `last_run_status` is included because the dashboard doubles as the
  ingestion-status surface (spec §9 area 10).
- Implemented with aggregate queries (no per-feed loops issuing N+1).

### 1.2 D2 — `GET /feed-sources/{id}/products`

Params:

| Param | Behavior |
|---|---|
| `stage` | `raw` (default, implemented). `processed` → `501` (D3 placeholder; UI never calls it). Other values → 422. |
| `page` | 1-based, default 1 |
| `page_size` | default 50, max 200 |
| `q` | case-insensitive contains match on `product_id` and `raw_data->>'title'` |
| `status` | `active` / `removed` / `all` (default `all`; removed rows included and filterable per D2) |
| `sort` | field with optional `-` prefix for descending; fields: `product_id` (default asc), `title` (via `raw_data->>'title'`), `status`, `last_seen_at` |

Response: `{ "items": […], "total": N, "page": N, "page_size": N }`.
Each item: `product_id`, `status`, `last_seen_at`, plus the baseline columns
extracted from `raw_data`: `id`, `title`, `description`, `link`, `image_link`,
`availability`, `price`, `condition` (spec §7 baseline set — also the default
visible table columns).

**Detail endpoint (new, supports the row-click drawer):**
`GET /feed-sources/{id}/products/{product_id}` → full row including complete
`raw_data` (canonical product JSON, spec §5.5), `status`, hashes, timestamps.
404 when absent. Keeps list payloads small for large feeds.

### 1.3 D4 — `POST /feed-sources/{id}/dry-run`

Optional JSON body `{"limit": N}` — caps source rows processed (sample mode).
Synchronous read-only full pass: fetch → parse → map → pipeline → QC.
No staging writes, no XML publish.

Implementation: reuse existing steps in-memory —
`IngestStep → MappingStep → PluginStep → qc.run_engine(…)`:

- `IngestStep`/`MappingStep` operate on `RunState.products` in memory.
- `PluginStep` persistence (`apply_plugin_outcomes`) is a no-op because
  `RunState.product_pks` is empty in dry-run mode.
- QC runs via `run_engine` directly on the processed in-memory products,
  skipping `persist_findings`. `previous_export_run` is loaded read-only for
  the VolumeDrop rule. The image-probe rule participates and may write to the
  `image_dimensions` cache table — a performance cache, not staging state.
- Config bundle resolved read-only via `resolve_config_bundle`.

Response:

```jsonc
{
  "total": 500,            // source rows parsed (after limit applied)
  "processed": 480,        // survived the pipeline
  "parse_errors": 2,       // malformed rows logged & skipped (extension beyond D4 minimum)
  "dropped": [ {"product_id": "…", "plugin_id": "filter", "reason": "filter dropped the product"} ],
  "findings": {
    "critical": [ {"rule": "baseline_required", "count": 3, "sample": [ {"product_id": "…", "field": "…", "message": "…"} ]} ],
    "warning": […], "info": […]
  },
  "sample": [ … ]          // up to 50 processed products (constant DRY_RUN_SAMPLE_CAP = 50)
}
```

- Drop `reason`: the runtime contract has no structured drop reason today —
  plugins return `None`. Reason string is `"<plugin_id> dropped the product"`.
  A structured reason is a future contract extension, out of scope.
- Source fetch/parse failure → `422 {"errors": […]}` (spec §8 error convention).
- **Latency:** the endpoint is synchronous by design. A full pass (no `limit`)
  on a large source (up to 500 MB, spec §5.8) can exceed practical HTTP
  request latencies — fetch + parse + per-product pipeline + QC (incl. image
  probes on cache miss) all run inline. This is accepted for MVP; the UI
  mitigates by prefilling `limit=100` (sample mode), which the operator may
  clear knowingly. If full-pass dry runs prove too slow in practice, making
  `limit` mandatory or moving dry-run to a background run is a future
  decision, not part of M10.

### 1.4 D5 — cascade deletes

**New:** `DELETE /clients/{id}` — cascades the client, all of its feed sources
and all per-feed data.
**Reworked:** `DELETE /feed-sources/{id}` — currently returns 409 when
ingestion runs exist; becomes the same per-feed cascade.

Deleted per feed source: quality findings, export versions, export runs,
staging history (via cascade), staging products, module instances, the feed's
pipeline(s) (after unsetting `feed_sources.active_pipeline_id`), ingestion
runs, plugin config/data rows at `feed_source` scope, published XML file and
versions directory on disk, scheduler registration, lock-registry entry.
Client delete additionally removes client-scoped plugin config/data rows and
the client row itself.

- **FK-safe explicit order** in a cascade service (`backend/app/persistence/`
  or new `backend/app/cascade.py`); no migration — the circular
  `export_runs ↔ export_versions` FKs require: delete export versions first
  (`export_runs.export_version_id` is `ON DELETE SET NULL`), then export runs.
- **Guard:** 409 when a run is currently active for any affected feed source
  (lock registry check) — deletion during an active run is rejected.
- Irreversible; the UI requires type-to-confirm and names the cascaded data.

### 1.5 Pipeline API (spec §8 — not yet implemented)

- `GET /feed-sources/{id}/pipeline` →
  `{"instances": [{"position": 1, "plugin_id": "example_upper", "name": "…", "configuration": {…}}]}`
  — empty list when the feed source has no active pipeline. `plugin_id` is the
  manifest id string (matches `GET /plugins` `id`).
- `PUT /feed-sources/{id}/pipeline` — full replace of the ordered instance
  list. Validation (422 `{"errors": […]}` on failure): every referenced plugin
  exists, is enabled, has `extension_point = pipeline_module`, and the instance
  configuration passes the plugin's `validate_config` (via the plugin loader).
- Write path: one `ModulePipeline` row per feed source (created on first save,
  `name` = feed source name, `version` = `"1"`); `ModuleInstance` rows replaced
  transactionally (delete + reinsert with positions); `active_pipeline_id` set;
  `definition` JSONB mirrors the saved instance list. `ModuleInstance` rows are
  the source of truth (`config_resolver` reads them). Pipeline changes alter
  the `config_hash` inputs and therefore trigger reprocessing on the next run
  automatically (spec §4) — no extra work.

### 1.6 Client update (dashboard edit modal)

`PUT /clients/{id}` — updates `name`, `status`, `contact_details`.
404 when absent; 409 on duplicate name (unique constraint).

### 1.7 Supporting schema extensions

- `FeedSourceUpdate`/`FeedSourceOut` gain `volume_drop_threshold_pct`
  (int, 0–100) and `configuration` (JSONB; the Setup form edits the
  `basic_auth` sub-object `{username, password}` inside it — M3 decision,
  plaintext MVP storage). The Setup form cannot save these today without it.
- `GET /plugins` list items gain `used_by_feed_sources: N` (count of module
  instances referencing the plugin across all pipelines) so the
  disable-a-plugin-in-use warning in the Pipeline Editor is accurate.

## 2. Frontend foundation

### 2.1 Dependencies (pinned exactly; each recorded in `docs/decisions.md`)

- `@mantine/core@9.5.2`, `@mantine/hooks@9.5.2`, `@mantine/notifications@9.5.2`,
  `@mantine/dates@9.5.2` (DatesProvider required by i18n instructions),
  `@tabler/icons-react` (manifest icon rendering)
- `@tanstack/react-query`, `@tanstack/react-table`, `@tanstack/react-form`
- `@dnd-kit/core`, `@dnd-kit/sortable`
- `react-router` (v7)
- `i18next`, `react-i18next`, `i18next-browser-languagedetector`,
  `i18next-http-backend`, `dayjs`
- Kept: React 19.2.7, Vite 8.2.2, TypeScript 7.0.2, vitest 4.1.11

Exact versions of the new dependencies are resolved against current
context7/llms.txt documentation at install time (m10 §1: Mantine via
`https://mantine.dev/llms.txt`; context7 rule remains in force).

### 2.2 Source layout

```
frontend/src/
├── main.tsx               # imports i18n init first, then renders <App/>
├── i18n/                  # init module + i18next.d.ts (typed keys from en resources)
├── api/                   # typed fetch client (extends existing api.ts),
│                          # queryKeys.ts factory, per-area query/mutation hooks
├── app/                   # router.tsx (route tree + RequireSession), AppShell layout, theme
├── components/            # ConfirmModal, StateViews (loading/empty/error),
│                          # JsonSchemaForm, CopyField, ExportUrlBlock, …
├── features/
│   ├── auth/  dashboard/  setup/  products/
│   ├── pipeline/  monitoring/  export/  plugins/
public/locales/{en,de}/    # common, auth, dashboard, setup, mapping, products,
                           # pipeline, monitoring, export, plugins, notifications
```

Vite dev proxy extended from `/auth` + `/health` to all API prefixes
(`/clients`, `/feed-sources`, `/dashboard`, `/plugins`, `/registry`, `/export`).

### 2.3 Routing (m10 §2 table, React Router v7)

`/login`, `/` (Dashboard),
`/clients/:clientId/feeds/:feedSourceId/setup|products|pipeline|monitoring|export`,
`/clients/:clientId/plugins/:pluginId` (client-scope plugins),
`/plugins/:pluginId` (global plugins). Client/feed context comes from URL
params only — no context store (spec §2). Setup/Monitoring tabs via search
param (`?tab=settings|mapping`, `?tab=runs|findings|dry-run`).

**Auth guard:** `RequireSession` wrapper queries `GET /auth/me` once; on 401
redirects to `/login` carrying the requested path in router state; after
successful login the original route is restored. Any mutation/query 401 also
routes to `/login` (centralized in the fetch client).

### 2.4 App shell (m10 §2)

Mantine `AppShell`. Header: text wordmark placeholder → breadcrumb context
selector `Client > Feed` (Client segment links to `/`; Feed segment is a
`Menu` listing the current client's feed sources; switching keeps the current
area) → spacer → language switcher, dark/light toggle, user menu (change
password via `POST /auth/password`, logout). Navbar: Dashboard, Setup,
Products, Pipeline Editor, Monitoring, Export (feed-scoped items disabled
until a feed source is selected), then a labeled plugin section rendered
purely from `GET /plugins` (enabled + `manifest.frontend.menu_item`).

### 2.5 Query keys, polling, notifications

- **Query-key factory** `api/queryKeys.ts`: `['dashboard','summary']`,
  `['clients']`, `['feed-source', id, 'products', params]`,
  `['feed-source', id, 'pipeline']`, `['feed-source', id, 'runs']`,
  `['feed-source', id, 'findings']`, `['feed-source', id, 'export-history']`,
  `['feed-source', id, 'field-mapping']`, `['plugins']`, … Every mutation
  invalidates the affected keys; server state is never copied into client
  state (spec §2).
- **Polling (fixed values, m10 §4):** while any run of the current feed source
  is `running` → `refetchInterval: 5000` on runs, findings, dashboard summary;
  idle dashboard summary → 30 s; `refetchIntervalInBackground: false`
  everywhere.
- **Notifications (@mantine/notifications):** provider mounted once at root;
  defaults top-right, limit 5, errors sticky/longer autoClose; all text via
  `t()` (`notifications` namespace). Helpers:
  - mutation success/error notifications; 422 arrays from full-replace PUTs
    rendered in the form *and* summarized in a notification;
  - long-running triggers (manual run, dry run, auto mapper): loading
    notification updated via `notifications.update` on completion/failure;
  - `useRunTransitionNotifier`: compares previous vs current status per run id
    (seen-set ref); fires exactly one "Run finished"/"Run failed" notification
    on running → success/error, never re-notifies on refetch.

### 2.6 Theme & i18n

- Mantine default theme, `primaryColor: 'blue'` (recorded in
  `docs/decisions.md`); dark/light toggle persisted (Mantine color-scheme
  storage); text placeholder logo.
- i18n exactly per `i18n-agent-instructions.md`: single init module imported
  first in `main.tsx`; `fallbackLng: 'en'`, allowlist `['en','de']`, detector
  order querystring → localStorage → navigator, cache in localStorage;
  `common` preloaded, all other namespaces lazy via `i18next-http-backend`
  from `public/locales/<lng>/<ns>.json`; Suspense boundary with Mantine
  `Loader`; language-change effect syncs `dayjs.locale`, `DatesProvider`
  settings (`firstDayOfWeek: 1` for de), and `document.documentElement.lang`;
  typed keys via declaration merging from `en` resources; `Intl` for
  numbers/dates/currencies; dayjs for relative timestamps with active locale.

## 3. Plugin infrastructure (frontend)

- **Demo plugin:** copy `backend/tests/fixtures/example_upper/` →
  `plugins/example_upper/`; add
  `"frontend": {"menu_item": "Example Upper", "icon": "letter-e"}` to its
  manifest (no `component` → exercises the auto-rendered path). The contract
  suite must still pass unchanged.
- **Dynamic nav & routes:** built purely from `GET /plugins` manifests (spec
  §5.10); no hardcoded plugin entries. Icon string → tabler icon map with a
  fallback icon for unknown names. Route placement: plugins declaring `client`
  in `config_scope`/`data_scope` → `/clients/:clientId/plugins/:pluginId`;
  purely global → `/plugins/:pluginId`.
- **Auto-rendered plugin page:** `JsonSchemaForm` (Mantine-themed JSON Schema
  renderer: string→TextInput, number→NumberInput, boolean→Switch, enum→Select,
  object→nested Stack, array→add/remove list) over
  `GET/PUT /plugins/{id}/config|data` with scope params from route context
  (`?client_id=` / `?feed_source_id=`); PUT 422 `errors` rendered in-form +
  notification.
- **Build-time discovery:** a small Vite plugin scans `plugins/*/frontend/`
  (repo root) via `import.meta.glob` and generates a registry
  `pluginId → lazy(component)`. Empty today; when a plugin ships a component,
  its page renders it instead of the auto form. Mechanism + empty-registry
  case tested. No runtime module federation (spec §2/§5.10).
- **Pipeline Editor registry panel** (fulfills spec §9 area 4): all discovered
  plugins with the global activation toggle (`PUT /plugins/{id}/enabled`),
  explicit text that the toggle affects every client and feed source;
  disabling a plugin with `used_by_feed_sources > 0` requires a warning
  confirm naming the usage count.
- **Core-plugin-specific UIs** (m10 §3.8 last bullet: Labelizer/Category/Rules
  screens) are **deferred** until the core plugins are built (owner decision,
  §0.2).

## 4. Areas (m10 §3 — implementation notes beyond the instruction text)

1. **Login** — existing logic ported to Mantine; redirect-to-origin (§2.3);
   password change modal from the user menu.
2. **Dashboard** — four stat cards from D1; collapsible client sections with
   status badge and Add feed / edit / delete actions; feed cards with format
   badge, item count, status dot + relative last-export line (dayjs), settings
   icon → Setup, delete icon; Add client button top-right; create/edit share
   one modal; delete modals type-to-confirm naming cascaded data (D5).
   Dashboard is the ingestion-status surface (spec §9 area 10) via
   `last_run_status`.
3. **Setup** — `?tab=settings|mapping`. Feed settings: TanStack Form over
   `PUT /feed-sources/{id}` incl. `volume_drop_threshold_pct` and Basic Auth
   credentials (§1.7), cron presets (hourly/daily/weekly) + free text with
   "interpreted in UTC" hint, Export URL block (shared component, §4.7).
   Mapping: auto-mapper button with loading notification; TanStack Table of
   source fields → target Select built from `GET /registry/attributes`.
   **Target grammar is `attr` / `attr.subfield` only** (e.g.
   `installment.months`) — the M4 scope rejects positional paths such as
   `shipping.1.price` with a guaranteed 422
   (`backend/app/routes/field_mapping.py:42–56`), so the target dropdown must
   not offer them (owner clarification §0.6; supersedes the
   `m10-frontend-instructions.md` §3.3 example). Repeated/structured
   attributes are offered as their bare attribute name or named sub-fields.
   Synonym matches badged as suggestions; unmapped baseline-required
   attributes highlighted; persist via `PUT .../field-mapping`; 422 errors
   per-field.
4. **Products** — TanStack Table against D2 with server-side pagination,
   search, status filter; column show/hide persisted in `localStorage` key
   `products.columns.<feedSourceId>`; default columns = the 8 baseline
   attributes; Raw/Processed `SegmentedControl`, Processed disabled with
   tooltip (D3); removed rows badged; row click → Drawer with read-only JSON
   from the detail endpoint (§1.2).
5. **Pipeline Editor** — registry panel (§3) + dnd-kit sortable pipeline of
   the current feed source; palette of enabled `pipeline_module` plugins;
   per-instance config via `JsonSchemaForm` from manifest `config_schema`;
   workspace state local React state with dirty tracking (deep compare vs
   server state), Reset, Save (`PUT .../pipeline`), navigation warning on
   unsaved changes.
6. **Monitoring** — `?tab=runs|findings|dry-run`. Runs: history table with
   status icons, processed/failed counts, expandable error details
   (message + stack trace). Findings: latest-run findings, severity + rule
   filters, aggregated by rule with per-product drill-down. Dry run: trigger +
   sample-size input (prefill 100), read-only labeling, results panel per §1.3.
7. **Export** — Export URL block (copy + rotate confirm warning the old URL
   dies immediately); version list with per-severity finding counts; versions
   created by rollback (`ExportVersionOut.source == "rollback"`) render a
   distinct "not QC'd" badge — their finding counts are 0 because QC never
   ran on them, which must not misread as "clean". Diff view: two version
   selects (default latest vs previous), field-based table grouped by
   product, one row per changed attribute, old → new — never line-based;
   rollback confirm modal stating append-only semantics.
8. **Plugin UIs** — §3 of this doc.

## 5. Testing

**Backend** (pytest against real PostgreSQL per AGENTS.md):
- D1 summary counts and per-feed fields (incl. failed-last-export semantics
  across `completed`/`failed`/`rollback`).
- D2 pagination/search/filter/sort, `stage=processed` → 501, detail endpoint.
- D4 full pass on a fixture feed: totals, drops with plugin_id, findings
  grouping, sample cap, `limit`, source-failure → 422, and a
  no-side-effects assertion (staging/export tables untouched).
- D5 cascade completeness (every child table empty afterwards, circular
  export FK order), 409 active-run guard, filesystem cleanup; client cascade.
- Pipeline GET/PUT: validation failures (unknown/disabled plugin, non-pipeline
  plugin, invalid instance config), replace semantics, `config_hash` input
  change.
- `PUT /clients/{id}`; `GET /plugins` usage count; contract suite green with
  `plugins/example_upper` present.

**Frontend** (vitest + Testing Library, jsdom; fetch stubbed — existing
pattern, no new mocking library):
- DoD minimum: auth route guards; column-config localStorage persistence;
  diff-view rendering; pipeline-builder dirty tracking; schema-form rendering;
  notification on mutation failure.
- i18n acceptance per instructions (switch without reload, lazy namespaces,
  typed keys compile-time, en fallback) — typecheck + targeted tests; network
  behavior verified manually in the browser.

CI unchanged: backend job (migrations + pytest + compileall) and frontend job
(test + typecheck + build) already run on push/PR.

## 6. Sequencing (four staged plans)

| Plan | Scope | Verified by |
|---|---|---|
| M10-a Backend | §1 (D1, D2+detail, D4, D5 + feed-source rework, pipeline API, `PUT /clients/{id}`, §1.7 extensions, `plugins/example_upper`) | backend pytest incl. contract suite |
| M10-b Foundation | §2 (deps/pins, i18n, theme, router + guard, AppShell incl. dynamic plugin nav, query keys, notifications, shared components incl. JsonSchemaForm) | frontend tests + typecheck + build |
| M10-c Areas I | Login, Dashboard, Setup (both tabs), Products (§4.1–4.4) | frontend tests + manual pass |
| M10-d Areas II + plugin infra | Pipeline Editor, Monitoring, Export, plugin routes/auto-UI/build-time discovery (§3, §4.5–4.8); full M10 DoD pass | frontend tests + end-to-end manual verification |

Each plan: TDD (RED-GREEN-REFACTOR), review checkpoint before the next plan,
`main` green after every plan.

## 7. Decisions to record in `docs/decisions.md` upon implementation

- D1–D5 implementation records (per m10 §0).
- Demo plugin `example_upper` shipped in `plugins/` for M10 verification.
- Core-plugin UIs deferred with M10 (pointer to the deferred-plugins decision).
- D3 kept despite the `processed_data` contradiction (contradiction flagged).
- Pipeline API semantics (single pipeline per feed source, instances as source
  of truth, `definition` mirror).
- Dry-run drop reason string; `parse_errors` extension; sample cap 50.
- Cascade delete implementation (explicit FK-safe order, no migration;
  409 active-run guard).
- Mantine primary color `blue`.
- All new frontend dependency pins (one line each).
- `POST /auth/password` verified pre-existing with M1 revocation semantics —
  consumed, not rebuilt (§0.5).
- Mapping target grammar clarification (`attr` / `attr.subfield` only);
  contradiction with the `m10-frontend-instructions.md` §3.3 example flagged
  (§0.6).
- Rollback versions badged "not QC'd" in the export history (§4.7).
- Dry-run full-pass latency accepted for MVP; UI prefills `limit=100` (§1.3).
