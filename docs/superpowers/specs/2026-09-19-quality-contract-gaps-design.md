# Quality-Contract Gaps (T1, T2, T4, T5, T6) — Design

**Date:** 2026-09-19
**Status:** Approved (design), pending implementation plan
**Scope:** Tooling/CI/docs only (plus one dependency bump and 17 tiny lint fixes). Closes `T1`, `T2`, `T4`, `T5`, `T6` from `docs/reports/2026-09-17-04-tooling-testing.md`. `T3` and `T7` are already resolved (oxlint/oxfmt CI gate; production compose + runbook) and are explicitly out of scope, as are `T8`–`T12`.

## Problem

The 2026-09-17 tooling review found the documented quality contract overstates the actual configuration:

- **T1** — `/chat` was missing from the API proxy prefix list. Already fixed in `Caddyfile`, `Caddyfile.dev`, and `frontend/vite.config.ts`; `README.md:64` still omits it.
- **T2** — no security/dependency scanning: no `.github/dependabot.yml`, no `pip-audit`, no `npm audit` in CI. A runtime audit of the locked env finds **33 vulnerabilities in `pillow 10.4.0`** (fix available) and **2 in `diskcache 5.6.3`** (no upstream fix).
- **T4** — `backend/AGENTS.md` claims B006/B008, C4, SIM113, I, and E711/E712 are "enforced via Ruff", but `ruff.toml` has no rule selection, so only Ruff's built-in default set runs and the configured `extend-immutable-calls` is inert. The documented families (`--select B,C4,SIM,I,E711,E712`) find **18 latent violations**.
- **T5** — mypy is non-strict and CI runs `mypy .` from `backend/` only, so `plugins/` (the runtime-contract code) is never typechecked. Full `--strict` is **3274 errors in 172 files**.
- **T6** — no coverage tooling at all; `backend/AGENTS.md` documents a jq/`--report-log` CI failure gate that CI does not actually run (`ci.yml` runs plain `uv run pytest -q`).

## Decision

| Topic | Decision |
|-------|----------|
| T1 | Add `/chat` to the `README.md` proxy-prefix list (one line) |
| T2 scanning | `.github/dependabot.yml` (uv, npm, github-actions, weekly) + CI `pip-audit` (runtime deps) + `npm audit` |
| T2 pillow | `pillow>=10.4,<11` → `pillow==12.3.0` (fixes all 33) |
| T2 diskcache | Runtime audit runs `--ignore-vuln PYSEC-2026-2447`, documented in `docs/decisions.md` (no upstream fix; cache dir is server-local) |
| T4 | `ruff.toml` `[lint] extend-select = ["B","C4","SIM","I","E711","E712"]`; fix all 18 |
| T5 | Typecheck `plugins/` via a second mypy invocation; fix its 1 error; **defer `strict`** |
| T6 | `pytest-cov` dev dep; `[tool.coverage]` source `app/`, `fail_under = 85`; CI runs the coverage command; fix the AGENTS reportlog claim |
| T3 / T7 | Out of scope — already resolved |

Rationale: these are the cheap, high-credibility fixes — restore the gate the docs already advertise (T4), typecheck the contract code (T5), make coverage and dependency risk visible (T2/T6), and fix the one user-facing doc drift (T1). Full mypy strict and frontend coverage are real but disproportionate; both are deferred explicitly rather than silently dropped.

## Design

### 1. T1 — README proxy list

`README.md:64` lists `(/admin, /auth, /health, /clients, /feed-sources, /dashboard, /plugins, /registry, /export, /logs)`. Add `/chat` (alphabetically after `/auth`).

### 2. T2 — dependency scanning and pillow bump

**Pillow.** `backend/pyproject.toml`: `"pillow>=10.4,<11"` → `"pillow==12.3.0"`. Regenerate the lock (`uv lock`). The only production use is `Image.open(BytesIO(body)).size` in `app/qc/image_probe.py` plus a test fixture (`Image.new(...).save(...)`); both are stable across 10→12.

**Dependabot.** New `.github/dependabot.yml`, `version: 2`, weekly:
- `uv` at `/backend` (pip ecosystem equivalent for uv projects)
- `npm` at `/frontend`
- `github-actions` at `/`
- `open-pull-requests-limit: 5` and groups for minor/patch updates to keep PR noise low.

