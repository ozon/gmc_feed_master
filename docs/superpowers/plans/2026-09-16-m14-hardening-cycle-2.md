# M14 — Hardening Cycle 2 (Dev-env, Docs, Minors, UsagePage) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the machine-specific dev host and document the frontend env by example; close 14 documentation findings (D1, D4–D16) against re-verified code; triage the deferred review minors; and build the UsagePage KPI row + timeseries chart on the already-live endpoints.

**Architecture:** Four phases in risk order. Phase 1 is config/docs only. Phase 2 corrects documentation, always deriving the truth from code at edit time (the 2026-09-08 report and the SDD ledger are historical artifacts, not ground truth). Phase 3 audits the ledger's minor list and bounds it. Phase 4 adds two TanStack Query hooks and a KPI row + chart to one page — no backend change.

**Tech Stack:** React 19, TypeScript, Vite 8 (Rolldown), Mantine 9 (`@mantine/charts` + `recharts` are already dependencies), TanStack Query, i18next; Python 3.10+ FastAPI backend (read-only for this plan).

## Global Constraints

- **Do not amend `gmc-feed-engine-spec.md`.** Findings D2 and D3 are operator-owned and excluded. Do not edit any labelizer-scope or auth/RBAC wording in any doc — not even to "make it consistent".
- **Code is ground truth, not the report.** Every corrected claim is re-derived by reading the model/route/`package.json`/`Makefile` at edit time. The 2026-09-08 report is already known to be wrong on at least one point (D5 claims `source` defaults to `"run"`; `backend/app/models/export.py:56` says `default="manual"`, and `backend/app/schemas/export.py:8` has a **3-value** enum `Literal["scheduled", "manual", "rollback"]`, not the 2-value one the report implies). When the report and the code disagree, the code wins and the report's finding gets a status note recording the correction.
- **No doc is fixed by matching another doc.** If two docs disagree, resolve both against code.
- **Doc-only phases change no behaviour.** Phase 1 touches `vite.config.ts` and `Caddyfile.dev` (dev tooling only); phases 2–3 change no application code beyond explicitly-listed small minor fixes.
- **Frontend conventions (binding):** TanStack Query only for server state; every string through `t()`; `en` and `de` locale trees stay identical; `LoadingState`/`EmptyState`/`ErrorState` on every data view; reuse the existing `StatCard`/`ChartCard` + `@mantine/charts` primitives — do **not** add a chart library.
- **Frontend gates:** `cd frontend && npm test -- --run && npm run typecheck && npm run build`.
- **Backend gates (must stay green; nothing here should touch them):** `cd backend && uv run ruff check . ../plugins && uv run mypy .`, `uv run alembic check`, and `env -u DATABASE_URL uv test` → `uv run pytest -q`.
- **Historical records stay as written:** prior `TODO.md` cycle-log entries, older dated `docs/decisions.md` entries, `backend/docs/mypy-baseline.md`, and anything under `docs/superpowers/**` or `.superpowers/**`.

---

### Task 1: Env-driven dev host + `frontend/.env.example`

**Files:**
- Create: `frontend/.env.example`
- Modify: `frontend/vite.config.ts`, `Caddyfile.dev`, `frontend/docs/architecture.md`, `docs/makefile.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `VITE_ALLOWED_HOSTS` (Vite) and `DEV_HOST` (Caddy) as the two env knobs; the pattern later tasks assume when documenting dev setup.

- [ ] **Step 1: Create `frontend/.env.example`**

```
# Copy to .env.local (gitignored). Every value below is read by vite.config.ts.
# Set BOTH cert vars or neither; HTTPS is required for the Secure session cookie.
VITE_HTTPS_CERT=local-certs/localhost-cert.pem
VITE_HTTPS_KEY=local-certs/localhost-key.pem
# Comma-separated Host headers the dev server accepts (Vite rejects unknown Hosts).
# Keep in sync with DEV_HOST when using `make dev-caddy`.
VITE_ALLOWED_HOSTS=localhost
```

- [ ] **Step 2: Make `vite.config.ts` read it**

In `frontend/vite.config.ts`, after the existing `const keyPath = env.VITE_HTTPS_KEY?.trim();` line, add:

```ts
  const allowedHosts = (env.VITE_ALLOWED_HOSTS?.trim() || 'localhost')
    .split(',')
    .map((host) => host.trim())
    .filter(Boolean);
