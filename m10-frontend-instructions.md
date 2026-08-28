# M10 — Frontend Instructions (final)

> Audience: Coding Agent. Governs milestone **M10 (Frontend areas)** of the GMC Feed Engine.
> Process rules: `coding-agent-instructions.md` (superpowers workflow, authority model, decisions log).
> Binding product spec: `gmc-feed-engine-spec.md` — especially §2 (architecture), §5.10 (plugin frontend), §6 (field mapping), §8 (API), §9 (frontend areas). Do not edit the spec.
> i18n: `i18n-agent-instructions.md` is binding in full for this milestone.
> Status: all decisions below were approved by the human on 2026-08-28. This document is implementation-ready.

## 0. Approved decisions — record in `docs/decisions.md`

These extend spec §8 (API shape) and §9 (frontend areas). They are approved; record each in `docs/decisions.md` (date, topic, decision, rationale) when you implement it.

| ID | Decision |
|---|---|
| D1 | New endpoint `GET /dashboard/summary`: client count, feed-source count, total active products, count of feed sources whose last export failed; plus per feed source: id, client id, name, format, item count, last export timestamp + status. Powers the dashboard without N+1 requests. |
| D2 | New endpoint `GET /feed-sources/{id}/products?stage=raw` over `StagingProduct` (post-mapping / pre-pipeline state, spec §4). Params: `page`, `page_size`, `q` (server search over product `id` and `title`), `sort`, `status` filter. Products with `status=removed` are included and filterable; the UI shows them with a badge. |
| D3 | Products view ships with a Raw/Processed switch; **Processed is a disabled placeholder with tooltip** until specified later (post-pipeline state is not persisted per spec §4; persisting it is a separate future decision). |
| D4 | New endpoint `POST /feed-sources/{id}/dry-run`: read-only full pass (fetch source → parse → map → pipeline → QC), no staging writes, no XML publish. Optional `limit` param caps source rows processed (sample mode; feeds up to 500 MB, spec §5.8). Synchronous response: products total/processed/dropped (drops with `plugin_id` + reason, spec §5.4), findings grouped by severity + rule, capped sample of processed products. |
| D5 | Client management includes create (modal) and delete. `DELETE /clients/{id}` **cascades**: all of the client's feed sources incl. staging products/history, ingestion runs, quality findings, export runs/versions, plugin config/data at client and feed-source scope. `DELETE /feed-sources/{id}` cascades the same per-feed data. Both are irreversible and require type-to-confirm in the UI. |

UI/UX decisions approved alongside (no new endpoints): dashboard as landing page per approved mockup; breadcrumb `Client > Feed` with feed dropdown for fast switching; plugin overview/activation lives inside the Pipeline Editor; plugin menu items render directly in the main nav; i18n per `i18n-agent-instructions-2.md` (en fallback + de); dark/light toggle in header, placeholder logo; notifications incl. polling-event notifications; Mantine `llms.txt` as documentation reference (see §1).

## 1. Documentation references

- Mantine (pinned v9.5.2, `coding-agent-instructions-2.md` §4): use **https://mantine.dev/llms.txt** as the primary documentation index; it lists per-component and per-package `llms/*.md` pages — fetch the relevant page before writing code against a component. The context7 rule from `coding-agent-instructions-2.md` §4 remains in force; llms.txt complements it for Mantine.
- Notifications: **@mantine/notifications**, reference **https://mantine.dev/llms/x-notifications.md** (provider setup, `notifications.show` / `notifications.update`, position, queue limit).
- i18n: implement `i18n-agent-instructions-2.md` exactly — react-i18next, lazy HTTP-loaded namespaces, typed keys, language detection, language switcher. Languages: `en` (fallback) + `de`.

## 2. App shell & navigation

Mantine `AppShell` for all authenticated views.

**Header (left → right):**
1. Logo placeholder (text wordmark; no brand assets exist).
2. Breadcrumb context selector: `Client > Feed`. The Client segment links to the dashboard (`/`). The Feed segment is a dropdown (Mantine `Menu` on the breadcrumb item) listing all feed sources of the current client for fast switching; switching keeps the current area (e.g. stays on Products).
3. Spacer, then: language switcher (per i18n instructions), dark/light color-scheme toggle, user menu (change password, logout).

**Navbar (main nav); feed-source-scoped items are disabled until a feed source is selected:**
- Dashboard (`/`)
- Setup — tabs: *Feed settings*, *Mapping*
- Products
- Pipeline Editor
- Monitoring — tabs: *Runs*, *Quality findings*, *Dry run*
- Export
- **Plugin section**: one nav item per enabled plugin that declares `frontend.menu_item` in its manifest (`GET /plugins`, spec §5.10), with the manifest icon. Rendered as a labeled section below the fixed items, fully dynamic — no hardcoded plugin entries.

**Routing table (React Router):**

