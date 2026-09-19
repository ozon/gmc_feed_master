# Quality-Contract Gaps (T1, T2, T4, T5, T6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the documented quality contract real: enable the documented ruff rules, typecheck `plugins/`, add dependency scanning + audits (upgrading Pillow), gate backend coverage at 85%, and fix the `/chat` README omission.

**Architecture:** Config + CI + docs changes plus 17 behavior-preserving lint fixes, one Pillow major bump, one mypy annotation fix, and a new coverage gate. No application logic changes.

**Tech Stack:** Ruff 0.16.6, mypy, pytest 8.4.2 + pytest-cov 7.1.0, uv, GitHub Actions, Dependabot, pip-audit 2.10.1.

**Spec:** `docs/superpowers/specs/2026-09-19-quality-contract-gaps-design.md`.

## Global Constraints

- No new application dependencies. New **dev/CI** tooling is limited to `pytest-cov==7.1.0` (dev) and `pip-audit==2.10.1` (CI-only via `--with`); both were explicitly approved in the spec.
- The only dependency version change is `pillow>=10.4,<11` → `pillow==12.3.0`.
- Do not add `strict` to mypy. Do not add frontend coverage.
- Run backend commands from `backend/`; DB-backed tests need
  `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/postgres`.
- `uv run ruff check . ../plugins` and `uv run mypy .` must stay exit-0 after every task.
- Commit style: `type(scope): summary`.
- Each task commits its own docs (`docs/decisions.md` / `backend/AGENTS.md`) per the repo's same-commit rule.

---

## File Structure

- `ruff.toml` — enable `[lint] select`.
- `backend/app/access.py`, `backend/app/export/service.py`, `backend/app/ingest/flat_notation.py`, `backend/app/qc/ai_rules.py`, `backend/app/qc/engine.py`, `backend/app/staging/persistence.py`, `backend/tests/test_ai_policy_check.py`, `backend/tests/test_custom_labels_plugin.py`, `backend/tests/test_export_service.py`, `backend/tests/test_rule_ai_step.py`, `plugins/core/category/plugin.py`, `plugins/core/enrichment/plugin.py`, `plugins/core/filter/plugin.py` — the 17 fixes.
- `backend/pyproject.toml` — pillow pin, pytest-cov, coverage config.
- `.github/dependabot.yml` — new.
- `.github/workflows/ci.yml` — plugins mypy, dependency audits, coverage test command.
- `Makefile`, `README.md`, `backend/AGENTS.md`, `docs/decisions.md` — docs.

---

### Task 1: Enable the documented ruff rules and fix the 17 findings (T4)

**Files:**
- Modify: `ruff.toml`
- Modify: 13 source/test/plugin files (listed per step)

- [ ] **Step 1: Enable the rules and observe the failures**

Add to `ruff.toml`:

```toml
[lint]
select = ["E4", "E7", "E9", "F", "B", "C4", "SIM", "I"]
```

Run: `uv run ruff check . ../plugins --output-format concise`
Expected: FAIL, 17 findings (the list fixed below).

- [ ] **Step 2: Fix the B904 sites**

`backend/app/access.py` — two blocks. Add `from None`:

```python
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="client_id must be an integer",
            ) from None
```
```python
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="feed_source_id must be an integer",
        ) from None
```

`plugins/core/filter/plugin.py`:

```python
    try:
        attr, index, sub = _parse_indexed(field)
    except ValueError as exc:
        raise FilterError(f"invalid field path {field!r}") from exc
```

- [ ] **Step 3: Fix the B905 `zip` sites (all `strict=True`)**

`backend/app/ingest/flat_notation.py:167`: `struct = dict(zip(spec.sub_fields, parts, strict=True))`
`backend/app/ingest/flat_notation.py:188`: `result[spec.name] = dict(zip(spec.sub_fields, parts, strict=True))`
`backend/app/qc/ai_rules.py:22`: `by_id = dict(zip(product_ids, products, strict=True))`
`backend/app/qc/engine.py:72`: `for product, product_id in zip(products, product_ids, strict=True):`
`backend/app/staging/persistence.py:83`: `for u, row in zip(group, rows, strict=True):`
`plugins/core/enrichment/plugin.py:136`: `for (product_id, _raw), result in zip(candidates, results, strict=True):`

Each length invariant holds by construction (flat-notation `parts` is padded to `len(spec.sub_fields)`; the others are aligned 1:1).

- [ ] **Step 4: Fix C4, SIM, and the remaining sites**

`backend/app/export/service.py:261` — replace the dict comprehension with `dict(...)`:

```python
            run_ids: dict[int, int | None] = dict(
                (
                    await session.execute(
                        select(ExportVersion.version_number, ExportRun.ingestion_run_id)
                        .join(ExportRun, ExportVersion.export_run_id == ExportRun.id)
                        .where(
                            ExportVersion.feed_source_id == feed_source_id,
                            ExportVersion.version_number.in_([version_number, against]),
                        )
                    )
                ).all()
            )
```

