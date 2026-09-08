# Documentation Consistency Review — 2026-09-08

Scope: `gmc-feed-engine-spec.md` (authoritative contract), `backend/docs/*` (architecture, data-model, api, plugins, mypy-baseline), `frontend/docs/*` (architecture, plugin-uis), `docs/decisions/0001-0009` + `docs/decisions.md`, root/backend/frontend AGENTS.md, README, `docs/makefile.md`, `docs/system-overview.md`.
Method: doc claims verified against code (code = ground truth); endpoint sets diffed route-by-route; symbol references grepped (e.g., deleted `merge_scopes`). Historical artifacts (`docs/superpowers/**`, TODO.md, message board) excluded per scope. Read-only review.

Binding rule (root AGENTS.md): *documentation that contradicts `gmc-feed-engine-spec.md` is a bug — fix the doc, never the spec, and flag the conflict to the operator.* Two findings below (D2, D3) are **spec-internal or spec-vs-shipped conflicts** — the operator must amend the spec; the docs are correct per code in those cases.

Severity legend: Important (will actively mislead) · Medium · Minor.

## Operator flags (spec changes required — do not "fix" docs to match)

### [D2] Spec contradicts itself: §10 vs §2/§5.3/§5.9 on labelizer feed_source scope
- Severity: **Important**
- Location: `gmc-feed-engine-spec.md:285` vs `:43,130,197`
- Evidence: §10: "Labelizer and Category deliberately stay `[global, client]` only for MVP — no per-feed-source (per-market) granularity." vs §2: "data: client + feed_source per-rule value lists" and §5.9: "PluginData (scopes client + feed_source)… per-market labeling ships with the MVP."
- Impact: a reader honoring §10 would drop feed-scope data support that §5.9 mandates and the code implements.
- Suggestion: **operator action** — correct the stale §10 bullet; the spec is the contract and must be internally consistent.

### [D3] Spec §2 still says "single user, no role model" while two-role RBAC shipped per ADR-0009
- Severity: **Important**
- Location: `gmc-feed-engine-spec.md:37` vs `backend/app/models/user.py`, `backend/app/routes/admin.py`, `docs/decisions/0009-basic-rbac.md`
- Evidence: spec §2: "Access / auth | Single user (operator only), no client portal, no role model." Code: `role` (`admin`/`user`), `user_clients`, `/admin/*` routes; ADR-0009 documents the two-role design; api.md/architecture.md document RBAC.
- Impact: anyone auditing against the spec finds the shipped auth model in violation; the binding rule makes this a spec-vs-docs conflict requiring a spec amendment, not doc reversion.
- Suggestion: **operator action** — record the ADR-0009 change in spec §2.

## Findings (doc fixes)

### [D1] ADR-0002 prescribes RJSF; the shipped renderer is a custom `JsonSchemaForm` with no @rjsf dependency
- Severity: **Important**
- Location: `docs/decisions/0002-schema-renderer-rjsf.md` (Decision + "Rejected Alternative: Custom JSON Schema renderer") vs `frontend/package.json` (no `@rjsf/*`, no `ajv`) and `frontend/src/components/JsonSchemaForm.tsx` (custom Mantine renderer)
- Corroborating drift: `frontend/docs/plugin-uis.md:58` still documents "AJV (for RJSF): Configured for JSON Schema draft 2020-12"; `backend/docs/plugins.md:173` says "JsonSchemaForm (RJSF)"; root AGENTS.md doc-map line for plugin-uis says "RJSF schema rendering".
- Impact: the "rejected alternative" is what shipped. An engineer adding plugin UIs would install RJSF/AJV per the ADR and diverge from the actual validation/rendering path.
- Suggestion: amend ADR-0002 (Status: Superseded — custom renderer shipped); scrub RJSF/AJV mentions from plugin-uis.md, backend/docs/plugins.md, and the AGENTS.md doc-map line.
- Status: CONFIRMED-known-class (tooling agent T8 independently flagged the same contradiction; unified here)

