# AGENT_MSG_BOARD.md

> Message board for coding agents working in this repo. Read this before starting work. Append your message at the end when you leave. Keep entries dated and concise.

---

## 2026-09-01 — Handoff after three cycles (m11a-p1s, m11b-correctness, m11c-micro)

**State:** main is pushed and in sync with origin (head `e9500b9`). Working tree clean. All gates green on merged main: backend 662/662 (`pytest -n auto`, real PostgreSQL via `TEST_DATABASE_URL`), frontend 168/168 + typecheck + build clean, no chunk-size warning.

**Read first:**
- `TODO.md` — the working backlog. Status legend, cycle log, and "Working notes for the next agent" at the bottom are kept current.
- `.superpowers/sdd/progress.md` — the SDD ledger (gitignored, lives on disk). Per-task tables, review verdicts, and carried-minors triage for every cycle. Trust it over your own recollection after any context loss.
- Specs/plans under `docs/superpowers/` — the last three cycles' docs are there (`2026-08-31-m11a-p1s-*`, `2026-09-01-m11b-correctness-*`, `2026-09-01-m11c-micro-*`).

**What just landed (2026-08-31 → 2026-09-01):**
- m11a-p1s: owner WIP (manual run trigger backend+frontend, add-feed `source_url`, Caddyfile.dev, ingest bare-structured→generic — spec §5.8 amended to match, owner decision), TODO 3.4 (plugin nav routes by manifest scopes), TODO 1.7 (RouteErrorBoundary for chunk-load failures).
- m11b-correctness: TODO 1.2 rescoped (backend 409 on disabling a plugin in use — the original "backend may return 409" premise was false; we ADDED the 409), TODO 3.3 (logout error toast + unconditional local session clear), TODO 1.8 (findings badges column), shutdown drain for manual-trigger background tasks (lifespan, 10s, pending-warning; exception-logging done-callback).
- m11c-micro: TODO 1.9 (unified `mutateToggle` error handler, both toggle paths), TODO 1.10 (findings-badge aria-labels).

**Open work, in rough priority order:**
1. **P2 pool (TODO 1.3-1.6):** stable dnd-kit ids, palette→workspace drag test, diff queryKey sentinels, rollback diff invalidation. All frontend, all pre-scoped in TODO with files/acceptance.
2. **Small leftovers (noted inside TODO's Done entries):** enable-error toast wording needs a future `enableFailed` i18n key (m11c's no-new-keys constraint blocked it); findings-badge span aria-label SR robustness (`role="img"` or visually-hidden text).
3. **Ops decision needed from the owner:** ruff/mypy are NOT installed in the backend dev group (AGENTS.md lists them as gates but they were never executable — baseline is ~430 ruff / 45 mypy pre-existing errors). Either pin+configure them or drop the gates from AGENTS.md. Also: classify the 65 pytest warnings; vite `allowedHosts` contains a machine-specific host (`x.hermes-tower.com`) and Caddyfile.dev's site label (`http://localhost`) may not match it.
4. **TODO 2.2** stays deferred until the backend decides 2-value vs 3-value export-source enum (ask the owner, don't guess).
5. **Task 8.1 — M11+ planning:** the owner hasn't scoped core plugin implementation (Labelizer/Category/Rules) yet. When they do, that unblocks TODO 5.1 and needs a fresh brainstorming → spec → plan cycle. Don't start it without the owner.

**Conventions that came out of reviews (binding, learned the hard way):**
- en+de i18n trees must stay structurally identical; all new keys in BOTH files in the same commit.
- Files must end with trailing newlines (`git diff --check` clean) — reviewers flag every miss; two cycles' worth of EOF fixes were controller remediations.
- Frontend full-suite runs flake (~1 test) when a heavy backend suite runs concurrently — load-induced jsdom timing. Re-run solo before diagnosing; 3+ consecutive solo greens = accept and move on.
- Brief code snippets have twice contained latent bugs (SQLAlchemy `.select_from` needed; test stub `detail` contradictions). Implementers: expect to fix plan snippets, report the forced deviation honestly — reviewers verify, and honest deviations get approved.
- hooks.ts stays i18n-free (no `useTranslation` there); toasts live at call sites.
- Backend tests: use the `app_factory`/`logged_in_client` patterns in the existing test files; lifespan tests use `app.router.lifespan_context(app)` (see test_m9_lifespan.py).

**Workflow that's been working** (per TODO's header + superpowers): brainstorm scope with the owner → spec in `docs/superpowers/specs/` → plan in `docs/superpowers/plans/` → subagent-driven execution (fresh implementer per task, two-verdict review per task, whole-branch final review) → fix Important findings pre-merge → ff-only merge to main → TODO.md cycle log + progress.md → push (owner has approved pushes after each cycle; confirm anyway).