`backend/app/ingest/flat_notation.py:63`:

```python
            prev = seen.get(name, 0)
            kind = "repeated_structured" if prev >= 1 else "structured"
```

`backend/app/ingest/flat_notation.py:196`:

```python
            values = _split_csv_cell(cell) if spec.kind == "repeated_scalar" else cell
```

`backend/tests/test_ai_policy_check.py:91`:

```python
    ai = FakeAi(dict.fromkeys(["p1", "p2", "p3"], real))
```

`backend/tests/test_custom_labels_plugin.py:543`:

```python
        rule = dict(CONFIG["slotRules"][0])
```

`backend/tests/test_export_service.py:188`:

```python
    for title in titles:
```

`backend/tests/test_rule_ai_step.py:160`:

```python
    expected = {k: tuple(v) for k, v in TASK_FIELDS.items()}
    assert plugin._AI_OUTPUT_FIELDS == expected
```

`plugins/core/category/plugin.py` — add `import contextlib` before `import csv`, then:

```python
            except OSError as exc:
                with contextlib.suppress(OSError):
                    tmp.unlink()
                raise HTTPException(
```

- [ ] **Step 5: Verify the gate and tests**

Run: `uv run ruff check . ../plugins`
Expected: `All checks passed!`

Run: `uv run mypy . 2>&1 | tail -1`
Expected: `Success: no issues found`

Run: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/postgres uv run pytest tests/test_ai_policy_check.py tests/test_custom_labels_plugin.py tests/test_export_service.py tests/test_rule_ai_step.py tests/test_ingest_step.py tests/test_qc_engine.py tests/test_staging_step.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ruff.toml backend/app backend/tests plugins
git commit -m "chore(lint): enable documented ruff rule set and fix findings"
```

---

### Task 2: Plugins mypy gate (T5)

**Files:**
- Modify: `plugins/core/filter/plugin.py:185`
- Modify: `.github/workflows/ci.yml`, `Makefile`, `backend/AGENTS.md`, `docs/decisions.md`

- [ ] **Step 1: Confirm the current failure**

Run: `MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins 2>&1 | tail -3`
Expected: FAIL — `plugins/core/filter/plugin.py:192: error: Incompatible return value type (got "JSONResponse", expected "dict[str, int]")`.

- [ ] **Step 2: Fix the annotation**

In `plugins/core/filter/plugin.py`, change the `preview` signature annotation:

```python
        async def preview(
            payload: PreviewRequest,
            user: CurrentUser = Depends(get_current_user),
            db_session: Any = Depends(get_db_session),
        ) -> dict[str, int] | JSONResponse:
```

- [ ] **Step 3: Add the CI gate**

In `.github/workflows/ci.yml`, immediately after the existing `Mypy gate (exit-0)` step, insert:

```yaml
      - name: Mypy gate — plugins (exit-0)
        working-directory: backend
        run: MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins
```

- [ ] **Step 4: Mirror it locally**

In `Makefile`, change `backend-typecheck`:

```make
.PHONY: backend-typecheck
backend-typecheck: ## Type-check backend with mypy
	cd $(BACKEND_DIR) && uv run mypy .
	cd $(BACKEND_DIR) && MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins
```

- [ ] **Step 5: Update AGENTS and record the deferral**

In `backend/AGENTS.md`, under `## CI gate (required, in order)`, add the plugins line (leave the pytest line for Task 4):

```bash
uv run ruff check . ../plugins   # exit-0, hard gate, no baseline file
uv run mypy .            # exit-0, hard gate, no baseline file
MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins   # plugins runtime-contract code
uv run alembic check     # no pending model changes without a migration
uv run pytest --report-log=.report.jsonl   # jq-based failure gate, see Testing above
```

Change the closing sentence from "All four are enforced in CI" to "These gates are enforced in CI".

Then append under the existing `## 2026-09-19` section of `docs/decisions.md`:

```markdown
### Mypy covers plugins; strict deferred (T5)

**Topic:** The runtime-contract plugin code was never typechecked.

**Decision:** CI adds a second mypy invocation (`MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins`); the single `mypy . ../plugins` form cannot be used because every plugin's `plugin.py` maps to a duplicate top-level `plugin` module. The one finding (`filter/plugin.py` preview returning `JSONResponse` under a `dict[str, int]` annotation) is fixed by widening the annotation to `dict[str, int] | JSONResponse`, matching enrichment/custom_labels. `mypy --strict` is **not** enabled: it currently reports 3274 errors across 172 files, tracked as a future cycle.

**Rationale:** The contract code is the highest-value thing to typecheck and was the only completely unchecked surface; the fix is one line. Full strict is a large, mechanical, separate project and bundling it would dwarf this cycle.
```