### [D4] data-model.md Session entity does not match the model
- Severity: Medium
- Location: `backend/docs/data-model.md:228-237` vs `backend/app/models/session.py`
- Evidence: doc says `id String(64)` PK (random token) + `last_accessed_at`/`expires_at`; code has Integer PK, `token_hash` (hashed, not raw), `last_interaction_at`, dual `idle_expires_at`/`absolute_expires_at`, `revocation_generation`, `revoked_at`.
- Impact: wrong PK and missing security-relevant columns mislead anyone reasoning about session revocation.
- Suggestion: rewrite the Session table to mirror the model.
- Status: NEW

### [D5] data-model.md ExportVersion lists a nonexistent `xml_path` and omits shipped columns
- Severity: Medium
- Location: `backend/docs/data-model.md:200-210` vs `backend/app/models/export.py:41-44`
- Evidence: doc: `xml_path String(512)`; code: `file_hash`, `product_count`, `source` (default `"run"`), `source_version_id` (rollback lineage, SET NULL) — no `xml_path`.
- Suggestion: replace with the real columns; note the 2-value source enum status (TODO 2.2) if documenting `source`.
- Status: NEW

### [D6] data-model.md StagingHistory says `created_at`; code has `recorded_at`
- Severity: Medium
- Location: `backend/docs/data-model.md:168` vs `backend/app/models/staging.py` and `backend/app/staging/purge.py` (`StagingHistory.recorded_at < history_cutoff`)
- Suggestion: rename the doc column.
- Status: NEW

### [D7] api.md documents `GET /clients/{id}` which does not exist
- Severity: Medium
- Location: `backend/docs/api.md:52` vs `backend/app/routes/clients.py` (only POST /clients, GET /clients, PUT/DELETE /clients/{id})
- Suggestion: remove the line or implement the endpoint.
- Status: NEW

### [D8] api.md documents `POST /registry/generate` which is not an HTTP route
- Severity: Medium
- Location: `backend/docs/api.md:137` vs `backend/app/routes/registry.py` (only `GET /registry/attributes`)
- Evidence: regeneration is a CLI script (`scripts/registry_check.py`), correctly documented in README.
- Suggestion: replace the entry with the CLI command.
- Status: NEW

### [D9] frontend/docs/architecture.md stack line is doubly stale: "Vite 6 (esbuild dev, Rollup prod)"
- Severity: Medium
- Location: `frontend/docs/architecture.md:7` vs `frontend/package.json` (vite 8.2.2) and `frontend/vite.config.ts:22`
- Impact: wrong bundler mental model; `manualChunks` advice from that era would break the build.
- Suggestion: update to Vite 8 (Rolldown, `rolldownOptions.output.codeSplitting.groups`); consider surfacing the chunking strategy (currently only in decisions.md).
- Status: NEW

### [D10] ADR-0003 treats Rolldown as an optional evaluation; it is the shipped bundler
- Severity: Medium
- Location: `docs/decisions/0003-rolldown-optional-evaluation.md` vs vite 8.2.2 + rolldownOptions in the shipped config
- Impact: readers believe Rollup is the prod bundler and Rolldown is merely being evaluated.
- Suggestion: mark ADR-0003 Superseded/Completed (Rolldown adopted via the Vite 8 upgrade; criteria passed).
- Status: NEW

