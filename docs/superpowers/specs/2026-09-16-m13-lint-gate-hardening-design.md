# M13 — Lint & Gate Hardening (Cycle 1) — Design

Date: 2026-09-16
Status: Approved in brainstorming (operator). Not yet implemented.
Baseline: `main` at `cdc2a1e` (phases A–D of the AI core replacement merged and pushed)

## Purpose

Three gates exist in this repository. One is soft, one is dishonest, one is missing:

1. **Ruff is a count-file baseline gate, and the file is stale.** `backend/ruff-baseline.txt` says 508; the tree actually produces 489 errors. The gate passes on a number nobody maintains, and it only covers `backend/` — `plugins/` (a first-class code root) is not linted by CI at all.
2. **`alembic check` fails at HEAD** on two model↔DB drifts, so the "no pending model changes without a migration" convention (AGENTS.md) is unenforced and CI does not run it.
3. **CI cannot be trusted to catch any of this**, because it enforces the soft gate and skips `alembic check`.

This cycle makes all three strict: `ruff` exits 0, `alembic check` reports nothing, and CI enforces both. It is the ruff analogue of the mypy cleanup completed 2026-09-10 (`42 → 0` errors, baseline file deleted, gate flipped to hard exit-0).

## Verified premise (measured, not assumed)

All figures below were measured on `main` at `cdc2a1e` with the pinned `ruff==0.16.6`.

- **There is no ruff configuration anywhere in the repository.** No `ruff.toml`, no `.ruff.toml`, and no `[tool.ruff]` section in `backend/pyproject.toml` (the only `pyproject.toml` in the repo).
- **Ruff 0.16.6's built-in default is 413 rules** — `SIM`, `B`, `I`, `UP`, `RUF`, `FURB`, `BLE`, `S`, `ASYNC`, `DTZ` are all enabled by default; `E501` is not. Verified with `ruff check --isolated` (ignores all config files) in a directory with no config, and by resolving `linter.rules.enabled` (413 entries) — identical in `/tmp` and in `backend/`, so the rule set comes from the version, not from any file.
- **Ruff config discovery walks past `backend/pyproject.toml`.** A root-level `ruff.toml` applies to files under `backend/` even though `backend/pyproject.toml` exists without a `[tool.ruff]` section. Verified with a throwaway tree. It applies to `plugins/` as well.
- **Error counts:** `backend/` 489 errors (491 lines in `--output-format=concise`, which is what the CI gate counts): `tests/` 237, `app/` 165, `alembic/` 43, `registry/` 39, `scripts/` 5. `plugins/` 34 (B008 19, TRY004 10, I001 5). `examples/` contains no Python.
- **`alembic check` at HEAD reports exactly three operations** (see Workstream 2 for root causes).
- **All 8 `BLE001` sites are intentional** contract-mandated broad catches (per-item XML parse error collection, plugin-contract probes that must catch anything, image-probe failure caching, `validate_config` error collection, per-plugin isolation). Narrowing them would change failure semantics.

### Fix-wave sizing (measured in a throwaway worktree, then reverted)

| Wave | Action | Errors after |
|---|---|---|
| baseline | — | 489 |
| 1 | add root `ruff.toml` (kills `B008`) | 408 |
| 2 | `ruff check --fix` (303 fixed) | 117 |
| 3 | `ruff check --fix --unsafe-fixes` (79 fixed) | 38 |
| 4 | hand-fix 38 (backend) + 10 (plugins `TRY004`) | 0 |

Wave 2's invocation reports 420 found / 303 fixed / 117 remaining — `--fix` can expose new errors as it edits (e.g. an import removal changes what the next rule sees). Wave numbers are therefore diagnostics, not identities; the acceptance criterion is exit-0, not a count.

## Operator decisions

| Question | Decision |
|---|---|
| Milestone direction | Hardening / cleanup |
| Structure | Two cycles. This is Cycle 1 (mechanical: lint, alembic, CI). Cycle 2 (dev-env, docs/dotenv drift, deferred review minors, UsagePage KPI) gets its own spec |
| How to handle `B008` (81 backend + 19 plugin sites) | Configuration, not hand-editing: `[tool.ruff.lint.flake8-bugbear] extend-immutable-calls` for the FastAPI callables. This is ruff's documented remedy for the false positive |
| How to handle the 9 intentional broad catches (`BLE001`×8 + `S112`×1) | Approach A: surgical inline `# noqa` at those exact lines. Rejected: per-file ignores (imprecise, hides future accidental bare excepts) and narrowing the exceptions (real regression risk in run-abort paths) |
| Where does the ruff config live? | A single new root `ruff.toml` governing `backend/` and `plugins/` |
| Is `plugins/` in the gate? | Yes — it is a first-class code root and today is unlinted by CI |
| Alembic drift resolution | Align the **models to the migrations**. The deployed DB is already correct; migrations are the historical source of truth, so no new migration |
| Gate scope | `ruff check backend plugins` explicitly — not `.`, so `docs/`-adjacent `.md`/`.toml` lint noise stays out |

