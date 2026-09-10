# Mypy Baseline Cleanup — Design (2026-09-10)

Zeroes the 42-error mypy baseline (TODO 10.1) and flips CI + `backend/AGENTS.md` to a hard exit-0 gate.

## Operator decisions (binding)

1. **Scope:** all 8 documented clusters in one cycle; end state is exit-0 gating, not a smaller baseline.
2. **No `# type: ignore`:** every fix is a real fix (rename, narrow, annotate, pydantic validator, mypy override). No new ignore directives anywhere, and the existing `alembic/env.py:18` directive is removed by the config.py fix that unblocks it.
3. **Verification:** per cluster — `uv run mypy .` count drops by the cluster's size, the touched files' tests pass; full gates at cycle end (backend suite `-n auto`, ruff 506 exact, frontend untouched).
4. **Ruff stays out of scope** (its 506 pre-existing baseline remains a separate ops item).
5. **CI flip:** at zero, ci.yml's mypy step becomes `uv run mypy .` exit-0 (count/baseline compare deleted), `mypy-baseline.txt` is deleted, `backend/docs/mypy-baseline.md` records the flip (kept as historical record), and `backend/AGENTS.md` gates mypy on exit-0 like ruff.
6. **Branch/commits:** branch `mypy-baseline-cleanup`, one commit per cluster, each updating both baseline files (`mypy-baseline.txt` count + doc lines) in the same commit; final commit = gate flip + TODO 10.1 close.
7. **Ordering** (risk/ease, matches error interactions):
   - C1 renames/local-var: `quality.py` (6 — rename reused `result` → `findings_result`; verified 2026-09-10 as pure inference artifact), `staging/persistence.py` (2 — typed local), `registry/parser.py` (2 — tuple/list variable).
   - C2 None-narrowing family (13): `steps.py` (5), `runner.py` (2), `qc/engine.py` (2), `dry_run.py` (1), `scheduler.py` (1), `fetch.py` (1), `xml_reader.py` (1) — shared pattern: assert-narrow or widen signatures where runtime guarantees presence.
   - C3 annotations (7): `pipeline.py` (5), `plugins.py` (2), `dashboard.py` (2) — JSONResponse returns on typed dict routes + `dict(Sequence[Row])` conversion annotations.
   - C4 `config.py` (3): required-field `call-arg` on no-arg `Settings()` construct. Fix pattern: field defaults (`= ""`) + `@model_validator(mode="after")` raising on empty — runtime strictness preserved (env must still provide `SESSION_SECRET`/`INITIAL_USERNAME`/`INITIAL_PASSWORD` per `.env.example`), mypy satisfied; also removes `alembic/env.py:18` ignore since `Settings(database_url=...)` becomes fully-typed.
   - C5 tests (7): `test_export_token_log_redaction.py` (5 — `record.args` `tuple|Mapping|None` indexing: narrow with isinstance), `test_rules_plugin.py` + `test_rules_conditions.py` (1 each — plugin `import` resolution: register plugin modules under `[[tool.mypy.overrides]]` or import via the plugin loader).

## Error handling

- If a cluster fix reveals a *real* latent bug (not an inference artifact), stop, fix the bug properly with its own test, then continue — recorded in the commit message.
- If a fix would require weakening runtime behavior (dropping a check, loosening a type the runtime enforces), that's a design deviation: file it in TODO instead of forcing it.

## Testing

- Per cluster: the touched files' test files green + mypy count check.
- Cycle end: full backend suite (1019 expected — no behavior change intended), ruff exact at 506 (no new), frontend untouched (no frontend files).
- `alembic/env.py` change verified via `uv run mypy alembic/` and one `alembic upgrade head` smoke run against the dev database (config-construction path only).

## Out of scope

- Ruff baseline (separate ops item), frontend, any behavior change to app logic. This cycle is type-hygiene: zero runtime behavior change is the success bar.