### [D11] Code route `GET /feed-sources/{id}/fields` missing from api.md
- Severity: Medium
- Location: `backend/app/routes/products.py:170`; api.md's Products section omits it
- Impact: undiscoverable endpoint that powers the column picker / preview extraFields.
- Suggestion: add it to api.md (and fold in the later query-key additions like `productLookup`, `adminUsers`, `adminSettings`, `adminScheduler` noted in frontend/docs/architecture.md's key table where applicable).
- Status: NEW

### [D12] data-model.md IngestionRun status enum omits `pending`
- Severity: Minor
- Location: `backend/docs/data-model.md:177` vs `backend/app/routes/clients.py:321` (creates `status="pending"`), `backend/app/pipeline/reconcile.py:26` (reconciles `("running", "pending")`)
- Suggestion: document `pending` (manual-trigger 202 response, reconciled to `error` "interrupted by restart").
- Status: NEW

### [D13] data-model.md ExportRun omits shipped columns
- Severity: Minor
- Location: `backend/docs/data-model.md:188-198` vs `backend/app/models/export.py:16-28`
- Evidence: code also has `status`, `options` JSONB, `started_at`, `completed_at`, nullable `ingestion_run_id`/`export_version_id` (SET NULL) — the purge-detachment nullability is undocumented.
- Suggestion: extend the table; note FK nullability (ties into the 90-day purge behavior).
- Status: NEW

### [D14] data-model.md column-level drift: User, Client, PluginConfig
- Severity: Minor
- Location: `backend/docs/data-model.md:35,63-70,129-139` vs `backend/app/models/*`
- Evidence: User `password_hash` is `String(512)` in code, doc says 255; Client has `settings` JSONB + `updated_at` (undocumented); PluginConfig has **no** `created_at` while the doc claims PluginConfig/PluginData are structurally identical.
- Suggestion: correct lengths and column lists; drop or qualify the "identical structure" claim.
- Status: NEW

### [D15] README understates the Vite proxy scope
- Severity: Minor
- Location: `README.md:64` (duplicate of tooling T9; fixed here for doc ownership)
- Suggestion: update to the full 9-prefix proxy list.
- Status: NEW

### [D16] docs/makefile.md omits the `prod` and `dev-caddy` targets
- Severity: Minor
- Location: `docs/makefile.md:61-69` vs `Makefile:141-147`
- Suggestion: add a Caddy section (makefile.md otherwise matches the Makefile accurately).
- Status: NEW

## Endpoint coverage appendix

**In code but missing from api.md:**
- `GET /feed-sources/{id}/fields` — `backend/app/routes/products.py:170`
- `POST /feed-sources/{id}/products/lookup` (batch product lookup) — present in api.md via ADR-0008? Verified documented; listed here only if your copy predates 2026-09-05 — confirmed present, no action.

**In api.md but not in code:**
- `GET /clients/{id}` (D7)
- `POST /registry/generate` (D8)

## Verified as consistent (no findings)

- **Reserved plugin routes**: spec §5.4/§8, api.md, backend/docs/plugins.md, and `backend/app/plugins/discovery.py` (`_RESERVED_SUBPATHS`) all agree.
- **Pipeline step order**: architecture.md matches `steps.py` and backend/AGENTS.md (Ingest → Mapping → Staging → Plugins → QC → Export).
- **Scheduler + system jobs + shutdown drain**: architecture.md matches `scheduler.py` and `main.py` (10s drain, pending-warning, reconcile of interrupted runs).
- **ADR-0008**: consistent with shipped preview + 2026-09-07 rule-card refactor amendments; no stale `merge_scopes` references.
- **ADR-0009**: matches access.py semantics (404-hiding scope checks), admin routes, migration `20260908_0001`, global_settings model.
- **Root AGENTS.md doc-map**: all listed files exist; mypy-baseline path correctly points to `backend/docs/`.
- **Query key structure**: frontend/docs/architecture.md matches `queryKeys.ts` except later additions (folded into D11).
- **No stale symbol references**: `merge_scopes` and `manualChunks` appear only in historical plans/decisions.md where correctly recorded as deleted/removed.

## Docs health verdict

The docs are recently maintained and mostly trustworthy — the RBAC/labelizer/scheduler stories are documented accurately and the decision log is exemplary. The rot is concentrated at the **pivot points**: the RJSF→custom-renderer switch (D1), the Rolldown adoption (D9/D10), and the data-model page (D4–D6, D12–D14), which has drifted column-by-column as models grew. The two spec flags (D2/D3) are the only items requiring operator action rather than doc edits.