## Non-goals

- No behaviour changes to application code. This cycle must not alter pipeline, plugin, ingest, QC, export, or API semantics.
- No new feature work, no refactors beyond what a specific rule demands.
- Do not touch the frontend. It has no ruff surface and is otherwise out of scope.
- Do not add rules beyond what the version already enables: no `[lint] select`, no `preview = true`, no `E501`. The gate stays strict because the default is already strict; adding a rule list would be one more thing to maintain.
- Do not reformat with `ruff format`. Only lint fixes.
- Do not "improve" the code while fixing a rule (no drive-by consolidation). A rule fix is the smallest edit that satisfies the rule.

## Workstream 1 — Ruff to zero

### 1.1 Configuration (new file `ruff.toml` at repo root)

```toml
target-version = "py310"

[lint.flake8-bugbear]
extend-immutable-calls = [
  "fastapi.Depends",
  "fastapi.Query",
  "fastapi.Path",
  "fastapi.Body",
  "fastapi.Header",
  "fastapi.Cookie",
  "fastapi.Form",
  "fastapi.File",
]
```

`target-version` makes the resolved version explicit rather than inferred. `extend-immutable-calls` teaches `B008` that these FastAPI callables are safe in argument defaults — the documented fix, and the reason 100 sites stop being errors without a single edit to route signatures.

### 1.2 Fix waves

Executed as separate, reviewable commits (cluster by rule where practical, following the mypy-cleanup precedent), each wave followed by a full `pytest` run:

1. **Config only** — 489 → 408. Pure deletion of false positives.
2. **Safe `ruff --fix`** — the 303 `I001`/`SIM117`/`FURB167`/`F401`/`UP007`/… class. Import sorting dominates at 87 files. Behaviour-neutral by construction.
3. **`ruff --fix --unsafe-fixes`** — 79 fixes, of which 59 are `RUF059` unused-unpacked-variable renames (safe in practice). The remaining ~20 diffs are read by hand before accepting; any that would change behaviour are reverted and hand-fixed instead.
4. **Hand-fixes** — the 48 sites the tooling will not take:

| Rule | Count | Sites | Fix |
|---|---|---|---|
| `SIM117` | 16 | mixed `app/`, `tests/` | merge nested `with` into one statement |
| `BLE001` | 8 | `app/ingest/xml_reader.py`, `app/pipeline/steps.py`, `app/plugins/contract.py`×4, `app/qc/image_probe.py`, `app/routes/pipeline.py` | inline `# noqa: BLE001` — intentional |
| `PLW1510` | 5 | `scripts/verify_m6_gate.py`, `scripts/verify_m9_gate.py`, `tests/test_m1_acceptance.py`, `tests/test_tooling.py`×2 | add explicit `check=` (and decide per site what the run should do on non-zero) |
| `RUF012` | 3 | `tests/` | annotate mutable class attributes `ClassVar` |
| `EXE001` | 2 | `scripts/verify_m6_gate.py`, `scripts/verify_m9_gate.py` | `chmod +x` (the shebang is intentional) |
| `SIM102` | 1 | `registry/parser.py` | merge nested `if` |
| `S112` | 1 | `app/plugins/contract.py` | same site as its `BLE001`; inline `# noqa: S112` |
| `DTZ001` | 1 | `tests/test_session_store.py` | add `tzinfo=timezone.utc` |
| `ASYNC221` | 1 | `tests/test_m1_acceptance.py` | same site as its `PLW1510` |
| `TRY004` | 10 | `plugins/core/{custom_labels,filter,rules}/plugin.py` | `ValueError` → `TypeError` in `validate_config` (invalid *type*) |

### 1.3 `TRY004` carries real risk

Changing `ValueError` → `TypeError` in plugin `validate_config` is the only hand-fix with observable behaviour. `app/plugins/contract.py` catches bare `Exception`, so the contract suite is insensitive to it, but plugin tests may assert `pytest.raises(ValueError)`. The fix wave must grep for those assertions first and update them in the same commit — a silent change here would surface as a plugin rejecting valid config with the wrong exception type.

### 1.4 Gate flip

- Delete `backend/ruff-baseline.txt`.
- The gate becomes `ruff check backend plugins` from the repository root, requiring **exit 0**.

## Workstream 2 — Alembic drift

`alembic check` at HEAD reports three operations. Root causes and fixes:

**`feed_sources.export_token`** — the model declares the column `unique=True`, which SQLAlchemy expresses as a UNIQUE *constraint*. Migration `m8` created a unique *index* named `uq_feed_sources_export_token`. Autogenerate therefore wants to drop the index and add a constraint.

