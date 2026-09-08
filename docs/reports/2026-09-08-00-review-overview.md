# Project Review — Overview & Executive Summary — 2026-09-08

Full-project review of GMC Feed Master at `main` head `6cd1f45` (working tree clean). Areas: open findings, backend logic, frontend code, UX/i18n, tooling/CI/deployment, documentation consistency.

## Methodology

- **Five parallel domain reviews** (backend logic, frontend code, UX, tooling, docs-vs-spec) dispatched as isolated review agents, each with a known-findings list to avoid re-reporting tracked TODO.md items; each instructed to verify claims in source before reporting (read-only — no code modified).
- **Controller verification of every Important-or-higher claim** against the actual source, plus targeted refutation checks. Two findings were **refuted** on verification (backend B3 "runner lock race" — atomic under single-loop asyncio semantics; tooling T10 "codeSplitting option inert" — confirmed as the correct Vite 8 API via current docs). One agent finding was **downgraded** by reachability analysis (B2 — filter plugin crash unreachable via the pipeline today); one was upgraded in scope (T2 — ruff is absent from the lockfile entirely, not merely "unpinned").
- **Tooling**: CodeGraph call-path exploration per the codegraph-ast-grep skill; Vite 8 chunking API verified via Context7 current docs; severity calibration conservative — no Critical findings survived verification, and the two agent-proposed Criticals are documented with their downgrade rationale.
- **Incident note**: the first docs-review agent returned an empty result (the documented 2026-09-07 environment lesson); it was re-dispatched and produced the full report.
- No tests were executed during this review; all evidence is source-based. Nothing was committed; only this `docs/reports/` set was created.

## Verdict

**Overall health: good, with concentrated fixable gaps.** The load-bearing backend invariants all verify (run lock, atomic publish, plugin contract, delta mechanics, retention purge, client scoping on recent routes), the frontend state layer is disciplined (TanStack Query conventions, invalidation, guards), local tooling hygiene is clean (lockfiles current, nothing tracked that should be ignored, no secrets), and the TODO/backlog discipline is exemplary. The review's 60+ findings cluster in five places rather than spreading across the codebase — error-path UX, CI enforcement, pivot-point doc drift, German copy quality, and one tenancy-scoping gap in the plugin config API.

## Finding statistics

| Report | Important | Medium | Minor | Other |
|---|---|---|---|---|
| 02 Backend logic | 1 | 1 | 3 | 1 refuted (B3) |
| 03 Frontend | 3 | 5 | 10 | — |
| 04 UX & i18n | 6 | 5 | 5 | 1 known-worse (U15), 2 cross-duplicates |
| 05 Tooling/CI | 4 | 3 | 4 | 1 refuted (T10) |
| 06 Docs | 3 (2 are operator flags) | 8 | 5 | — |
| **Raw total** | **17** | **22** | **27** | |
| **Unique after dedup** | **15** | **~21** | **~25** | ≈61 unique findings |

Cross-report duplicates were unified: F3=U2 (labelizer silent saves), F10≈U1 (rotate-token fallback), F11=U13 (delete toasts "Saved"), F7=U3+U4 (missing de keys), T9=D15 (README proxy), T8=D1 (RJSF).

## Top 10 findings (prioritized)

1. **[B1] Scoped users can read/write global-tier plugin config/data** — `enforce_scope_access` returns without raising when no `client_id`/`feed_source_id` query param is present, and the plugin config/data routes then resolve `scope="global"`. The global tier merges into every client's feeds, so this is a cross-tenant write for non-admin users. Security-class; the strongest backend finding.
2. **[T1+T2] The documented quality gates run nowhere in CI** — CI has no ruff step, no mypy step, and ruff isn't in the dev group/lockfile at all (`uv run ruff` only works via a global install). AGENTS.md's "full CI check" is currently unenforceable.
3. **[F2] Export diff area shows a perpetual loading spinner** — disabled TanStack Query reports `status: 'pending'`, and `ExportVersionDiff` checks `isPending` before the empty state; the "select versions" hint is unreachable.
4. **[F3/U2] Labelizer saves fail silently** — `mutateAsync` without try/catch, called via `void save…()`; failed saves produce unhandled rejections and zero user feedback on the most recently built core page.
5. **[U1/F10] Token-rotation failure can present as success** — the rotate flow's error fallback is the success string ("Export token rotated successfully") whenever the server sends no detail (e.g., network failure). Security-relevant: the old token still works.
6. **[F1] SetupPage calls a hook after an early return** — Rules-of-Hooks violation; crash-class if `feedSourceId` toggles while mounted. Also symptomatic: no frontend linter exists to catch it (T7).
7. **[T3] Alembic ignores `DATABASE_URL`** — `alembic/env.py` reads only the hardcoded `alembic.ini` URL; the documented `DATABASE_URL=… uv run alembic upgrade head` command has no effect and silently targets the wrong DB on non-localhost hosts.
8. **[T4] `make plugin-test` — and therefore `make test` — is broken** — runs `uv run` from the repo root where no pyproject exists; the AGENTS.md contract-test workflow fails via Make.
9. **[D1] ADR-0002 prescribes RJSF; a custom `JsonSchemaForm` shipped** — the ADR's "rejected alternative" is the implementation; RJSF/AJV mentions also live in plugin-uis.md, backend/docs/plugins.md, and the AGENTS.md doc-map. Related Rolldown drift: D9/D10.
10. **[U3/U4/F7 + U7] German i18n parity and register** — four de keys missing (compare button, auto-mapper toasts), and the customLabels namespace switches to informal "du" while the rest of the app uses "Sie", with grammar and Denglisch issues.

