# Labelizer Polish Cycle — Design

Date: 2026-09-07
Status: Approved (brainstorm with operator)
Scope: `plugins/core/custom_labels` + `backend/app/staging/config_resolver.py` +
`backend/app/plugins/manifest.py` + `frontend/src/features/customLabels` +
backend test files + docs
Builds on: `2026-09-05-labelizer-live-matching-and-tier-ux-design.md` and
`2026-09-05-labelizer-plugin-ux-design.md` (both cycles complete; their final
whole-branch reviews deferred the items closed here)

## Problem

Both labelizer cycles ended with final reviews that deferred a set of minors
and recommendations to the backlog. None is Critical or Important, but
together they leave dead code in the plugin runtime path, a stale-behavior
preview hook, one hardcoded-English aria-label, untranslated pluralization,
weak tests, and two hand-synced fixture copies. This cycle closes every
still-open item so the labelizer area carries no known debt.

## Verified current state (facts, not review notes)

- `merge_scopes` (`backend/app/staging/config_resolver.py:47`) has zero
  production callers — production resolves via `_resolve_declared` /
  `resolve_config_bundle`; only `backend/tests/test_config_merge.py` and
  `backend/tests/test_custom_labels_delta.py` call it.
- `preview.__annotations__` lines
  (`plugins/core/custom_labels/plugin.py:348-349`) re-assign annotations the
  `def preview(...)` signature already carries (`payload: PreviewRequest`,
  return type included).
- `noActiveRules` dead i18n key: already gone (verified by grep) — no task.
- `frontend/docs/plugin-uis.md` trailing newline: already fixed — no task.
- Spec §197 doc-tension: closed post-cycle by `a134ffe` — no task.

## Tasks

### T1 — Backend dead-code removal

- Delete `merge_scopes` from `config_resolver.py`. Rewrite its two test
  consumers to exercise `resolve_config_bundle` (the manifest-driven path
  production actually uses) so the same merge semantics stay covered.
- Delete the redundant `preview.__annotations__` lines in
  `plugins/core/custom_labels/plugin.py:348-349`. RED proof: the preview route
  tests (which exercise request-body parsing through FastAPI) stay green
  after removal.
- Adjudicate the "dead non-string-key check" claim
  (`backend/app/plugins/manifest.py:70-71`): probe a non-string
  `config_merge.<key>.key` through the real manifest loader. If unreachable,
  delete the check; if live, keep it and add the missing test.
- Add the untested empty-`{}` `config_merge` branch test.
- Fix the mid-file import in the offending backend test file (locate: the
  cycle-1 Task-1 minor; move to top).
- Gate: backend full suite (`pytest -n auto`, real PostgreSQL); ruff/mypy
  zero new in touched files.

### T2 — Shared equivalence fixture + backend test hygiene

- Extract the hand-synced fixtures duplicated across
  `backend/tests/test_config_merge.py` and
  `backend/tests/test_custom_labels_delta.py` into one shared test helper
  (module under `backend/tests/`, imported by both suites).
  `frontend/src/features/customLabels/scopeMerge.test.ts` stays TS-local —
  cross-language fixture sharing rejected as coupling (decision recorded in
  T6).
- Fix the double module-load in backend tests (importlib preamble; UNIQUE
  module names per load).
- Gate: backend full suite.

### T3 — usePreview behavior (TDD)

- Reset `error` at request start: a new preview request clears any previous
  error (loading state replaces the stale error).
- Clear the previous result on 422: the UI must never show match results
  contradicted by the just-rejected input.
- RED tests first, then implement (both changes are operator-approved
  behavior changes; the old shapes were brief-mandated, now free to fix).
- De-flake `usePreview.test.tsx`: remove real-timer margins in favor of
  deterministic waits / fake timers.
- Gate: frontend suite + typecheck.

### T4 — CustomLabelsUI a11y / i18n / memos

- Values-mode Textarea (`frontend/src/features/customLabels/SlotGroup.tsx:126`):
  replace the hardcoded-English `aria-label` (`${rule.name} ids/values`) with
  the same `t()` expression as the visible label
  (`bulk.productIds` / `bulk.valuesFor`), killing the aria/visible mismatch.
- Inherited badge: replace the hardcoded `scope.client`
  (`CustomLabelsUI.tsx:75`) with the existing tier helpers
  (`editableConfigTier`/`currentDataTier` from `scopeMerge.ts`).
- `activeRulesCount` (`SlotGroup.tsx:41`): add `_one`/`_other` plural
  suffixes in en+de (en+de trees stay identical).
- nowrap header groups (`CustomLabelsUI.tsx:251/382/429`): allow wrapping on
  narrow viewports.
- Chain memos: correct the `useMemo` deps in `CustomLabelsUI.tsx` so the
  tier-chain memos stop recomputing on every render.
- Gate: frontend suite + typecheck + build.

### T5 — Test-strength pass

- Strengthen the weak badge assertions in the origin/ScopeBadge tests
  (cycle-1 Task 6/7 minors).
- Directly assert the feed-tier client-data URL (cycle-1 Task 7 minor).
- Add one integration test with origin-bearing rules against the real
  `/plugins/custom_labels/preview` route — tolerance was verified by review
  but never asserted end-to-end.
- Gate: backend + frontend suites.

### T6 — Docs

- `docs/decisions.md` entries:
  - `merge_scopes` deleted (test-only helper; production uses
    `resolve_config_bundle`).
  - `scopeMerge.ts` stays local to `features/customLabels` (promotion deferred
    until a second scoped plugin adopts the pattern — YAGNI).
  - `usePreview` behavior change: error resets at request start; 422 clears
    the previous result.
- No architecture.md / api.md / plugin-uis.md changes — no API surface,
  route, or rendering change in this cycle.

## Out of scope

- Raw coverage interpolation in the info boxes (moot — backend rounds to 1
  decimal).
- Locale-tab JSON reformat (cosmetic).
- Non-labelizer backlog: German findings-tooltip pluralization, ruff/mypy
  pin-or-drop ops decision, icon registry (TODO 3.5), test-wrapper dedup
  (TODO 6.2).
- The cycle-1 "fresh-agent re-review" recommendation — the cycle's final
  whole-branch review fulfills it when subagent infra has recovered.

## Conventions (binding)

- No comments in code; all strings via `t()`; en+de identical i18n trees.
- TDD per task; per-task review; gates after each task
  (`pytest -n auto` backend, `npm test -- --run && npm run typecheck && npm run build`
  frontend); final whole-branch review before closing.
- RTL-rerender-remounts lesson: prop-change scenarios use stateful harnesses,
  not `rerender`.
- Run backend and frontend suites sequentially, not concurrently
  (load-induced jsdom flakes).
