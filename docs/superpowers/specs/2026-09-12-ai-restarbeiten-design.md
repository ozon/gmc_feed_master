# AI Integration Roadmap + Z1 (AI Restarbeiten) — Design

Date: 2026-09-12
Status: Approved in brainstorming (operator)
Baseline: main at e87a72a (backend 1188 tests / ruff 507 / mypy clean; frontend 490 + typecheck + build clean)

## Roadmap — 6 cycles, build order fixed by operator

Order: **Z1 → Chat (Z5+Z6) → Z2 → Z3 → Z4**

| # | Cycle | Content | Size |
|---|-------|---------|------|
| Z1 | AI-Restarbeiten | 5 items below | S |
| Z2 | Findings visualization & quality improvement | Run-over-run delta (fixed/new/remaining), trend/score per feed source, grouping by rule; 1 backend endpoint (findings history/compare) + frontend | M |
| Z3 | Feature 4: AI-QC rules | `policy_check` + `image_quality` as QC rules over the AIProvider abstraction; findings surface in the normal QC UI (client-visible) | M–L |
| Z4 | Feature 5: attribute enrichment | Enrichment module (pipeline step or on-demand) + UI with suggest→apply flow, client-visible | L |
| Z5 | AI-Chat backend | `tools`/`tool_calls` protocol extension on `AIProvider`, chat endpoint with read-only tool loop (`query_staging_products`, `query_qc_findings`, `query_export_runs`), session scoping via `CurrentUser.client_ids` | M–L |
| Z6 | AI-Chat frontend | App-wide slide-over widget in the AppShell, reachable from every page; client-side history (no DB table in phase 1) | M |

Cross-cutting (operator decisions):
- Client-user visibility falls out of Z3/Z4 UIs (they live on feed-scoped pages) and the chat (Z5/Z6); admin AI configuration (providers, templates) stays admin-only.
- Chat phase 1 is read/query only — no write actions, no tool-calling confirmation flows. Tenant boundary follows the session: `client_ids` scoping, admins query globally. No separate permission model.
- Chat runs over the AIProvider abstraction (uniform caching/cost tracking); it uses a system prompt with tool definitions, not a library template.
- Chat phase 1: no streaming, no DB-persisted history (both retrofit-friendly).

## Z1 scope — 5 items

### 1. UsagePage time-range filters (frontend only)
Backend already accepts `from`/`to` (aliased query params) on `GET /admin/ai/usage`. Extend `AiUsageParams` with optional ISO `from`/`to`; `useAiUsage` appends them to the query string only when set. UI: two clearable `DateInput`s (Mantine Dates, already installed) beside the group-by Select. `from` → ISO of picked date 00:00; `to` → ISO of picked date 23:59:59 (end-of-day so "today" includes today's rows). i18n keys en+de.

### 2. Malformed-brace warning (backend + frontend mirror)
`validate_template` collects `{{...}}`-shaped candidates (`\{\{[^{}]*\}\}`) from both prompts; candidates that `PLACEHOLDER_RE` does not match produce a warning: `malformed placeholder {{Title}} — use a lowercase identifier like {{title}}`. Sorted, deduplicated. Stays a warning (renders literally today; non-blocking). TemplateEditor mirrors the check client-side (same mirror pattern as CANONICAL_VARIABLES) and shows it in the existing orange warning list.

### 3. Non-canonical declared variables become errors (backend)
Spec data-model says declared variables are validated. In `validate_template`, the declared-but-unused loop partitions: canonical+unused stays a warning; **non-canonical declared becomes an error** ("declared variable %r is not a canonical variable of this task type"). Declared+used+non-canonical is already an error via the used-check. Breaking by design: previously accepted templates now 422.

### 4. Activation deadlock → 409 (backend)
AB-BA activation deadlock currently surfaces as 500 (asyncpg `DeadlockDetected`, SQLAlchemy `OperationalError`). Both routes that activate (`create_prompt_template` with `activate=true`, `activate_prompt_template`) map it to the existing 409 "concurrent …; retry": keep `IntegrityError` → 409, add `OperationalError` whose `orig` message contains "deadlock" → 409, re-raise everything else. Detection factored as a small testable helper.

### 5. Builtin cache staleness → content-hash version (backend, root cause)
Reported staleness: Feature 2 changed builtin prompt rendering (data tags + injection guard) but `TEMPLATE_VERSION_BUILTIN = "builtin"` stayed constant → pre-deploy cache rows remain hits until retention purge. Same trap on every future builtin prompt edit. Fix at the root: the builtin fallback version becomes `builtin:{sha256(system+NUL+user)[:12]}` (computed in `_resolve_template`; sha256 of short strings is negligible per call). Any builtin prompt change auto-invalidates; no delete endpoint, no manual bumps, no migration (old `builtin` rows simply stop hitting; retention purges them). Chosen over delete-on-activate, which does not fix deploy-time staleness.

## Testing
- `test_ai_templates.py`: malformed-brace cases (`{{Title}}`, `{{}}`, valid `{{ title }}` produces no warning); declared-non-canonical → error; declared-unused-canonical stays warning.
- `test_ai_service.py`: builtin version is content-derived (changes when spec prompts change, differs from plain `"builtin"`); cache lookup/store use the hashed version.
- `test_ai_admin_api.py`: usage `from`/`to` filtering (if not already covered); deadlock-`OperationalError` → 409 via the helper; IntegrityError → 409 unchanged.
- Frontend: UsagePage test (date inputs render, query URL carries `from`/`to`); TemplateEditor test (malformed warning visible with `data-testid`).

## Docs (same commit)
- `backend/docs/api.md`: activate/create 409 wording includes deadlock; usage `from`/`to` documented.
- `backend/docs/data-model.md`: builtin template_version is content-hashed.
- `docs/decisions.md`: Z1 entry (incl. non-canonical → error breaking change, content-hash choice over delete-on-activate).

## Out of scope (stays in ledger)
- `activate=false` create-branch test; api.md preview-404 wording polish; delete-on-activate cache purge; UsagePage per-row drilldown.