- [ ] **Step 6: Verify and commit**

Run: `MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins`
Expected: `Success: no issues found` (10 source files).

```bash
git add plugins/core/filter/plugin.py .github/workflows/ci.yml Makefile backend/AGENTS.md docs/decisions.md
git commit -m "build(ci): typecheck plugins with mypy"
```

---

### Task 3: Dependency scanning, pillow upgrade, audit gates (T2)

**Files:**
- Modify: `backend/pyproject.toml`, `.github/workflows/ci.yml`, `docs/decisions.md`
- Create: `.github/dependabot.yml`

- [ ] **Step 1: Bump Pillow and relock**

In `backend/pyproject.toml` change `"pillow>=10.4,<11"` to `"pillow==12.3.0"`. Then:

Run: `uv lock && uv sync --locked`
Expected: lock updates; Pillow 12.3.0 installed.

Run: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/postgres uv run pytest tests/test_image_probe.py tests/test_qc_rules.py tests/test_qc_engine.py -q`
Expected: PASS.

- [ ] **Step 2: Add Dependabot**

Create `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "uv"
    directory: "/backend"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    groups:
      backend-minor-patch:
        update-types: ["minor", "patch"]

  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    groups:
      frontend-minor-patch:
        update-types: ["minor", "patch"]

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
```

- [ ] **Step 3: Add the backend runtime audit gate**

In `.github/workflows/ci.yml`, immediately before the `Run backend tests and compile checks` step, insert:

```yaml
      - name: Dependency audit (runtime)
        working-directory: backend
        run: |
          uv export --frozen --no-dev --format requirements-txt --no-emit-project > /tmp/req.txt
          uv run --with pip-audit==2.10.1 pip-audit -r /tmp/req.txt --ignore-vuln PYSEC-2026-2447
```

- [ ] **Step 4: Add the frontend audit gate**

In the frontend job, immediately after the `Lint and format check` step, insert:

```yaml
      - name: Dependency audit
        working-directory: frontend
        run: npm audit --audit-level=high
```

- [ ] **Step 5: Record the decision**

Append under `## 2026-09-19` in `docs/decisions.md`:

```markdown
### Dependency scanning + Pillow security bump (T2)

**Topic:** No security/dependency scanning existed; the runtime lock carried known CVEs.

**Decision:** Add `.github/dependabot.yml` (uv, npm, github-actions, weekly, minor/patch groups) and two CI audit gates: a runtime-only `pip-audit` (`uv export --frozen --no-dev | pip-audit -r`, tool pinned at `pip-audit==2.10.1`) and `npm audit --audit-level=high`. A runtime audit found 33 CVEs in `pillow 10.4.0`; bump `pillow>=10.4,<11` to `pillow==12.3.0`. `diskcache 5.6.3` has `PYSEC-2026-2447` (pickle deserialization) with **no fixed release**; the audit passes `--ignore-vuln PYSEC-2026-2447` because exploiting it needs write access to the server-local `ai_cache_dir`, which is not an attacker-reachable path here. Dev-only CVEs (e.g. `pytest 8.4.2`) are outside the runtime gate by `--no-dev`.

**Rationale:** `litellm` and the image path are the largest third-party surfaces; a silent vulnerable pin was the biggest unmanaged risk. Runtime-only keeps the gate about the shipped artifact and avoids an unmaintainable dev-dependency whitelist.
```

- [ ] **Step 6: Verify and commit**

Run: `uv export --frozen --no-dev --format requirements-txt --no-emit-project > /tmp/req.txt && uv run --with pip-audit==2.10.1 pip-audit -r /tmp/req.txt --ignore-vuln PYSEC-2026-2447`
Expected: exits 0 (`No known vulnerabilities found`).

Run (from `frontend/`): `npm audit --audit-level=high`
Expected: exits 0.

```bash
git add backend/pyproject.toml backend/uv.lock .github/dependabot.yml .github/workflows/ci.yml docs/decisions.md
git commit -m "build(deps): bump pillow, add dependabot and dependency audits"
```

---

### Task 4: Backend coverage gate (T6)

**Files:**
- Modify: `backend/pyproject.toml`, `.github/workflows/ci.yml`, `backend/AGENTS.md`, `docs/decisions.md`

- [ ] **Step 1: Add pytest-cov and coverage config**

In `backend/pyproject.toml`, add to `[dependency-groups].dev` (after `"pytest-reportlog"`):

```toml
  "pytest-cov==7.1.0",
```

After `[tool.pytest.ini_options]`, add:

```toml
[tool.coverage.run]
source = ["app"]

[tool.coverage.report]
fail_under = 85
```

Run: `uv lock && uv sync --locked`
Expected: `pytest-cov` and `coverage` installed.

