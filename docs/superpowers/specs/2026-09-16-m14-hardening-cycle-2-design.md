# M14 — Hardening Cycle 2 (Dev-env, Docs, Minors, UsagePage) — Design

Date: 2026-09-16
Status: Approved in brainstorming (operator). Not yet implemented.
Baseline: `main` at `5678c6d` (M13 lint & gate hardening merged and pushed)

## Purpose

Cycle 1 of the hardening milestone made the three gates strict. Cycle 2 closes the remaining known debt that cycle 1 explicitly deferred, in one phased pass:

1. **Dev-env config drift** — the dev host is machine-specific and the two dev entry points cannot agree; there is no `frontend/.env.example` at all.
2. **Documentation drift** — a 2026-09-08 consistency review left 14 unaddressed doc findings (D1, D4–D16), concentrated at the project's pivot points: the RJSF→custom-renderer switch, the Rolldown adoption, and a `data-model.md` page that has drifted column-by-column.
3. **Deferred review minors** — a long, partly stale list carried in the SDD ledger, never triaged.
4. **The one spec'd but unbuilt frontend item** — the UsagePage KPI row; its backend endpoints are live and unused by the UI.

## Verified premise (measured, not assumed)

- `frontend/vite.config.ts:35` hardcodes `allowedHosts: ['localhost', 'x.hermes-tower.com']`. The file already calls `loadEnv(mode, rootDir, '')` for `VITE_HTTPS_CERT`/`VITE_HTTPS_KEY`, so an env-driven value needs no new mechanism.
- `Caddyfile.dev` is a tracked file whose site label is `http://localhost`; `make dev-caddy` runs it (`Makefile:145-147`). `frontend/docs/architecture.md:220-227` documents `.env.local` with the two HTTPS vars and instructs "Open https://localhost:5173" (direct to Vite). Nothing ties the Caddy host to the Vite host.
- **There is no `frontend/.env.example`.** `.gitignore` excludes `.env` and `.env.local`. The only documentation of the frontend env vars is the snippet inside `frontend/docs/architecture.md`.
- `AGENT_MSG_BOARD.md:34` records the ops decision as still open: vite `allowedHosts` contains a machine-specific host and "Caddyfile.dev's site label (`http://localhost`) may not match it".
- `docs/reports/2026-09-08-06-docs-consistency.md` contains 16 findings: **D2/D3 are operator flags** (spec-internal / spec-vs-shipped conflicts), D1 and D4–D16 are doc fixes. The report is 8 days old and **has not been re-verified since**; its own verdict names the rot concentration (D1, D9/D10, D4–D6 + D12–D14).
- `frontend/src/features/admin/ai/UsagePage.tsx` calls only `useAiUsage` (the grouped list). `frontend/src/api/hooks.ts` has `useAiProviders`, `useAiSettings`, `useAiCacheStatus`, `useAiCacheStats`, `useAiUsage` — **no** summary or timeseries hook.
- The endpoints are live: `GET /admin/ai/usage/summary` (`backend/app/routes/ai_admin.py:479`) and `GET /admin/ai/usage/timeseries` (`:500`). `summarize_usage` (`backend/app/ai/usage.py:103`) returns exactly the KPI set: `calls`, `cache_hits`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `saved_prompt_tokens`, `saved_completion_tokens`, `cost_saved_usd`.
- `.superpowers/sdd/progress.md` carries the deferred minors. Several were fixed by later fix-waves (e.g. `useTriggerRun` dashboard invalidation, `fillVolumeTrend`, the `/#clients` hash guard, the FeedSourceCard Space key, the unused `EmptyState` import), so the list is **partly stale**.

## Operator decisions

| Question | Decision |
|---|---|
| How to carve cycle 2 | One spec + plan covering all four phases, ordered docs/config → minors → feature |
| Spec contradictions D2/D3 | **Not resolved now.** Operator will investigate separately; add a `TODO.md` item. The sweep must not touch those areas |
| Deferred minors | Triage-first: audit each against current code, close the stale ones, fix the small real ones, file anything substantial as its own TODO item |
| UsagePage scope | KPI row **and** the daily timeseries chart |
| Doc-sweep ground truth | Re-derive every claim from code at implementation time. Neither the 2026-09-08 report nor the SDD ledger is authoritative — both are historical artifacts |

## Non-goals