**CI audit, backend** (`.github/workflows/ci.yml`, backend job, after the mypy gate):
```yaml
      - name: Dependency audit (runtime)
        working-directory: backend
        run: |
          uv export --frozen --no-dev --format requirements-txt --no-emit-project > /tmp/req.txt
          uv run --with pip-audit==2.10.1 pip-audit -r /tmp/req.txt --ignore-vuln PYSEC-2026-2447
```
Dev-only CVEs (e.g. `pytest 8.4.2`) are intentionally excluded by `--no-dev`; the gate is about the shipped surface. `pip-audit` is pinned in the `--with` spec so the tool itself cannot drift.

**CI audit, frontend** (frontend job):
```yaml
      - name: Dependency audit
        working-directory: frontend
        run: npm audit --audit-level=high
```

**Decisions.** Append a dated `docs/decisions.md` entry: pillow 10→12 for the 33 CVEs; diskcache `PYSEC-2026-2447` accepted because no fixed release exists and exploiting it requires write access to the server-local `ai_cache_dir`; dev-env CVEs are out of the runtime gate.

### 3. T4 — enable the documented ruff rules and fix 17

`ruff.toml` gains:
```toml
[lint]
extend-select = ["B", "C4", "SIM", "I", "E711", "E712"]
```
(`extend-select` adds the documented families on top of Ruff's built-in defaults. The original review recommended an explicit `select = ["E4","E7","E9","F",...]`, but Ruff 0.16's actual default set is narrower than that list, so the explicit form would additionally pull in unrelated `E402`/`E702` findings in tests. `extend-select` enforces exactly what `backend/AGENTS.md` claims and nothing more.) Enabling `B` activates the already-present `[lint.flake8-bugbear] extend-immutable-calls`; the survey shows zero B008 findings, so FastAPI `Depends(...)` defaults are unaffected. `I` has zero current findings, so no import churn.

The 18 fixes, all behavior-preserving:

| File:line | Rule | Fix |
|-----------|------|-----|
| `app/access.py:100`, `:115` | B904 | `raise ... from err` / `from None` |
| `app/export/service.py:261` | C416 | narrow `# noqa: C416` with a reason — SQLAlchemy `Row` is not typed as `Iterable[tuple]`, so the `dict(rows)` rewrite fails mypy |
| `app/ingest/flat_notation.py:63`, `:196` | SIM108 | ternary expressions |
| `app/ingest/flat_notation.py:167`, `:188` | B905 | `zip(..., strict=True)` — `parts` is padded to `expected = len(spec.sub_fields)`, so lengths are equal by construction |
| `app/qc/ai_rules.py:22` | B905 | `zip(..., strict=True)` (aligned lists) |
| `app/qc/engine.py:72` | B905 | `zip(..., strict=True)` (aligned lists) |
| `app/staging/persistence.py:83` | B905 | `zip(..., strict=True)` (`rows` is `add_all(group)`'s result) |
| `app/staging/persistence.py:204` | E712 | `StagingProduct.excluded.is_(False)` (SQLAlchemy needs `.is_`, not `not`) |
| `tests/test_ai_policy_check.py:91` | C420 | `dict.fromkeys(...)` |
| `tests/test_custom_labels_plugin.py:543` | C416 | plain `dict(...)` |
| `tests/test_export_service.py:188` | B007 | drop the unused `enumerate` index (`for title in titles:`) |
| `tests/test_rule_ai_step.py:160` | SIM300 | bind the comprehension to a local and compare two names (`expected = {...}; assert plugin._AI_OUTPUT_FIELDS == expected`) — ruff's auto-fix only swaps operands |
| `plugins/core/category/plugin.py:458` | SIM105 | `contextlib.suppress(OSError)` |
| `plugins/core/enrichment/plugin.py:136` | B905 | `zip(..., strict=True)` (results are generated 1:1 from candidates) |
| `plugins/core/filter/plugin.py:63` | B904 | `raise ... from exc` |

Each B905 `strict=True` is justified by a length invariant; where a mismatch is impossible by construction this converts a silent truncation into a loud error (the intent of B905). No site legitimately needs `strict=False`.

### 4. T5 — typecheck plugins, defer strict

**Fix.** `plugins/core/filter/plugin.py` `preview(...)` is annotated `-> dict[str, int]` but returns a `JSONResponse` on validation failure (line 192). Change the annotation to `dict[str, int] | JSONResponse`, matching the established `dict[str, Any] | JSONResponse` pattern in `plugins/core/enrichment/plugin.py` and `plugins/core/custom_labels/plugin.py`.

**CI/local invocation.** A separate mypy run (running `mypy . ../plugins` in one invocation fails resolution: every plugin's `plugin.py` maps to a duplicate top-level `plugin` module):
```yaml
      - name: Mypy gate — plugins (exit-0)
        working-directory: backend
        run: MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins
```
`Makefile` `backend-typecheck` runs both invocations so local and CI match.

**Strict deferred.** `mypy --strict` currently reports 3274 errors across 172 files. Do not add strict flags. Record the deferral in `docs/decisions.md` with the count so it is a tracked future cycle, not a silent omission.

### 5. T6 — backend coverage gate

**Dependency.** Add `pytest-cov==7.1.0` to `[dependency-groups].dev` (it pulls `coverage` transitively; pin only the direct tool).

**Config** (`backend/pyproject.toml`):
```toml
[tool.coverage.run]
source = ["app"]

[tool.coverage.report]
fail_under = 85
```
Baseline measured this cycle: **86%** (1021 missed / 7197 statements) over `app/`. 85 leaves ~1 point of headroom; it is a floor, not a target.

**CI** (backend job): replace `uv run pytest -q` with
```yaml
      - name: Run backend tests with coverage
        working-directory: backend
        run: uv run pytest --cov=app --cov-report=term-missing
```
`coverage`'s `fail_under` makes the step exit non-zero below 85. `--cov` stays out of `addopts` so local `pytest` remains fast; CI sets it explicitly. pytest-cov is xdist-aware, so `addopts = "-n auto"` is unchanged.

**Doc reconcile.** `backend/AGENTS.md`'s "Test reporting" section claims a jq/`--report-log` failure gate is "enforced in CI". Rephrase it: the jq recipes are local triage for the large, growing suite; CI runs `uv run pytest --cov=app --cov-report=term-missing`. The `--report-log=.report.jsonl` guidance itself stays.

## Verification

- `uv lock --check` passes; `grep -n 'pillow' backend/pyproject.toml` shows `==12.3.0`.
- `uv run --with pip-audit==2.10.1 pip-audit -r <runtime reqs> --ignore-vuln PYSEC-2026-2447` exits 0.
- `npm audit --audit-level=high` (from `frontend/`) exits 0.
- `uv run ruff check . ../plugins` exits 0 with the new `select` (no findings).
- `MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins` exits 0; `uv run mypy .` stays clean.
- `uv run pytest --cov=app --cov-report=term-missing` passes all tests and reports ≥85%.
- Image-probe tests pass under Pillow 12.
- `git grep -n '/chat' README.md` shows it in the proxy list.

## Docs (same commits)

- `README.md` — proxy list gains `/chat`.
- `backend/AGENTS.md` — CI gate list gains the plugins mypy run and the coverage command; reportlog section rephrased as local triage.
- `docs/decisions.md` — dated entry: pillow 10→12 (+ CVEs), diskcache ignore rationale, mypy-plugins gate, strict deferral (3274), coverage floor 85 at 86% baseline, dependabot/audits.
- `Makefile` — `backend-typecheck` runs the plugins mypy invocation too.

## Risks and non-goals

- **Pillow major bump (10→12).** Only `.open().size` and a test fixture are used; covered by `tests/test_image_probe.py`. If PIL ever gains heavier usage, revisit.
- **`pip-audit` fetches its advisory DB over the network in CI.** Pinned tool version; a transient network failure fails the job (acceptable, same as other network CI steps).
- **Dependabot `uv` ecosystem.** If GitHub rejects the `uv` ecosystem for this repo, fall back to `pip` at `/backend` (the lock is uv, but `pip` still surfaces `pyproject.toml` bumps). Validate on the first run.
- **Coverage flakiness.** A floor 1 point under the measured baseline tolerates normal test-count movement; if legitimate coverage drops below 85, the PR must add tests, not lower the bar (lowering requires a `docs/decisions.md` note).
- **Non-goals:** mypy strict, frontend coverage, `T8`–`T12` (stale instruction docs, duplicate `examples/feed.xml`, `DATABASE_URL` dialect, CI double-run, pinning ranges), and any application behavior change beyond the Pillow upgrade.

## References

- `docs/reports/2026-09-17-04-tooling-testing.md` findings `T1`, `T2`, `T4`, `T5`, `T6`.
- `ruff.toml`, `backend/pyproject.toml`, `.github/workflows/ci.yml`, `Makefile`, `README.md`, `backend/AGENTS.md`.
- `docs/superpowers/specs/2026-09-18-frontend-oxc-lint-format-design.md` (T3, already shipped); `docs/prod_deployment.md` (T7, already shipped).
