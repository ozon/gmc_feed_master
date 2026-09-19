# Project Review — Overview & Executive Summary — 2026-09-17

Full-project review of GMC Feed Master at `main` head `077409b` (working tree clean). Areas: backend logic & security, frontend code, architecture & documentation, tooling/testing/DX, and an over-engineering audit.

Finding ID prefixes (`B`, `F`, `A`, `T`, `O`) are **local to this 2026-09-17 review**; the 2026-09-08 review used the same `B`/`F`/`T`/`D` prefixes.

## Methodology

- **Five parallel read-only domain reviews** dispatched as isolated agents (backend, frontend, architecture/docs, tooling/testing, over-engineering audit). Each was given the stack and repo layout, a bounded scope, and an explicit READ-ONLY constraint; none modified code.
- **Controller verification of every Critical and High claim** against source. Verified: the tenant-scope short-circuit (`access.py:87-104`), the missing `/chat` proxy (`vite.config.ts:48`, `Caddyfile*`, `hooks.ts:931`), plugin routers mounted without the scope dependency (`discovery.py:141`), and the `FeedSettingsForm` dirty-gate bug (`FeedSettingsForm.tsx:261-269`). One nuance was checked and it **strengthens** `B1`: the inner guard `require_feed_source` (`access.py:149-158`) is existence-only and does not mitigate the bypass.
- **No tests were run to completion during this review** beyond the targeted slices noted per report; all findings are source-verified. Nothing was committed; only this `docs/reports/` set was created.
- **Tooling**: CodeGraph index used for call-path exploration; targeted source reads for confirmation.

## Verdict

**Overall health: good, with a small number of load-bearing gaps.** The core engine is faithful to the spec (pipeline order, delta hashing, three-tier scope merge, plugin contract, atomic publish, migration hygiene) and the frontend is disciplined (strict TS with zero `any` in production code, TanStack Query conventions largely held, plugin error isolation wired, en/de i18n parity). The one Critical is a genuine cross-tenant authorization bypass in the shared scope guard. Outside that, the gaps cluster in three places: tenant-isolation boundaries that are opt-in rather than enforced, synchronous work on the single-worker event loop, and a documented quality contract (ruff/mypy/lint/coverage) that the config does not actually deliver. Over-engineering residue is small (~145 lines) — the codebase is not bloated.

## Remediation status — 2026-09-19

Remediation cycles landed since this review (all on `main` unless noted):

- **Over-engineering cuts** — `ec26c7f`: all `O1`–`O12` (net −210 lines).
- **Event-loop relief** — `b103a97`: `B3`, `B4`, `B5`, `B9`.
- **Quality-contract gaps** — branch `feat/quality-contract-gaps`: `T1`, `T2`, `T4`, `T5` (plugins-only), `T6`; `T3`/`T7` were already resolved.
- Earlier: `B1`/`A2`/`A3` at `cccb501`; frontend `F1`–`F10`/`F12` at `0a98f4b`.

Still open from the prioritized list: `B2` (SSRF), scale/perf (`B6`/`B7`), single-worker invariants (`A9`/`A10`), docs/spec rot (`A1`, `A4`–`A16`), backend lows (`B8`, `B10`–`B13`), deferred frontend `F11`/`F13`, and mypy `strict` (deferred; 3274 errors). Tooling `T10`–`T12` are fixed; `T8`/`T9` are deferred by operator choice.

## Finding statistics

| Report | Critical | High | Medium | Low |
|---|---|---|---|---|
| 01 Backend | 1 | 2 | 5 | 6 |
| 02 Frontend | 0 | 1 | 6 | 6 |
| 03 Architecture & docs | 0 | 3 | 8 | 5 |
| 04 Tooling/testing | 0 | 3 | 5 | 4 |
| 05 Over-engineering | — | — | — | — (12 cuts, net ≈ -145 lines) |
| **Raw total** | **1** | **9** | **24** | **21** |

Cross-report duplicates unified: frontend/ESLint (`F5` = `T3`), `placeholders.tsx` (`F10` ⊂ `O12`). The 2026-09-08 review's `B1` is the same function as this review's `B1` but a **distinct remaining bypass** (missing-param fallthrough vs. caller-supplied `client_id` short-circuit); see `01-backend.md`.

## Top findings (prioritized)

