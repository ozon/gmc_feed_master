# Open Findings Inventory — 2026-09-08

Status audit of every tracked open item at the time of the full project review. Sources: `TODO.md` (working backlog, cycle log, working notes), `AGENT_MSG_BOARD.md`, and verification against the current tree (head `6cd1f45`, working tree clean).

Severity legend: P0 = before any new milestone · P1 = before next follow-up work · P2 = nice to have. Status legend: `[ ]` open · `[x]` complete · `[!]` blocked.

## 1. Open TODO.md items

| ID | Pri | Status | Item | Note |
|----|-----|--------|------|------|
| 8.1 | P0 | `[ ]` | M11+ scope planning | Owner meta-task. Options recorded: source-enum question (2.2), core plugins (Category), or new feature work. Blocks nothing technical but gates roadmap work. |
| 2.2 | P2 | `[ ]` (deferred) | `ExportVersionOut.source`: spec's 3-value enum `{scheduled, manual, rollback}` vs shipped 2-value `run`/`rollback` | Owner question pending ("ask before implementing"). Verified still 2-value in `backend/app/export/service.py` (`'run'`/`'rollback'`). Frontend whitelist matches backend, so no user-visible defect — a spec-contract gap. |
| 3.5 | P2 | `[ ]` | `PluginIconMap` is a 4-icon skeleton + circle fallback | Cosmetic; accepted fallback behavior, needs icon-registry expansion. |
| 5.1 | P2 | `[!]` blocked | Core plugin-specific UIs (Labelizer/Category/Rules) | Labelizer + Rules + Filter shipped 2026-09-04/05; **Category plugin still unimplemented** — the remaining blocker. |
| 6.1 | P2 | `[ ]` | Newline-at-EOF pass for M10-d files | Cosmetic; `git diff --check` hygiene. |
| 6.2 | P2 | `[ ]` | Centralize `QueryClientProvider` in test wrapper (fix double-wrap) | Test-noise only; functionally benign. |
| 9.1 | P2 | `[ ]` | customLabels i18n plural forms (`matchedCount`, `slotLabeled`, `freshnessHint`) | German singular/plural collisions. See UX report: the plural gap is wider than tracked (U15). |
| 9.2 | P2 | `[ ]` | `usePreview` disabled-path test: replace 1500ms real-time sleep with fake timers | Deterministic-test follow-up. |
| 9.3 | P2 | `[ ]` | `labels_equivalence.py`: `MERGED_SLOT_RULES` aliases fixture rows; deep-copy instead | Test-suite mutation safety. |
| 9.4 | P2 | `[!]` blocked | Inherited-badge UI test cannot distinguish derived `sourceTier` from re-hardcode | Blocked until a second scoped plugin / third data tier exists. |
| 9.5 | P2 | `[ ]` | `manifest.py` `config_merge` key-check error message overstates | Unreachable in production (`json.loads`); wording only. |
| 9.6 | P2 | `[ ]` | App-side `plugin.py` re-exec under `create_app(plugins_dir=...)` in tests | Test-only; documented in decisions.md with qualifier. |
| 10.1 | P2 | `[ ]` | mypy baseline cleanup (42 errors) | Baseline snapshotted in `backend/docs/mypy-baseline.md`; exit-0 gate planned after cleanup (currently ruff-style "no new" convention). See tooling report T1/T2 — the gate runs nowhere in CI today. |

## 2. Carried minors (recorded inside TODO Done entries, not standalone items)

| Source | Item |
|--------|------|
| 1.2/1.9 Done | Enable-path non-409 toggle errors toast "Could not disable plugin." — needs a future `enableFailed`/`toggleFailed` i18n key (blocked by a no-new-keys cycle decision). |
| 1.10 Done | Findings-badge `aria-label` on Mantine `<span>` may be suppressed by some SR/browser combos — `role="img"` or visually-hidden text candidate. |
| 1.5 Done | Disabled diff-key test's second render stays mounted (intent naming); `JSON.stringify` key comparisons in tests are cosmetic. |
| 1.6 Done | Prefix-matcher seed assertion gap: spy proves the hook passes the prefix, not that query-core's matcher matches a concrete diff key. |
| 1.4 Done | Pointer interaction test coupled to dnd-kit geometry internals — revisit on any dnd-kit major bump. |

## 3. Ops notes (from TODO working notes + message board)

| Item | Status 2026-09-08 |
|------|-------------------|
| ruff ~506 pre-existing errors, "unpinned but installed" | **Worse than documented**: ruff is not in the backend dev group at all (`backend/pyproject.toml` dev group has no ruff; `uv.lock` has no ruff). `uv run ruff` only works because a global ruff happens to be on PATH. See tooling report T2. |
| mypy not a dev dep | **Resolved** 2026-09-08: mypy 2.3.1 added with `[tool.mypy]` config + 42-error baseline (TODO 10.1). |
| ProductsPage.test.tsx parallel-load flake (passes solo) | Still open; documented; worth a fake-timer pass. |
| vite `allowedHosts` contains machine-specific host (`x.hermes-tower.com`) | Still present (`frontend/vite.config.ts:35`); also Caddyfile.dev site label (`http://localhost`) mismatch noted on the message board. |
| 65 unclassified pytest warnings | Still unclassified (mentioned once on the message board, no task filed). |
| German findings tooltips lack pluralization (`1 Warnungen`) | Still open; UX audit found the plural gap extends to more keys (U15). |
| Frontend full-suite flake under concurrent backend load | Known environment behavior; re-run-solo convention documented. |

## 4. Process-level observations

- **TODO.md discipline is exemplary** — cycle log, per-task Done entries with commit hashes, refuted-premise recording (1.2, Task-1 amendment), and a stale-report lesson. The open list is genuinely accurate; nothing audited as `[x]` was found reverted, and nothing `[ ]` was found already done (with one nuance: message-board item "ruff/mypy not installed" is half-resolved — mypy yes, ruff no).
- **The known-findings list already anticipated the biggest review themes**: i18n pluralization, aria-label robustness, the source enum, the lint baselines. This review's NEW findings (see other reports) are concentrated where the backlog is thin: error-path UX (toasts/feedback), CI enforcement, and doc-vs-code drift around the RJSF/Rolldown/RBAC pivots.
- **Two spec conflicts require operator action** (docs report D2/D3): spec §10 contradicts spec §2/§5.9 on labelizer feed_source scope, and spec §2 still says "single user, no role model" while RBAC shipped per ADR-0009. Per the binding rule, the spec is authoritative and must be amended by the operator — docs should not be "fixed" to match code here.
- **Environment lesson re-confirmed during this review**: the first docs-review subagent returned empty; it was re-dispatched and produced the report (same failure mode as the 2026-09-07 lesson in TODO.md).

## 5. Suggested triage order

1. 8.1 (owner planning) — unblocks everything downstream.
2. Tooling T1–T4 cluster (CI gate reality, ruff in dev group, alembic DATABASE_URL, `make plugin-test`/`make test` broken) — small, mechanical, restores the documented quality contract.
3. Backend B1 (global-tier plugin config write by scoped users) — the only security-class backend finding.
4. Frontend error-path cluster (F1, F2, F3/F10) — user-visible correctness.
5. Docs D1/D9/D10 (RJSF/Rolldown ADR drift) + spec flags D2/D3.
6. The P2 pool as capacity allows (plurals 9.1 + U15 keys make one coherent i18n pass).