| Route | Area |
|---|---|
| `/login` | Login (spec §8 auth) |
| `/` | Dashboard |
| `/clients/:clientId/feeds/:feedSourceId/setup` | Setup (tab via search param or nested route) |
| `/clients/:clientId/feeds/:feedSourceId/products` | Products |
| `/clients/:clientId/feeds/:feedSourceId/pipeline` | Pipeline Editor |
| `/clients/:clientId/feeds/:feedSourceId/monitoring` | Monitoring (tabs: runs, findings, dry-run) |
| `/clients/:clientId/feeds/:feedSourceId/export` | Export |
| `/clients/:clientId/plugins/:pluginId` | Plugin UI (client-scoped plugins) |
| `/plugins/:pluginId` | Plugin UI (global-scoped plugins) |

Selected client/feed-source context comes from URL params only — no duplicated context store (spec §2: TanStack Query for server state, React built-ins for client state).

## 3. Areas

### 3.1 Login
- Session login per spec §8 (`POST /auth/login`, `POST /auth/logout`); redirect to the originally requested route after login; any 401 redirects to `/login`.
- Password change via the user menu (spec §2: password changeable in the UI).

### 3.2 Dashboard (`/`) — layout per approved mockup
- Four stat cards: Clients, Feeds, Products (total active), Failed last exports — via D1 endpoint.
- One collapsible section per client: client name, status badge (e.g. ACTIVE), actions *Add feed*, edit, delete (D5, type-to-confirm; cascade warning must name what gets deleted).
- One card per feed source inside its client: feed name, format badge (XML/TSV/CSV), item count, status dot + relative line ("Last export 5 days ago — succeeded"), settings icon → that feed's Setup, delete icon (D5).
- *Add client* button top-right; create/edit in a modal (D5). *Add feed* creates the feed source and links into its Setup.
- The dashboard doubles as the ingestion-status surface of spec §9 area 10 (status icon per feed source) — no separate status page.

### 3.3 Setup (per feed source)
Two tabs:
1. **Feed settings** (spec §9 area 3): source format (XML/TSV/CSV/wide-format TSV), source URL/upload reference + optional Basic Auth credentials, target country/language/currency, cron schedule (presets hourly/daily/weekly + free-text cron, interpreted in UTC — state this in the UI), `volume_drop_threshold_pct`, `history_retention_count`. Hand-built form (TanStack Form, spec §2).
2. **Mapping** (spec §6 + §9 area 6): "Run auto mapper" button (`POST .../field-mapping/auto`, loading notification); TanStack Table of source fields → registry target paths; auto assignments editable; synonym matches marked as suggestions; targets selectable from the Attribute Registry including sub-field paths (§5.7 grammar, e.g. `shipping.1.price`); unmapped baseline-required GMC attributes (§7) highlighted; no template save/load (§6). Persist via `GET/PUT .../field-mapping`; render 422 validation errors per spec §8 conventions.

### 3.4 Products (per feed source)
- TanStack Table against the D2 endpoint with server-side pagination and server search (`q`). No client-only paging over full feeds.
- Column configuration: show/hide only, persisted in `localStorage` per feed source. Default visible columns: the GMC baseline required attributes (spec §7): `id`, `title`, `description`, `link`, `image_link`, `availability`, `price`, `condition`.
- View switch (`SegmentedControl`): *Raw* (post-mapping / pre-pipeline, spec §4 StagingProduct) / *Processed* — Processed disabled placeholder with tooltip (D3).
- Removed products (`status=removed`, §4): visible with a badge, filterable via the `status` filter (D2).
- Row click opens a drawer with the full canonical product JSON (spec §5.5), read-only.

### 3.5 Pipeline Editor (per feed source)
Full builder in M10 (spec §9 area 5), two cooperating parts on one screen:
1. **Plugin registry panel**: all discovered plugins (`GET /plugins`) with the global activation toggle (`PUT /plugins/{id}/enabled`). The toggle is global (spec §5.3 level 1): the UI states that it affects every client and feed source, and disabling a plugin that is used in any pipeline requires a warning confirm. This panel fulfills spec §9 area 4 — no separate plugins page.
2. **Pipeline builder**: dnd-kit drag & drop of enabled `pipeline_module` plugins into the ordered pipeline of the current feed source; per-instance configuration rendered from the manifest's `config_schema` via the schema-rendered form renderer (spec §2, §5.10). Workspace state is local React state with dirty tracking, Reset, Save → `GET/PUT /feed-sources/{id}/pipeline`; warn on navigation with unsaved changes.

### 3.6 Monitoring (per feed source)
Three tabs:
1. **Runs** (spec §9 area 10): IngestionRun history (`GET .../ingestion-runs`) — timestamp, status icon (success/error/skipped), products processed/failed, expandable error details (message + stack trace). Retention (90 days) is backend-side; the UI renders what it gets.
2. **Quality findings** (spec §9 area 8): `GET .../quality-findings` — findings of the latest run, filterable by severity (critical/warning/info) and rule; aggregate by rule with per-product drill-down.
3. **Dry run** (D4): trigger button + optional sample-size input (`limit`); results panel with products total/processed/dropped, drops with plugin + reason, findings by severity/rule, and the sample of processed products. Clearly labeled read-only ("no staging changes, no export published").