- Do not amend `gmc-feed-engine-spec.md`. D2/D3 are recorded for the operator and excluded from the sweep; nothing in the labelizer-scope or auth/RBAC wording is to be edited this cycle.
- Do not change application behaviour beyond the small deferred-minor fixes. No new endpoints, no migrations, no pipeline changes.
- Do not "fix" a doc by matching another doc. Every corrected claim is re-derived from code, and where code and spec conflict, the spec wins and the conflict is flagged rather than silently resolved.
- Do not rewrite historical records: prior cycle-log entries in `TODO.md`, older dated `docs/decisions.md` entries, `backend/docs/mypy-baseline.md`, and anything under `docs/superpowers/**` or `.superpowers/**` stay as written.
- Do not add a frontend bundler/lint/formatting toolchain. Frontend verification stays `vitest` + `typecheck` + `build`.

## Phase 1 — Dev-env config

**Goal:** one env-driven dev host, no machine-specific value in the repo, and the frontend env documented by example.

- **New `frontend/.env.example`** documenting `VITE_HTTPS_CERT`, `VITE_HTTPS_KEY`, `VITE_ALLOWED_HOSTS`, with a comment that `.env.local` is the real file.
- **`frontend/vite.config.ts`** — `allowedHosts` becomes env-driven from the already-loaded `env`: comma-separated `VITE_ALLOWED_HOSTS`, falling back to `['localhost']`. The hardcoded `x.hermes-tower.com` disappears from the repo; a developer reaches the dev server by hostname by setting the variable locally.
- **`Caddyfile.dev`** — site label becomes `{$DEV_HOST:localhost}` so Caddy reads the same host from the environment instead of hardcoding one. `make dev-caddy` continues to work with no variable set.
- **Docs** — `frontend/docs/architecture.md` and `docs/makefile.md` describe the two dev paths consistently: direct Vite (HTTPS on `:5173`) and `make dev-caddy` (HTTP on `{$DEV_HOST}` proxying to Vite), naming which env var drives the host in each.

**Acceptance:** `git grep` finds no machine-specific hostname; `npm run build` and `npm run typecheck` pass; with no env vars set, the default remains `localhost` for both Vite and Caddy; `frontend/.env.example` exists and matches the variables `vite.config.ts` actually reads.

## Phase 2 — Documentation consistency sweep

**Goal:** every D-finding except D2/D3 resolved, with each claim re-verified against current code.

| ID | Sev | Doc to fix | Re-verify against |
|---|---|---|---|
| D1 | Important | `docs/decisions/0002-schema-renderer-rjsf.md` (mark Superseded), `frontend/docs/plugin-uis.md`, `backend/docs/plugins.md`, root `AGENTS.md` doc-map line | `frontend/package.json` (no `@rjsf/*`, no `ajv`), `frontend/src/components/JsonSchemaForm.tsx` |
| D4 | Medium | `backend/docs/data-model.md` Session table | `backend/app/models/session.py` |
| D5 | Medium | `backend/docs/data-model.md` ExportVersion table | `backend/app/models/export.py` |
| D6 | Medium | `backend/docs/data-model.md` StagingHistory column name | `backend/app/models/staging.py`, `app/staging/purge.py` |
| D7 | Medium | `backend/docs/api.md` — drop `GET /clients/{id}` | `backend/app/routes/clients.py` |
| D8 | Medium | `backend/docs/api.md` — replace `POST /registry/generate` with the CLI command | `backend/app/routes/registry.py`, `scripts/registry_check.py` |
| D9 | Medium | `frontend/docs/architecture.md` stack line (Vite 8 / Rolldown) | `frontend/package.json`, `frontend/vite.config.ts` |
| D10 | Medium | `docs/decisions/0003-rolldown-optional-evaluation.md` (mark Superseded/Completed) | shipped `rolldownOptions` in `vite.config.ts` |
| D11 | Medium | `backend/docs/api.md` — add `GET /feed-sources/{id}/fields` | `backend/app/routes/products.py` |
| D12 | Minor | `backend/docs/data-model.md` IngestionRun status enum (`pending`) | `app/routes/clients.py`, `app/pipeline/reconcile.py` |
| D13 | Minor | `backend/docs/data-model.md` ExportRun columns | `backend/app/models/export.py` |
| D14 | Minor | `backend/docs/data-model.md` column-level drift (User, Client, PluginConfig) | `backend/app/models/*` |
| D15 | Minor | `README.md` Vite proxy list | `frontend/vite.config.ts` (9 prefixes) |
| D16 | Minor | `docs/makefile.md` Caddy section | `Makefile` |