1. **[B1] Cross-tenant authorization bypass in `enforce_scope_access`** — `access.py:87-104` resolves a caller-supplied `client_id` first and returns before validating `feed_source_id`. Any non-admin appending `?client_id=<own>` to `/feed-sources/{id}/...` routes skips the ownership check for another tenant's feed source. **Verified.**
2. **[A2] Plugin routers bypass central tenant-scope enforcement** — `discovery.py:141` mounts plugin routers with no `enforce_scope_access` dependency (core routers get it at `main.py:209-220`); isolation is opt-in per plugin body.
3. **[A3] Global taxonomy file writable by any authenticated user** — `POST /plugins/category/taxonomy/fetch` (`plugins/core/category/plugin.py:426-475`) replaces a shared file guarded only by `get_current_user`, while global plugin config requires admin.
4. **[B2] SSRF via user-controlled URLs** — `source_url` and product image URLs fetched with no scheme allowlist or private-IP blocking (`ingest/fetch.py:32`, `qc/image_probe.py:36-41`); the image probe follows redirects.
5. **[B3] Export blocks the event loop and doubles memory** — full feed rendered in memory then synchronous file I/O inside `async` (`export/service.py:80,128,150`, `export/renderer.py:68-87`), violating the documented streaming threshold.
6. **[T1] `/chat` is not proxied in dev or prod** — backend route and same-origin frontend call exist, but `/chat` is absent from `vite.config.ts`, both Caddyfiles, and README; the feature 404s in dev and falls through to static HTML in prod.
7. **[T2] No security or dependency scanning in CI** — no dependabot, pip-audit, or npm audit gate, while `litellm==1.101.0` is pinned.
8. **[F1] Feed settings with only AI-QC/basic-auth changes cannot be saved** — Save is gated on TanStack Form `isDirty`, but those fields live in separate `useState` (`FeedSettingsForm.tsx:261-269`). **Verified.**
9. **[A1] The authoritative spec is now factually wrong** — it still declares "single user, no role model" and "no Celery/Redis", while RBAC, LiteLLM+Redis, and an opt-in enrichment stage have shipped.
10. **[T3/T5] Frontend has no lint gate; backend mypy excludes `plugins/`** — the one domain with a runtime contract is untypechecked, and `react-hooks/exhaustive-deps` is entirely unenforced.
11. **[A9] Single-worker invariants are implicit and unenforced** — in-process `asyncio.Lock` + in-process APScheduler silently break the skip rule at `--workers > 1`.
12. **[B4/B5] Plugins run synchronously with no timeout; per-plugin run state collides** — contradicts the AGENTS-documented `asyncio.wait_for` timeout and shares state across two instances of the same plugin.

## Operator flags (spec action required)

Per the binding rule (fix the doc, never the spec), the implementation has outgrown the spec and needs **spec amendments by the operator**:

- **[A1]** `gmc-feed-engine-spec.md` §2 ("single user … no role model"; "no Celery/Redis") vs. shipped RBAC (ADR-0009) and LiteLLM Redis cache (ADR-0010). §4/§9 also omit `UserClient`, `GlobalSetting`, `Session`, `ImageDimension`, `AiProviderConfig`, `AiUsageLog`, `PromptTemplate`, and the Admin/AI/Chat areas.
- **[A15]** Category manifest declares `data_scope: ["global","client"]` while spec §5.9 says Category is "client-scope only for MVP".
- **[A8]** Spec §5.4 / `architecture.md` say drop decisions are "logged with plugin_id and reason"; the runtime captures no reason (`steps.py:280-283`).

## Cross-cutting themes