- [ ] **Step 2: Gate the CI test step on coverage**

In `.github/workflows/ci.yml`, replace:

```yaml
      - name: Run backend tests and compile checks
        working-directory: backend
        run: uv run pytest -q && uv run python -m compileall app alembic registry
```

with:

```yaml
      - name: Run backend tests with coverage
        working-directory: backend
        run: uv run pytest --cov=app --cov-report=term-missing && uv run python -m compileall app alembic registry
```

- [ ] **Step 3: Reconcile the AGENTS reportlog claim**

Make two edits in `backend/AGENTS.md`.

(a) In the "Test reporting" section, change the `- CI failure gate:` bullet header to a local-triage bullet (keep the jq recipes unchanged):

    - Failure triage (local — CI runs `uv run pytest --cov=app --cov-report=term-missing`; `coverage`'s `fail_under = 85` in `pyproject.toml` is the gate):

(b) In the `## CI gate (required, in order)` block, replace the pytest line:

    uv run pytest --report-log=.report.jsonl   # jq-based failure gate, see Testing above

with:

    uv run pytest --cov=app --cov-report=term-missing   # coverage floor 85 (pyproject)

- [ ] **Step 4: Record the decision**

Append under `## 2026-09-19` in `docs/decisions.md`:

```markdown
### Backend coverage floor at 85% (T6)

**Topic:** Coverage was unmeasured and the documented CI failure gate did not exist.

**Decision:** Add `pytest-cov==7.1.0` to dev deps and a coverage gate: `[tool.coverage.run] source=["app"]`, `[tool.coverage.report] fail_under=85`; CI runs `uv run pytest --cov=app --cov-report=term-missing`. Measured baseline at adoption is 86% (1021 missed / 7197 statements) over `app/`. `backend/AGENTS.md`'s reportlog/jq recipe is reclassified as local failure triage, matching what CI actually runs. Frontend coverage is not added.

**Rationale:** 85% is a floor one point under the measured baseline, so it ratchets without flaking; it makes uncovered critical paths visible. The reportlog jq gate was redundant with pytest's own exit code, so the doc is corrected rather than the CI expanded.
```

- [ ] **Step 5: Verify and commit**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/postgres uv run pytest --cov=app --cov-report=term-missing -q 2>&1 | tail -4`
Expected: all tests pass and the coverage total is ≥85%.

```bash
git add backend/pyproject.toml backend/uv.lock .github/workflows/ci.yml backend/AGENTS.md docs/decisions.md
git commit -m "test(ci): add backend coverage floor of 85 percent"
```

---

### Task 5: `/chat` in the README proxy list (T1)

**Files:**
- Modify: `README.md:64`

- [ ] **Step 1: Add the prefix**

In `README.md`, change the proxy-prefix list to include `/chat`:

```
The Vite development server proxies the backend API prefixes (/admin, /auth, /chat, /clients, /feed-sources, /dashboard, /plugins, /registry, /export, /logs) to the backend at `http://127.0.0.1:8000`, so the documented frontend uses the same-origin API boundary without requiring CORS configuration.
```

- [ ] **Step 2: Verify and commit**

Run: `git grep -n '/chat' README.md Caddyfile Caddyfile.dev frontend/vite.config.ts`
Expected: `/chat` present in all four.

```bash
git add README.md
git commit -m "docs: add /chat to the documented proxy prefixes"
```

---

## Final Verification

- [ ] `cd backend && uv run ruff check . ../plugins` → exit 0.
- [ ] `cd backend && uv run mypy . && MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins` → both clean.
- [ ] `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/postgres uv run pytest --cov=app --cov-report=term-missing` → all pass, coverage ≥85%.
- [ ] `cd backend && uv export --frozen --no-dev --format requirements-txt --no-emit-project > /tmp/req.txt && uv run --with pip-audit==2.10.1 pip-audit -r /tmp/req.txt --ignore-vuln PYSEC-2026-2447` → exit 0.
- [ ] `cd frontend && npm audit --audit-level=high` → exit 0.
- [ ] `uv lock --check` (from `backend/`) → lock consistent.
- [ ] `git grep -n '/chat' README.md` → present.

## Self-Review (completed by plan author)

- **Spec coverage:** T1 → Task 5; T2 → Task 3; T4 → Task 1; T5 → Task 2; T6 → Task 4. T3/T7 documented as already resolved in the spec. All covered.
- **Placeholder scan:** no TBD/TODO; every edit is exact.
- **Type consistency:** `PLUGIN`-era symbols are unrelated; new names (`pytest-cov==7.1.0`, `pip-audit==2.10.1`, `fail_under = 85`, `PYSEC-2026-2447`) are identical across tasks, CI, and decisions text. The `MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins` command is byte-identical in Task 2, Task 2's AGENTS edit, and Final Verification.