## Operator flags (spec action required)

Per the binding rule (fix the doc, never the spec), these need **spec amendments by the operator** — the docs match the code:

- **[D2]** Spec §10 ("labelizer stays `[global, client]` only — no per-feed-source granularity") contradicts spec §2/§5.9 and the shipped feed_source data scopes.
- **[D3]** Spec §2 still says "single user, no role model"; two-role RBAC shipped per ADR-0009.

## Cross-cutting themes

1. **Error-path neglect.** Success paths are polished; failure paths lag — silent saves (F3), missing `onError` (F5), success-string fallback (U1/F10), 500-on-malformed-param (B7), latent unguarded `config.get` (B2). The older pages established a good pattern (`notifyApiError` + try/catch); the newest surfaces (labelizer, admin area) didn't follow it.
2. **Enforcement drift.** AGENTS.md documents a quality contract (ruff, mypy, frontend lint, contract tests via Make) that CI does not — and partially cannot — execute. T1–T4+T7 are one mechanical PR.
3. **Pivot-point doc rot.** Every place where the project changed direction (RJSF → custom renderer; Rollup → Rolldown; single-user → RBAC; labelizer scope) left contradicted docs behind, while everything documented *since* the pivot is accurate. The data-model page drifted column-by-column (D4–D6, D12–D14).
4. **German copy debt.** Missing keys, register clash, grammar, Denglisch, and pluralization gaps (U15's full list extends TODO 9.1) — one focused i18n pass resolves ~10 findings.
5. **Known-findings discipline works.** The TODO/msg-board inventory anticipated several review themes (i18n plurals, aria-label robustness, lint baselines, source enum). No `[x]` item was found regressed; nothing `[ ]` was found already done. The ruff item is the one case where reality is worse than documented (absent from lockfile, not just unpinned).

## What held up well (verified)

- Run lock (atomic under asyncio), atomic publish (`os.replace`), plugin `original_product` read-only contract, delta/content-hash mechanics, 90-day retention purge ordering, reserved plugin routes, admin-route gating, batch-lookup/preview body scope enforcement.
- TanStack Query invalidation strategy (rollback prefix-match, 401 session reset, product-lookup key normalization), dnd-kit id stability, dirty guards, route error boundary.
- Lockfiles current and committed; nothing tracked that should be ignored; no secrets in the tree; alembic single-head.
- TODO.md cycle log, refuted-premise recording, and decisions.md are better than most production repos.

## Suggested next cycle (ordered)

1. **Security fix**: B1 (global-tier plugin config guard) — small, self-contained, test with scoped-user fixtures.
2. **Tooling PR**: T2 (ruff in dev group) + T1 (CI lint/typecheck steps) + T4 (Makefile path) + T3 (alembic DATABASE_URL) + T7 (eslint) — restores the documented quality contract.
3. **Frontend error-path sweep**: F1, F2, F3, F10, F5, F11 — one coherent "failure feedback" pass with tests.
4. **Docs PR**: D1/D9/D10 (ADR amendments) + D4–D8/D12–D16 (data-model/api.md refresh); forward D2/D3 spec flags to the operator.
5. **i18n pass**: U3/U4 missing keys + U7 register + U15 plurals (+ TODO 9.1) + U6 value translation.
6. **UX hardening**: U5 (keyboard rows), U12 (NotFound), U11 (disabled-nav hint), F8 numeric validation.
7. Backlog P2 pool as capacity allows; 8.1 (M11+ scope) remains the owner's gating decision.

## Report index

| File | Contents |
|------|----------|
| `2026-09-08-01-open-findings.md` | Audited inventory of every tracked open item (TODO.md, message board, carried minors, ops notes) with current status |
| `2026-09-08-02-backend-logic.md` | Backend findings B1–B7, refuted B3, confirmed-knowns, verified invariants |
| `2026-09-08-03-frontend.md` | Frontend findings F1–F18, verified invariants |
| `2026-09-08-04-ux-i18n.md` | UX findings U1–U18, i18n audit table per namespace |
| `2026-09-08-05-tooling.md` | Tooling findings T1–T13, refuted T10, CI gate matrix, hygiene notes |
| `2026-09-08-06-docs-consistency.md` | Docs findings D1–D16, operator flags D2/D3, endpoint coverage appendix |