1. **Tenant isolation rests on one central guard that is bypassable and opt-in.** `B1` (guard short-circuits), `A2` (plugin routers skip the guard), `A3` (a global artifact writable by a scoped user) are three faces of the same boundary. Fix the guard once, route every entry point through it, and add cross-tenant tests for each route family — the suite currently has none for `enforce_scope_access` (`B1`).
2. **Synchronous work on the single-worker event loop.** Export rendering and file I/O (`B3`), plugin `process()` without a timeout (`B4`), and image decoding (`B9`) all block the loop, stalling requests and the scheduler simultaneously because the deployment is `--workers 1`.
3. **Single-worker invariants are assumed, not enforced.** `A9` (in-process lock/scheduler) and `A10` are safe only under the one-worker constraint; nothing asserts it. Either a DB advisory lock or a startup assertion.
4. **The documented quality contract overstates the configuration.** `T3` (no ESLint at all), `T4` (ruff's documented rule set not enabled — 15 latent violations), `T5` (mypy non-strict, `plugins/` excluded), `T6` (coverage and CI gate doc-vs-actual), `A13`/`A14` (stale doc paths). Cheap to close, and it restores the AGENTS.md credibility the repo otherwise earns.
5. **Per-row write amplification.** `B6` (staging/plugin/retention writes one statement per product), `B7` and `A10` (whole-table scans per run). Fine at current scale, painful on large catalogs.
6. **Doc rot at pivot points.** `A1`, `A4`–`A7`, `A12`–`A16`: everything documented since a pivot is accurate; the pre-pivot claims remain. Same pattern the 2026-09-08 review called out.
7. **Over-engineering residue is small and safe to clear.** ~145 lines, zero dependency removals, all in `O1`–`O12`.

## What held up well (verified)

- **Core engine fidelity:** pipeline order incl. opt-in enrichment (`steps.py:558`), canonical delta hashing, three-tier `global → client → feed_source` merge, plugin runtime contract with read-only `original_product`, reserved plugin routes, atomic publish (`temp → os.replace`), export-token log redaction (`main.py:68-86`).
- **Migration hygiene:** single linear alembic chain (head `b1a2c3d4e5f6`), `alembic check` drift gate in CI, hot FK columns indexed.
- **Static gates that do exist:** `ruff check . ../plugins` exit-0 and `mypy .` clean across 275 files at review time; frontend `tsc -b` clean under `strict` with zero `any` in production code.
- **Frontend discipline:** TanStack Query conventions largely held (the deviations are accumulators/drafts), all 13 feature pages lazy-loaded with vendor chunking, ADR-0004 plugin error isolation wired in both surfaces, 100 test files / 564 tests passing, en/de i18n key parity complete.
- **Backend test infrastructure:** 1079 tests, template-database cloning for xdist, `TestClock`, contract tests with targeted negative cases, and the reportlog-based failure gate.
- **Repo hygiene:** clean working tree, `uv lock --check` passes, `npm audit` reports 0 vulnerabilities, no secrets tracked, `.gitignore` comprehensive.

## Suggested next cycle (ordered)

1. **Authorization fix (do first):** `B1` — validate every present scope identifier instead of short-circuiting; add cross-tenant tests for every feed-source route family. Small, self-contained, high value.
2. **Isolation sweep:** `A2` (plugin routers through the scope dependency + contract assertion) and `A3` (gate taxonomy fetch to admin).
3. **SSRF hardening:** `B2` — scheme allowlist plus private/link-local IP rejection on ingest and image probe, including redirect targets.
4. **Event-loop relief:** `B3` (streaming export + `asyncio.to_thread` file ops), `B4` (threaded plugins with `asyncio.wait_for`), `B9` (decode images off-loop).
5. **Quality-contract PR:** `T3` (ESLint + `npm run lint` + CI), `T4` (enable documented ruff rules — 15 fixes), `T5` (mypy strict + `plugins/` in path), `T1` (add `/chat` to proxy configs + README), `T6`/`T2` (coverage floor + scanning).
6. **Frontend correctness batch:** `F1` (dirty gate), `F2`/`F4` (server-state conversions), `F6` (unsaved-changes guard), `F3`/`F7` (memoization).
7. **Scale/perf batch:** `B6`/`B7` bulk writes and targeted selects; `A9` advisory lock or startup assertion; `A10` SQL-side config filtering.
8. **Docs/spec PR:** forward `A1`/`A15`/`A8` spec flags to the operator; fix `A4`–`A7`, `A12`–`A14`, `A16`.
9. **Over-engineering cleanup:** `O1`–`O12` (~145 lines) as a low-risk janitorial pass.

## Report index

| File | Contents |
|------|----------|
| `2026-09-17-01-backend.md` | Backend findings `B1`–`B14`; static-gate and targeted-test results; verified invariants |
| `2026-09-17-02-frontend.md` | Frontend findings `F1`–`F13`; typecheck/vitest results; clean areas |
| `2026-09-17-03-architecture-docs.md` | Architecture & docs findings `A1`–`A16`; spec-vs-docs-vs-code reconciliation; operator flags |
| `2026-09-17-04-tooling-testing.md` | Tooling/CI/testing/deploy findings `T1`–`T12`; CI gate matrix |
| `2026-09-17-05-overengineering-audit.md` | Ranked cuts `O1`–`O12`, net line/dep estimate, investigated-and-rejected list |