**Method:** for each finding, read the code first and derive the truth, then edit the doc. If a finding is already fixed or obsolete, record that fact against the finding instead of inventing an edit. Findings whose "fix" would require changing code (e.g. D7's alternative of implementing the endpoint) stay doc fixes — the endpoint is not added.

**Deliverables:** the corrected docs, plus a status line per finding in `docs/reports/2026-09-08-06-docs-consistency.md` recording the disposition (fixed / already correct / obsolete) so the report stops being an open list.

## Phase 3 — Deferred minors triage

**Goal:** the SDD-ledger minor list stops being an unbounded backlog.

**Method:** enumerate every distinct minor recorded as deferred in `.superpowers/sdd/progress.md` (the entries are prose; each gets one row). For each: read the code, then classify **fixed** (a later fix-wave already addressed it), **obsolete** (the code it referenced no longer exists), or **open**. Fix the open ones that are small and self-contained (a test assertion, an i18n key, a stale selector, a missing `t()`). Anything that turns out to be real work gets its own numbered `TODO.md` item — it is filed, not smuggled into this cycle.

**Deliverables:** a triage table appended to the ledger (or a short report under `docs/reports/`), the small fixes, and the new `TODO.md` items. The minor count that remains open must be explicit.

## Phase 4 — UsagePage KPI row + timeseries chart

**Goal:** surface the already-live usage summary and trend data in the admin UI.

- `frontend/src/api/hooks.ts` — `useAiUsageSummary(params)` and `useAiUsageTimeseries(params)` following the existing `useAiUsage` shape (same filter params, same `apiGet` pattern).
- `UsagePage.tsx` — a KPI row above the existing table: **total calls**, **cache-hit rate**, **total cost**, **cost saved**; and a daily **timeseries chart** below/above the table. Both honour the existing `from`/`to` date filters, so changing the range updates KPIs and chart together.
- Conventions that are binding here: TanStack Query only (no duplicated server state), all strings through `t()` with identical `en`+`de` trees, and `LoadingState`/`EmptyState`/`ErrorState` on every data view. Chart primitives follow whatever the dashboard/feed-dashboard already use (do not introduce a new chart library).
- Backend: **no changes.** Both endpoints exist; if the timeseries payload shape proves insufficient for a daily chart, that is a follow-up finding, not a backend edit in this cycle.

**Acceptance:** the KPI values and the chart match the endpoints' output for a known fixture range; changing the date range refetches both; the page renders in both locales.

## Acceptance criteria

1. No machine-specific hostname anywhere in the repo; `VITE_ALLOWED_HOSTS` drives Vite and `{$DEV_HOST:localhost}` drives Caddy; `frontend/.env.example` exists and documents every variable `vite.config.ts` reads.
2. D1 and D4–D16 are each either fixed against re-verified code or explicitly recorded as already-correct/obsolete; no doc contradicts the spec.
3. **D2 and D3 are untouched** in every doc, and a `TODO.md` item records them as operator-owned spec amendments.
4. Every ledger-deferred minor has a disposition; open ones are either fixed or filed as TODO items with an explicit count.
5. UsagePage shows the KPI row and timeseries chart, driven by the two new hooks, honouring the date filters, with no backend change.
6. Frontend gates pass: `npm test -- --run`, `npm run typecheck`, `npm run build`. Backend gates remain green (ruff exit-0 over `backend` + `plugins`, mypy exit-0, `alembic check` clean, full `pytest`).

## Risks and open items

- **Both inputs are historical artifacts.** The D-report is 8 days old and the ledger months of accumulated prose; treating either as ground truth would propagate stale claims. Re-verification against code is an explicit step, and the D-report gains a disposition per finding so it stops functioning as an open list.
- **The triage is open-ended by nature.** A "small" minor can hide real work. The rule is: if it needs a design decision or touches behaviour beyond a test/string/selector, it is filed as a TODO item rather than done here.
- **The docs sweep brushes D2/D3-adjacent files.** `backend/docs/data-model.md`, `api.md`, and the AGENTS.md doc map are all edited in this cycle and all also document labelizer scope or RBAC somewhere. The exclusion is enforced by a final targeted check of those areas rather than by trusting the editor.
- **The timeseries chart is the only new UI surface.** It is the least-specified part of the cycle; if the endpoint's day-grouped rows turn out to be sparse or timezone-awkward (a known note: `func.date` uses the session timezone), surface it rather than papering over it with client-side fudging.
- **Scope creep via "while I'm in here".** Doc edits invite adjacent polishing. Each finding is fixed and stopped; adjacent observations are recorded, not fixed.

## Out of scope (noted, not scheduled)

- **D2/D3 spec amendments** — operator-owned (see acceptance 3).
- **Supplemental feeds** — the last major unimplemented capability the spec anticipates (`FeedSource.feed_type` exists; nothing branches on it). A future milestone, not a hardening item.
- **Unclassified pytest warnings** (~79 per run today) — recorded in the 2026-09-08 ops notes, still without a task; not this cycle.