```

then replace the hardcoded list in the `server` block:

```ts
    server: {
      allowedHosts,
```

`loadEnv(mode, rootDir, '')` is already in scope, so `VITE_ALLOWED_HOSTS` needs no new plumbing.

- [ ] **Step 3: Make `Caddyfile.dev` read the same host**

Replace the first line of `Caddyfile.dev`:

```
{$DEV_HOST:localhost} {
```

The default keeps `make dev-caddy` working with no environment set.

- [ ] **Step 4: Verify no machine-specific host remains in shipped config or live docs**

Run:
```bash
cd /home/ozon/gmc_feed_master && rg -n "hermes-tower" frontend/src frontend/vite.config.ts frontend/.env.example Caddyfile Caddyfile.dev Makefile README.md AGENTS.md
```
Expected: no matches.

Historical review artifacts that *recorded* the finding (`docs/reports/2026-09-08-01-open-findings.md`), the message board, and `docs/superpowers/**`/`.superpowers/**` are exempt. When this task lands, update the `allowedHosts` row in `docs/reports/2026-09-08-01-open-findings.md` to mark it resolved (that report is an open-findings tracker, same treatment as the D-report).

- [ ] **Step 5: Verify the frontend still builds**

Run:
```bash
cd frontend && npm run typecheck && npm run build
```
Expected: both clean.

- [ ] **Step 6: Update the dev-setup docs**

- `frontend/docs/architecture.md` (the "# .env.local" block around line 220): keep the cert example, add `VITE_ALLOWED_HOSTS=localhost` and a sentence that the same value must be set as `DEV_HOST` for `make dev-caddy`; state that `.env.example` is the canonical list.
- `docs/makefile.md`: in the Caddy section, note that `make dev-caddy` serves `{$DEV_HOST:-localhost}` and proxies to the Vite dev server.

- [ ] **Step 7: Commit**

```bash
git add frontend/.env.example frontend/vite.config.ts Caddyfile.dev frontend/docs/architecture.md docs/makefile.md
git commit -m "chore(dev-env): env-driven dev host (VITE_ALLOWED_HOSTS / DEV_HOST) + frontend .env.example"
```

---

### Task 2: `backend/docs/data-model.md` column corrections (D4, D5, D6, D12, D13, D14)

**Files:**
- Modify: `backend/docs/data-model.md`
- Modify: `docs/reports/2026-09-08-06-docs-consistency.md` (status lines only)

**Interfaces:**
- Consumes: nothing.
- Produces: the corrected data-model page; the D-report status lines for D4/D5/D6/D12/D13/D14.

**Method:** for each finding, read the model file first, then replace the doc table. The replacement tables below were derived from the models at plan time; re-read the model before pasting and note any difference.

- [ ] **Step 1: D4 — Session table**

Read `backend/app/models/session.py`. Replace the Session table with:

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `user_id` | Integer | FK → `users.id` (RESTRICT) |
| `token_hash` | String(64) | sha256 of the session token — the raw token is never stored; unique (`ix_sessions_token_hash`) |
| `created_at` | DateTime(tz) | |
| `last_interaction_at` | DateTime(tz) | updated on each authenticated request |
| `idle_expires_at` | DateTime(tz) | idle-timeout deadline |
| `absolute_expires_at` | DateTime(tz) | absolute-timeout deadline (idle is capped by it) |
| `revocation_generation` | Integer | compared against the user's generation to revoke all sessions at once |
| `revoked_at` | DateTime(tz) | nullable; set on explicit revocation |

- [ ] **Step 2: D5 — ExportVersion table**

Read `backend/app/models/export.py` (`ExportVersion`) and `backend/app/schemas/export.py`. Replace the ExportVersion table with:

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `feed_source_id` | Integer | FK → `feed_sources.id` (RESTRICT) |
| `export_run_id` | Integer | FK → `export_runs.id` (RESTRICT) |
| `version_number` | Integer | unique per feed source (`uq_export_versions_source_version`) |
| `file_hash` | String(64) | sha256 of the published file |
| `product_count` | Integer | |
| `source` | String(20) | default `manual`; enum `scheduled` \| `manual` \| `rollback` (`app/schemas/export.py`) |
| `source_version_id` | Integer | nullable; self-FK (SET NULL) — rollback lineage |
| `created_at` | DateTime(tz) | |

There is **no `xml_path` column**; the published path is derived from the feed-source export token.

- [ ] **Step 3: D6 — StagingHistory column name**

Read `backend/app/models/staging.py`. Rename the documented `created_at` column to `recorded_at`, and note it is what `app/staging/purge.py` compares against the history cutoff.

- [ ] **Step 4: D12 — IngestionRun status enum**

Read the status values actually assigned in `backend/app/routes/clients.py`, `backend/app/pipeline/runner.py`, `backend/app/pipeline/reconcile.py`. Document the full set (at least `pending` — the manual-trigger 202 state that reconciliation rewrites to `error` with an "interrupted by restart" reason). Do not guess: use the values found.

- [ ] **Step 5: D13 — ExportRun columns**

Read `backend/app/models/export.py` (`ExportRun`). Extend the table with `status`, `options` (JSONB), `started_at`, `completed_at`, the finding-count columns, and note that `export_version_id` (SET NULL) and `ingestion_run_id` are **nullable** because the 90-day purge detaches them.

- [ ] **Step 6: D14 — User, Client, PluginConfig column drift**

Read `backend/app/models/user.py`, `client.py`, `plugin.py`.
- User `password_hash` is `String(512)`, not 255; ensure `role`, `is_active`, `revocation_generation`, `updated_at` are listed.
- Client gains `settings` (JSONB), `status`, `updated_at`.
- PluginConfig has **no `created_at`**; PluginData does. Delete or qualify the claim that the two are structurally identical.

- [ ] **Step 7: Record dispositions in the D-report**

In `docs/reports/2026-09-08-06-docs-consistency.md`, replace each `Status:` line for D4, D5, D6, D12, D13, D14 with `Status: FIXED (2026-09-16, M14)`. For D5, add: `Report correction: source defaults to "manual" and the enum is 3-valued (scheduled/manual/rollback), not 2-valued.`

- [ ] **Step 8: Verify**

Run:
```bash
cd /home/ozon/gmc_feed_master && rg -n "xml_path|last_accessed_at" backend/docs/data-model.md
```
Expected: no matches. Then confirm each edited table's column list matches the model by re-reading the model file and eyeballing the table.

- [ ] **Step 9: Commit**

```bash
git add backend/docs/data-model.md docs/reports/2026-09-08-06-docs-consistency.md
git commit -m "docs(data-model): align Session/ExportVersion/ExportRun/StagingHistory/User/Client/PluginConfig with models (D4-D6, D12-D14)"
```

---

### Task 3: `backend/docs/api.md` endpoint corrections (D7, D8, D11)

**Files:**
- Modify: `backend/docs/api.md`
- Modify: `docs/reports/2026-09-08-06-docs-consistency.md` (status lines only)

**Interfaces:**
- Consumes: nothing.
- Produces: an api.md whose endpoint set matches the routes.

- [ ] **Step 1: D7 — remove the phantom `GET /clients/{id}`**

Confirm against `backend/app/routes/clients.py` that only `POST /clients`, `GET /clients`, `PUT /clients/{id}`, `DELETE /clients/{id}` exist, then delete the `GET /clients/{id}` entry from api.md. Do not implement the endpoint.

- [ ] **Step 2: D8 — replace `POST /registry/generate`**

Confirm `backend/app/routes/registry.py` exposes only `GET /registry/attributes`. Replace the documented `POST /registry/generate` entry with the CLI command actually used to regenerate the artifact:

```bash
cd backend && uv run python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json
```

(Note in the doc that `--check` verifies without writing, which is what CI runs.)

- [ ] **Step 3: D11 — add `GET /feed-sources/{id}/fields`**

Read `backend/app/routes/products.py` for the route's response shape and query parameters, then add it to api.md's Products section (it powers the column picker / `extraFields` preview). Describe the actual response; do not invent fields.

- [ ] **Step 4: Record dispositions**

Set `Status: FIXED (2026-09-16, M14)` for D7, D8, D11.

- [ ] **Step 5: Verify the endpoint sets match**

Run:
```bash
cd /home/ozon/gmc_feed_master && rg -n "clients/\{id\}|registry/generate|feed-sources/\{id\}/fields" backend/docs/api.md
```
Expected: only the `feed-sources/{id}/fields` line matches.

- [ ] **Step 6: Commit**

```bash
git add backend/docs/api.md docs/reports/2026-09-08-06-docs-consistency.md
git commit -m "docs(api): drop phantom endpoints, document /feed-sources/{id}/fields (D7, D8, D11)"
```

---

### Task 4: Renderer and bundler docs (D1, D9, D10)

**Files:**
- Modify: `docs/decisions/0002-schema-renderer-rjsf.md`, `docs/decisions/0003-rolldown-optional-evaluation.md`, `frontend/docs/plugin-uis.md`, `frontend/docs/architecture.md`, `backend/docs/plugins.md`, `AGENTS.md`
- Modify: `docs/reports/2026-09-08-06-docs-consistency.md` (status lines only)

**Interfaces:**
- Consumes: nothing.
- Produces: docs whose stated renderer and bundler match what ships.

- [ ] **Step 1: D1 — the renderer that actually shipped**

Confirm against `frontend/package.json` (no `@rjsf/*`, no `ajv`) and `frontend/src/components/JsonSchemaForm.tsx` (custom Mantine renderer). Then:
- In `docs/decisions/0002-schema-renderer-rjsf.md`, set `Status: Superseded — a custom Mantine JSON Schema renderer shipped instead; see ADR-0006` and add a dated note recording why RJSF was dropped (no dependency, full control over Mantine styling, plugin UIs rendered by the same component). Leave the original decision text intact — decisions are append-only.
- Remove the RJSF/AJV claims from `frontend/docs/plugin-uis.md` (the "AJV (for RJSF): JSON Schema draft 2020-12" line), `backend/docs/plugins.md` (the "JsonSchemaForm (RJSF)" phrase), and the root `AGENTS.md` doc-map line for `plugin-uis.md`.

Note: the root `AGENTS.md` doc map already labels ADR-0002 "(superseded)" — keep that and make sure the wording matches the ADR's new status.

- [ ] **Step 2: D9 — the frontend stack line**

Read `frontend/package.json` (`vite` version) and `frontend/vite.config.ts` (`rolldownOptions.output.codeSplitting.groups`). Update `frontend/docs/architecture.md`'s stack line from "Vite 6 (esbuild dev, Rollup prod)" to Vite 8 with Rolldown for production, and add one line pointing at the chunk-group strategy (`manualChunks` no longer exists).

- [ ] **Step 3: D10 — Rolldown is shipped, not "being evaluated"**

In `docs/decisions/0003-rolldown-optional-evaluation.md`, set `Status: Completed — Rolldown shipped via the Vite 8 upgrade` and add a dated note that the evaluation criteria were met and the config uses `rolldownOptions`. Keep the original text.

- [ ] **Step 4: Record dispositions**

Set `Status: FIXED (2026-09-16, M14)` for D1, D9, D10.

- [ ] **Step 5: Verify no RJSF claim survives outside history**

Run:
```bash
cd /home/ozon/gmc_feed_master && rg -n "RJSF|@rjsf|AJV" AGENTS.md backend/docs frontend/docs docs/decisions docs/decisions.md
```
Expected: matches only inside ADR-0002 itself (where the rejected/decision text is history) and the dated `docs/decisions.md` entries. Nothing in `backend/docs/`, `frontend/docs/`, or `AGENTS.md`.

- [ ] **Step 6: Commit**

```bash
git add docs/decisions/0002-schema-renderer-rjsf.md docs/decisions/0003-rolldown-optional-evaluation.md frontend/docs/plugin-uis.md frontend/docs/architecture.md backend/docs/plugins.md AGENTS.md docs/reports/2026-09-08-06-docs-consistency.md
git commit -m "docs(adr): mark custom renderer + Rolldown as shipped (D1, D9, D10)"
```

---

### Task 5: Minor doc drift (D15, D16)

**Files:**
- Modify: `README.md`, `docs/makefile.md`
- Modify: `docs/reports/2026-09-08-06-docs-consistency.md` (status lines only)

**Interfaces:**
- Consumes: Task 1 (which also edits `docs/makefile.md` — land Task 1 first).
- Produces: the last two doc findings closed.

- [ ] **Step 1: D15 — README proxy list**

Read `frontend/vite.config.ts` for the current proxy prefixes (9 today: `/admin`, `/auth`, `/health`, `/clients`, `/feed-sources`, `/dashboard`, `/plugins`, `/registry`, `/export`). Update `README.md`'s proxy sentence to the full list.

- [ ] **Step 2: D16 — the missing Makefile targets**

Confirm `Makefile` has `prod` and `dev-caddy`. If Task 1's Caddy wording already added them to `docs/makefile.md`, verify it covers both; otherwise add a Caddy section documenting `make prod` (`Caddyfile`, requires `DOMAIN`/`BACKEND_URL`) and `make dev-caddy` (`Caddyfile.dev`, HTTP, `DEV_HOST`).

- [ ] **Step 3: Record dispositions**

Set `Status: FIXED (2026-09-16, M14)` for D15, D16.

- [ ] **Step 4: Verify the report has no open doc findings left**

Run:
```bash
cd /home/ozon/gmc_feed_master && rg -n "^\- Status:" docs/reports/2026-09-08-06-docs-consistency.md
```
Expected: every line either `FIXED (2026-09-16, M14)` or an operator-flag line for D2/D3 that says the operator owns it. No `NEW`.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/makefile.md docs/reports/2026-09-08-06-docs-consistency.md
git commit -m "docs: full Vite proxy list and Caddy make targets (D15, D16)"
```

---

### Task 6: Deferred-minors triage

**Files:**
- Modify: `.superpowers/sdd/progress.md` (append a triage table; gitignored but the ledger is where the list lives)
- Create: `docs/reports/2026-09-16-deferred-minors-triage.md`
- Modify: `TODO.md` (new items for anything substantial)

**Interfaces:**
- Consumes: nothing.
- Produces: a bounded minor list — every entry classified, with an explicit count of what remains open.

**Method:** the ledger is the source. Enumerate every distinct item recorded as deferred by grepping it, then classify each by reading the code.

- [ ] **Step 1: Enumerate**

Run:
```bash
cd /home/ozon/gmc_feed_master && rg -o "Minors deferred:[^.]*\." .superpowers/sdd/progress.md | sort -u
```
This yields the raw list. Known candidates to verify (they may already be fixed or obsolete):
- `ChannelMetadata` placeholder strings cosmetic
- auto-select effect dep churn (guarded); Select hidden while loading
- blocker-reset (stay) path untested; save enabled during validate-pending; language param unencoded in `TaxonomyCombobox`
- trend non-ascending edge; `row_errors` truncated at 100 by the writer; `export_runs` 30-row cap vs 30-day window; partial-statistics funnel; excluded-only staging untested
- donut data/names untested; `component=a` has no href
- module-level `beforeAll` placement
- no hook-level `renderHook` test for `useFeedDashboard`; `fillChartDates` assumes ascending input
- breaker thresholds as per-config columns (documented gap)
- builtin cache staleness (`template_version` stays `"builtin"`)
- declared-but-unused non-canonical variables only warn
- AB-BA activation deadlock surfaces as 500 rather than 409
- `activate=false` create branch untested
- api.md preview-404 wording

- [ ] **Step 2: Classify each against current code**

For each item, read the referenced code and assign exactly one of:
- **fixed** — a later fix-wave already addressed it (cite the commit or the code that proves it);
- **obsolete** — the code it referenced no longer exists;
- **open (small)** — fixable within this task: a test assertion, an i18n key, a stale selector, a missing `t()`, a one-line guard;
- **open (work)** — needs a design decision or behaviour change → file as a numbered `TODO.md` item.

- [ ] **Step 3: Fix the small ones**

Apply only the `open (small)` fixes. Keep each to its stated scope; do not widen a fix because the surrounding code looks improvable.

- [ ] **Step 4: Write the triage report**

Create `docs/reports/2026-09-16-deferred-minors-triage.md` with a table: `Item | Source cycle | Classification | Evidence | Action`. State the counts (fixed / obsolete / open-small-fixed / open-work-filed) at the top.

- [ ] **Step 5: Append to the ledger**

Append the same table (or a pointer to the report) under a new dated heading in `.superpowers/sdd/progress.md` so the ledger stops carrying an unbounded list.

- [ ] **Step 6: Verify**

Run:
```bash
cd frontend && npm test -- --run && npm run typecheck
```
Expected: green (or, if no frontend fix was applied, still green). Then re-read the report and confirm every ledger item appears exactly once.

- [ ] **Step 7: Commit**

```bash
git add backend frontend TODO.md docs/reports/2026-09-16-deferred-minors-triage.md
git commit -m "chore(minors): triage deferred review minors (close stale, fix small, file the rest)"
```

---

### Task 7: Usage summary + timeseries hooks

**Files:**
- Modify: `frontend/src/api/queryKeys.ts`, `frontend/src/api/hooks.ts`, `frontend/src/api/types.ts`
- Test: `frontend/src/features/admin/ai/UsagePage.test.tsx` (existing file — add hook coverage there or in a sibling test)

**Interfaces:**
- Consumes: the existing `usageDateParams` helper (`frontend/src/features/admin/ai/usageDates.ts`) and `AiUsageSummary` (`frontend/src/api/types.ts`).
- Produces: `useAiUsageSummary(params)` → `AiUsageSummary`; `useAiUsageTimeseries(params)` → `{ rows: AiUsageTimeseriesRow[] }`; `queryKeys.ai.usageSummary(params)` and `queryKeys.ai.usageTimeseries(params)`.

Backend shapes (already live, read-only):
- `GET /admin/ai/usage/summary` → `AiUsageSummary`: `calls`, `cache_hits`, `hit_ratio`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `saved_prompt_tokens`, `saved_completion_tokens`, `cost_saved_usd`. Accepts `from`/`to` (aliased date-times), `client_id`, `feed_source_id`, `task_type`.
- `GET /admin/ai/usage/timeseries` → `{ "rows": [...] }` where each row is `{ group_key (date), calls, cache_hits, prompt_tokens, completion_tokens, cost_usd }`, ascending by day. Accepts only `from`/`to`.

- [ ] **Step 1: Make the summary query key parameter-aware and add the timeseries key**

In `frontend/src/api/queryKeys.ts`, replace:

```ts
    usageSummary: ['ai', 'usage-summary'] as const,
```

with:

```ts
    usageSummary: (params: unknown) => ['ai', 'usage-summary', params] as const,
    usageTimeseries: (params: unknown) => ['ai', 'usage-timeseries', params] as const,
```

The params **must** be in the key: the KPIs and chart are filter-dependent, and a constant key would serve stale numbers after a date change.

- [ ] **Step 2: Add the filter-params and timeseries row types**

In `frontend/src/api/types.ts`: `AiUsageParams` currently **requires** `group_by`, which the summary/timeseries endpoints do not take. Split it — existing callers keep working:

```ts
export type AiUsageFilterParams = {
  client_id?: number;
  feed_source_id?: number;
  task_type?: string;
  from?: string;
  to?: string;
};

export type AiUsageParams = AiUsageFilterParams & { group_by: AiUsageGroupBy };
```

Then, next to `AiUsageRow`:

```ts
export type AiUsageTimeseriesRow = {
  group_key: string;
  calls: number;
  cache_hits: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: string | number;
};
```

- [ ] **Step 3: Add the two hooks**

In `frontend/src/api/hooks.ts`, immediately after `useAiUsage`, mirroring its existing search-string construction. Note the parameter type is `AiUsageFilterParams`, **not** `AiUsageParams`:

```ts
export function useAiUsageSummary(params: AiUsageFilterParams) {
  const search = new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => [k, String(v)]),
  ).toString();
  return useQuery({
    queryKey: queryKeys.ai.usageSummary(params),
    queryFn: () => apiGet<AiUsageSummary>(`/admin/ai/usage/summary?${search}`),
  });
}

export function useAiUsageTimeseries(params: AiUsageFilterParams) {
  const search = new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => [k, String(v)]),
  ).toString();
  return useQuery({
    queryKey: queryKeys.ai.usageTimeseries(params),
    queryFn: () =>
      apiGet<{ rows: AiUsageTimeseriesRow[] }>(`/admin/ai/usage/timeseries?${search}`),
  });
}
```

Add `AiUsageFilterParams` and `AiUsageTimeseriesRow` to the existing type imports at the top of `hooks.ts`.

- [ ] **Step 4: Verify types and lint**

Run:
```bash
cd frontend && npm run typecheck
```
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/queryKeys.ts frontend/src/api/types.ts frontend/src/api/hooks.ts
git commit -m "feat(admin-ai): usage summary + timeseries query hooks"
```

---

### Task 8: UsagePage KPI row + timeseries chart

**Files:**
- Modify: `frontend/src/features/admin/ai/UsagePage.tsx`
- Modify: `frontend/public/locales/en/admin.json`, `frontend/public/locales/de/admin.json`
- Test: `frontend/src/features/admin/ai/UsagePage.test.tsx`

**Interfaces:**
- Consumes: `useAiUsageSummary`, `useAiUsageTimeseries` (Task 7); `StatCard` (`frontend/src/components/dashboard/StatCard.tsx`) and `ChartCard` (`frontend/src/components/dashboard/ChartCard.tsx`).
- Produces: the rendered KPI row and chart.

`StatCard` signature: `{ label: ReactNode; value: number; variant?: 'neutral' | 'warning' | 'critical'; suffix?: string }` — `value` is a **number**, so coerce (`Number(summary.cost_usd ?? 0)`).
`ChartCard` signature: `{ title: ReactNode; isEmpty: boolean; emptyMessage?: string; children: ReactNode }`.

- [ ] **Step 1: Add the i18n keys (en, then de)**

In the `ai.usage` object of `frontend/public/locales/en/admin.json` add:

```json
    "kpiCalls": "Total calls",
    "kpiCacheHitRate": "Cache hit rate",
    "kpiCost": "Total cost (USD)",
    "kpiCostSaved": "Cost saved (USD)",
    "trendTitle": "Daily usage",
    "trendCalls": "Calls",
    "trendCacheHits": "Cache hits"
```

Add the same keys to `de/admin.json` with German labels (`Anrufe gesamt`, `Cache-Trefferquote`, `Gesamtkosten (USD)`, `Eingesparte Kosten (USD)`, `Nutzung pro Tag`, `Anrufe`, `Cache-Treffer`). Both trees must keep identical key sets.

- [ ] **Step 2: Render the KPI row and chart**

In `UsagePage.tsx`, call the two new hooks with the same filter inputs already in state:

```tsx
  const filters = usageDateParams(fromDate, toDate);
  const usageQuery = useAiUsage({ group_by: groupBy, ...filters });
  const summaryQuery = useAiUsageSummary(filters);
  const timeseriesQuery = useAiUsageTimeseries(filters);
```

Keep the existing `usageQuery` early returns. The summary query has its own state, so guard it explicitly — **never render `summary.calls` while it is undefined**:

```tsx
  const summary = summaryQuery.data;
  const trendRows = timeseriesQuery.data?.rows ?? [];
```

Above the filter `Group`:

```tsx
      {summaryQuery.isPending ? (
        <LoadingState />
      ) : summaryQuery.isError ? (
        <ErrorState onRetry={() => void summaryQuery.refetch()} />
      ) : summary ? (
        <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }}>
          <StatCard label={t('ai.usage.kpiCalls')} value={summary.calls} />
          <StatCard
            label={t('ai.usage.kpiCacheHitRate')}
            value={Math.round(summary.hit_ratio * 100)}
            suffix="%"
          />
          <StatCard label={t('ai.usage.kpiCost')} value={Number(summary.cost_usd ?? 0)} />
          <StatCard
            label={t('ai.usage.kpiCostSaved')}
            value={Number(summary.cost_saved_usd ?? 0)}
          />
        </SimpleGrid>
      ) : null}
```

and below the table:

```tsx
      <ChartCard
        title={t('ai.usage.trendTitle')}
        isEmpty={trendRows.length === 0}
        emptyMessage={t('ai.usage.empty')}
      >
        <AreaChart
          h={220}
          data={trendRows}
          dataKey="group_key"
          series={[
            { name: 'calls', label: t('ai.usage.trendCalls'), color: chartColors.info },
            { name: 'cache_hits', label: t('ai.usage.trendCacheHits'), color: chartColors.success },
          ]}
          curveType="monotone"
        />
      </ChartCard>
```

Imports to add: `SimpleGrid` from `@mantine/core`, `AreaChart` from `@mantine/charts`, `chartColors` from `../../../components/dashboard/dashboardColors`, `StatCard`, `ChartCard`, and the two hooks. Colors come from the shared `chartColors` module (the codebase's single source for chart series colors) — do not inline hex/token strings.

If `@mantine/charts`' `Series` type rejects `label`, drop the `label` fields and keep `name`/`color` (the neighbours in `FleetCharts.tsx` use that shape); `npm run typecheck` is the arbiter, and the i18n keys stay for the chart title.

- [ ] **Step 3: Extend the page test**

In `frontend/src/features/admin/ai/UsagePage.test.tsx`, add assertions that with a mocked summary response the four KPI labels render their values (including the `%` suffix), and that with a mocked timeseries response the chart card is not empty. Follow the file's existing mocking pattern for `apiGet`.

- [ ] **Step 4: Run the frontend gates**

Run:
```bash
cd frontend && npm test -- --run && npm run typecheck && npm run build
```
Expected: all green, build clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/admin/ai/UsagePage.tsx frontend/src/features/admin/ai/UsagePage.test.tsx frontend/public/locales/en/admin.json frontend/public/locales/de/admin.json
git commit -m "feat(admin-ai): usage KPI row and daily trends chart"
```

---

### Task 9: TODO record for the operator-owned spec conflicts

**Files:**
- Modify: `TODO.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the D2/D3 record the operator asked for.

- [ ] **Step 1: Add the item**

Under `## Section 8 — Backlog (longer-term)`, add:

```markdown
### 8.2 [ ] Operator: amend `gmc-feed-engine-spec.md` for two self/shipped conflicts [P1, operator-owned]

**Why:** the 2026-09-08 docs-consistency review found two conflicts that only the operator can resolve, because the binding rule is *fix the doc, never the spec*.

1. **D2 — labelizer feed_source scope.** §10 says Labelizer/Category "stay `[global, client]` only for MVP — no per-feed-source granularity", while §2 and §5.9 mandate client + feed_source per-rule value lists and the code implements the three-tier merge. §10's bullet is stale; §5.9 is the shipped behaviour.
2. **D3 — access model.** §2 still says "Single user (operator only), no client portal, no role model", while two-role RBAC (`admin`/`user`) with client assignment shipped per ADR-0009.

**Acceptance:** §10's scope bullet and §2's access row are amended to match; no downstream doc has to be reverted. Until then, M14 deliberately leaves every labelizer-scope and auth/RBAC doc statement untouched.
```

- [ ] **Step 2: Commit**

```bash
git add TODO.md
git commit -m "docs(todo): record D2/D3 as operator-owned spec amendments"
```

---

### Task 10: Cycle close-out

**Files:**
- Modify: `TODO.md`, `docs/decisions.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: the cycle recorded; gates re-verified.

- [ ] **Step 1: Append the cycle-log entry to `TODO.md`**

Summarize: the dev-host knob (`VITE_ALLOWED_HOSTS`/`DEV_HOST`) and `frontend/.env.example`; the 14 doc findings closed against re-verified code (noting the D5 report correction and the D2/D3 exclusion); the minors triage counts; the UsagePage KPI + chart; and the gates.

- [ ] **Step 2: Append a dated entry to `docs/decisions.md`**

Record the decisions: dev host is env-driven from one knob pair (no machine-specific host in the repo); docs sweeps re-derive from code because historical reports drift (D5 was wrong on two counts); deferred-minor lists must be triaged, not carried.

- [ ] **Step 3: Run every gate**

Run:
```bash
cd backend && uv run ruff check . ../plugins && uv run mypy . && uv run alembic check
cd ../frontend && npm test -- --run && npm run typecheck && npm run build
```
and the backend suite:
```bash
cd ../backend && env -u DATABASE_URL uv run pytest -q
```
Expected: ruff `All checks passed!`; mypy `Success: no issues found`; alembic `No new upgrade operations detected.`; frontend all green; backend suite passes (1295 tests at the time of writing — no backend test changes are expected in this cycle).

- [ ] **Step 4: Verify the exclusion held**

Run:
```bash
cd /home/ozon/gmc_feed_master && git diff --stat "$(git merge-base HEAD main)"..HEAD -- gmc-feed-engine-spec.md
```
Expected: empty output — no M14 commit touched the spec.

- [ ] **Step 5: Commit**

```bash
git add TODO.md docs/decisions.md
git commit -m "docs: M14 hardening cycle 2 close-out"
```

---

## Final verification

- [ ] `frontend/.env.example` exists and lists exactly the variables `vite.config.ts` reads.
- [ ] `rg "hermes-tower"` finds no machine-specific host outside historical artifacts.
- [ ] Every `Status:` line in `docs/reports/2026-09-08-06-docs-consistency.md` is `FIXED (2026-09-16, M14)` or the operator-owned D2/D3 note; no `NEW` remains.
- [ ] `gmc-feed-engine-spec.md` is untouched (`git diff` shows no change).
- [ ] The minors triage report exists with a classification and an explicit open count for every ledger item.
- [ ] UsagePage renders the KPI row (`calls`, hit-rate `%`, cost, cost saved) and the daily chart, both reacting to the date filters, with no backend change.
- [ ] All gates green: ruff exit-0 (backend + plugins), mypy exit-0, `alembic check` clean, backend `pytest` passing, frontend test + typecheck + build clean.

## Self-review notes

- Spec coverage: Phase 1 → Task 1; Phase 2 → Tasks 2–5 (D1, D4–D16 = 14 findings, mapped one-to-one); Phase 3 → Task 6; Phase 4 → Tasks 7–8; the operator record → Task 9; close-out → Task 10. Non-goals (spec untouched, no behaviour change, no new chart library, no history rewriting) are restated as global constraints.
- Two facts were verified beyond the input report and are baked into the tasks: `export_versions.source` defaults to `"manual"` with a 3-value enum (`app/schemas/export.py:8`), and `queryKeys.ai.usageSummary` plus the `AiUsageSummary` type already exist unused — so Task 7 changes the key's shape rather than adding it from scratch.
- Task ordering dependency: Task 5 edits `docs/makefile.md`, which Task 1 also edits — run Task 1 first.
- No new backend endpoint, migration, or pipeline change appears anywhere in this plan; the only backend file touched is documentation.