Fix in `app/models/feed_source.py`: drop `unique=True` from the column, add `Index("uq_feed_sources_export_token", "export_token", unique=True)` to `__table_args__`.

**`staging_products.ix_staging_products_removed_purge`** — migration `m5` created a **partial** index (`postgresql_where=sa.text("status = 'removed'")`) that the model never declares, so autogenerate wants to drop it.

Fix in `app/models/staging.py`: add `Index("ix_staging_products_removed_purge", "removed_at", postgresql_where=text("status = 'removed'"))` to `StagingProduct.__table_args__` (requires importing `text`).

No migration is written. The database already has exactly these objects; the models are what drifted.

Acceptance: `uv run alembic check` reports no new upgrade operations at HEAD, against a database built by `alembic upgrade head`.

## Workstream 3 — CI enforcement

`.github/workflows/ci.yml`:

- Replace the "Ruff baseline gate (no new lint errors)" step with `ruff check backend plugins` run from the repository root, failing on any output. Delete the count-vs-file comparison entirely.
- Add an `alembic check` step immediately after "Run alembic migrations", so model↔DB drift fails the build.

The existing steps (registry artifact check, `mypy .` exit-0, `pytest`, `compileall`, frontend test/typecheck/build) are unchanged.

## Workstream 4 — Documentation

Same-commit updates, per the repository's documentation rule:

- `backend/AGENTS.md` — the four places that describe the 508 baseline (gate line, "Python best practices" preamble, the "New code must not add to the 508-error Ruff baseline" paragraph, and the CI gate block). The gate description becomes: `ruff check backend plugins` from the repo root, hard exit-0, no baseline file; pre-existing errors are now zero.
- `docs/decisions.md` — a new dated entry recording the gate flip and the config-based `B008` resolution. History is appended, never rewritten; the older baseline-gate entries stay as written.
- `TODO.md` — cycle log entry; the "Open ops items" line that cites "ruff 508 pre-existing errors" is corrected.
- `docs/decisions/0010-litellm-instructor-ai-transport.md:90` — the phrase "no new `ruff-baseline.txt` exceptions" refers to a file that will no longer exist; adjust the wording.

## Acceptance criteria

1. `ruff check backend plugins` from the repository root prints nothing and exits 0.
2. `backend/ruff-baseline.txt` does not exist and no document instructs anyone to consult it.
3. `uv run alembic check` reports no new upgrade operations at HEAD.
4. `uv run mypy .` remains exit-0.
5. Full backend `pytest` passes, with no test added, removed, or skipped to make a wave green. Frontend untouched.
6. `.github/workflows/ci.yml` enforces both new gates.
7. No application behaviour changed: the diff contains only the rule fixes, the two model alignments, the config, the workflow, and docs.

## Risks and open items

- **382 automated edits across ~300 sites can change behaviour silently.** Mitigated by running the full suite after every wave, by hand-reading the ~20 non-`RUF059` unsafe diffs, and by keeping waves as separate commits so a regression bisects to a wave.
- **`TRY004`'s exception-type change** may break `pytest.raises(ValueError)` assertions (Workstream 1.3).
- **`PLW1510` makes previously-ignored non-zero exit codes explicit.** Each of the 5 sites must choose `check=True` (fail loudly) or `check=False` (keep ignoring) deliberately; `check=True` on a script that intentionally tolerates a non-zero exit would break it.
- **`EXE001` `chmod +x` is a file-mode change** that some tooling normalises; it is invisible in a normal diff but visible to `git diff --summary`.
- **Inline `# noqa` at 9 sites** is a tool directive, not prose, but it is the only textual exception the cycle makes to the repository's no-comments convention. It is deliberate and counted.
- **The gate counts `--output-format=concise` lines today (491) but the error count is 489** — two diagnostics span multiple lines. Irrelevant once the gate is exit-0, but noted so nobody "fixes" the discrepancy later.
- **Stale baseline-derived lore.** `backend/AGENTS.md` and `TODO.md` contain several numeric claims (508, 506, 507, 490) that were already drifting. This cycle makes the point moot rather than reconciling each number; only the live gate description is rewritten.

## Out of scope (Cycle 2, separate spec)

- Dev-env config: `frontend/vite.config.ts` hardcoded `allowedHosts`, `Caddyfile.dev`, `make dev-caddy`, frontend `.env.example`.
- Docs/dotenv drift (including the fact that docs call `Caddyfile.dev` untracked when it is tracked).
- Deferred review minors from the SDD ledger (span-aria-label robustness, enable-error toast wording, prefix-matcher seed assertion, untested donut/funnel data, raw `run.status` bypassing i18n, and the rest).
- UsagePage KPI row (the one spec'd frontend item never built; `/admin/ai/usage/summary` is already live).