### 3.7 Export (per feed source)
- **Export URL block** (spec §8/§9 area 3): full public URL (`/export/{export_token}.xml`) with copy button; "Rotate token" opens a confirm modal warning that the old URL becomes invalid immediately (`POST .../export-token/rotate`). The same block also appears in Setup → Feed settings; both read the same server state.
- **Version list**: `GET .../export-history` — version, timestamp, product count, findings counts by severity (from ExportRun, §4).
- **Diff view**: default comparison = latest vs. previous version; both versions freely selectable via two selects (`GET .../export-history/{v}/diff?against={v2}`). Field-based rendering only (§10): table grouped by product, one row per changed GMC attribute, old value → new value. Never a line-based XML diff.
- **Rollback** (spec §9 area 9): per-version action with confirm modal stating rollback is append-only (creates a new version, republishes atomically).

### 3.8 Plugin UIs
- Menu items and routes are built dynamically from `GET /plugins` manifests (spec §5.10); no hardcoded plugin entries anywhere.
- Route placement by declared scopes: plugins with `client`-scope config/data render under `/clients/:clientId/plugins/:pluginId`; purely global plugins under `/plugins/:pluginId`.
- Plugins without `frontend.component`: auto-render config/data UIs from the manifest JSON Schemas (Mantine-themed renderer, spec §2/§5.10) against `GET/PUT /plugins/{id}/config|data` with scope params (`?client_id=` / `?feed_source_id=`).
- Plugin React components: build-time discovery via Vite scan of `plugins/*/frontend/` (spec §5.10) — no runtime module federation.
- Core plugin UIs per spec §9 area 7 (Labelizer dimension editor with global/client scope switch + ID lists; Category 4-bucket dashboard + drag-and-drop rule editor with taxonomy autocomplete; Rules list). v1-deferred features render as disabled controls with tooltips, per the per-plugin specs.

## 4. Cross-cutting conventions

**Notifications (@mantine/notifications)** — provider mounted once at app root:
- Every mutation: success or error notification; 422 validation errors from full-replace PUTs render in the form *and* as a summarized notification.
- Long-running triggers (manual run `POST .../run`, dry run, auto mapper): loading notification, updated via `notifications.update` on completion/failure.
- Polling events: when a polled query observes a run status transition (running → success/error), fire exactly one notification ("Run finished" / "Run failed"), deduped by run id — never re-notify on refetch.
- Defaults: position top-right, limit 5, sensible autoClose (errors sticky/longer). All text via `t()`.

**Polling (TanStack Query)** — fixed values (approved):
- While any run is active for the current feed source: `refetchInterval` 5 s on runs, quality findings, and dashboard summary.
- Idle dashboard: 30 s background refresh of the summary query.
- `refetchIntervalInBackground: false` everywhere.
- After every mutation: invalidate the affected query keys — server state is never copied into client state (spec §2). Use a central query-key factory (e.g. `['feed-source', id, 'products']`) for consistent invalidation.

**Theme & appearance**: light/dark toggle in the header (persisted), Mantine default theme with one primary-color choice recorded in `docs/decisions.md`, text placeholder logo. No custom design system in M10.

**i18n**: follow `i18n-agent-instructions-2.md` without deviation. Namespaces: `common`, `auth`, `dashboard`, `setup`, `mapping`, `products`, `pipeline`, `monitoring`, `export`, `plugins`, `notifications`. Plugin-contributed UI text follows the same rules — plugins ship their own locale JSON; the design doc must state how plugin namespaces register with the host i18n instance.

**Confirm modals (Mantine `Modal`)** for every irreversible action: token rotation, rollback, client deletion and feed-source deletion (D5: type-to-confirm, cascade warning), disabling a plugin that is in use.

**View states**: every data view implements loading (skeleton/loader), empty (helpful text + primary action), and error (message + retry) states. Relative timestamps via dayjs with the active i18n locale; numbers/dates/currencies via `Intl` per the i18n instructions.

## 5. Definition of done (M10)

- All areas in §3 usable end-to-end against the real API; plugin menu items and routes render purely from manifests (spec §5.10).
- New endpoints D1, D2, D4, D5 implemented and recorded in `docs/decisions.md`.
- i18n acceptance criteria from `i18n-agent-instructions-2.md` pass (switch without reload, lazy namespaces, typed keys, `en` fallback).
- Notifications behave as specified in §4, including the polling-transition case.
- Frontend tests cover at minimum: auth route guards, column-config persistence (localStorage), diff-view rendering, pipeline-builder dirty tracking, schema-form rendering, notification on mutation failure.
