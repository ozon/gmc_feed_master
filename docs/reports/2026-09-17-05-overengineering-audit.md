# Over-Engineering Audit — 2026-09-17

Repo-wide ponytail-audit. Scope: over-engineering and complexity **only** — correctness bugs, security holes, and performance are out of scope and covered by reports 01–04. Read-only; nothing applied. Each cut was verified in source (interface really has one implementation, flag really is dead, wrapper really only delegates, dep really is unused).

Tags: `delete` (dead code, nothing replaces it) · `stdlib` (hand-rolled stdlib — function named) · `native` (code/dep doing what the platform already does) · `yagni` (one-implementation abstraction, unset config, one-caller layer) · `shrink` (same logic, fewer lines).

## Status update — 2026-09-19

All 12 cuts applied on `main` at `ec26c7f` (`refactor: apply over-engineering audit cuts (O1-O12)`), net −210 lines across 25 files. `O12` was already absent. Verified at that commit: backend full suite 1436 passed, ruff + mypy clean, frontend typecheck/build/lint clean. The report line count (~-145) excluded the deleted tests and the spec/plan/doc edits folded into the same change.

## Findings (biggest cut first)

1. **`delete`** `backend/scripts/verify_m6_gate.py` + `verify_m9_gate.py` — near-identical 44-line milestone gate runners; no CI/Makefile/script caller (CI gate lives in `.github/workflows/ci.yml`, local in `Makefile`). Replacement: nothing. `O1`
2. **`yagni`** `LabelizerPage`/`LabelizerSetup` — 8-line pass-through wrappers, one caller each. Inline as `custom_labels: (p) => <CustomLabelsUI {...p} onlyTab="ids"/>` in `customComponents.ts` / `configComponents.ts`. `O2`
3. **`yagni`** `RESPONSE_MODELS` duplicates `TASK_SPECS[..].response_model`; only tests read it. Delete the map and the two test asserts. `O3`
4. **`delete`** `ai.constraints.enum_values` — no production caller, only tests. Delete plus its tests. `O4`
5. **`delete`** 3 vestigial plugin frontend shims — `plugins/core/{category,enrichment,custom_labels}/frontend/component.tsx`; `category`/`enrichment` imported nowhere, `custom_labels` only by one test, and the `enrichment` shim is syntactically invalid. `customComponents.ts` is the real mechanism; no `import.meta.glob` discovery exists. Replacement: nothing (import components from `frontend/src`). `O5`
6. **`shrink`** `routes/registry._attribute_sub_kind` re-implements `mapping.matcher._SUB_EFFECTIVE_KINDS` (already imported by `routes/field_mapping`). Use `_SUB_EFFECTIVE_KINDS.get(kind)`. `O6`
7. **`yagni`** `auth.create_session` / `invalidate_session` — trivial delegating wrappers (`store.create`/`store.invalidate`), one caller each. Inline at the `main.py` call sites. `O7`
8. **`yagni`** `ai.tasks.input_hash` — no production caller (cache keys use litellm namespacing). Delete. `O8`
9. **`yagni`** `db.engine.async_database_url` — one-line delegate to `Settings.async_database_url`; sole caller `create_engine`. Inline. `O9`
10. **`delete`** `ai.router.TIERS` — defined, never referenced. Replacement: nothing. `O10`
11. **`delete`** `qc.ai_rules.CHUNK_SIZE` — defined, never referenced. Replacement: nothing. `O11`
12. **`delete`** empty unreferenced `frontend/src/features/placeholders.tsx` (also `F10`). Replacement: nothing. `O12`

**net: ≈ -145 lines, -0 deps possible.**

## Investigated and rejected (not safe to cut)

- `redis` + `diskcache` are never imported directly (litellm imports them) but back the configured Redis/disk cache and are not declared required by litellm — removing breaks caching. Keep.
- `recharts` is not imported directly but is a peer dependency of `@mantine/charts` (used in `RulesTab.tsx`). Keep.
- `Clock`, `InMemorySessionStore`, `ImageProbe`/`PerProductRule` Protocols each have a test double or a second implementation — legitimate seams, not single-implementation abstractions.

## Verdict

Lean already, in substance. The only structural tidy-up with real volume is `O1`/`O5` (dead scripts and shims). Everything else is one-liner residue. No dependency removals are warranted.
