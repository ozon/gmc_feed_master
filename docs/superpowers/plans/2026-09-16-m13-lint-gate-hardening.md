# M13 — Lint & Gate Hardening (Cycle 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ruff` exit 0 over `backend/` + `plugins/`, make `alembic check` clean at HEAD, and have CI enforce both as hard gates.

**Architecture:** Five fix waves (config → safe auto-fix → unsafe auto-fix → hand-fix → plugin hand-fix), then two independent repairs (model↔DB alignment, gate/CI flip), then docs. Every wave is a separate commit followed by the full backend suite. No application behaviour changes.

**Tech Stack:** Python 3.10+, `ruff==0.16.6` (pinned in `backend/pyproject.toml` dev group), `mypy`, `pytest` + `pytest-asyncio` + `pytest-xdist`, Alembic, PostgreSQL, GitHub Actions.

## Global Constraints

- **Ruff version is pinned at `0.16.6`.** Do not upgrade it in this cycle. Its built-in default rule set (413 rules, `E501` off) *is* the gate — do not add `[lint] select`, `preview = true`, or an `E501` ignore.
- **The authoritative lint command runs from `backend/`:**
  ```
  cd backend && uv run ruff check . ../plugins
  ```
  It must exit 0 with no output at the end of this cycle. Do **not** run `ruff check` from the repository root: without the `src` setting added in Task 1, ruff's `I001` (import sorting) resolves first-party modules from the project root, so the repo-root cwd produces ~80 additional phantom `I001` findings on the same files (`backend/app/mapping/matcher.py` is clean from `backend/` and flagged from the root). Task 1's `src = ["backend", "plugins"]` removes that cwd-dependence — verified: the same check returns 424 lines from the repo root and from `backend/`.
- **Baseline for the authoritative command: 520 lines** (491 in `backend/` + 30 in `plugins/`, 1 shared). Task 1's config takes it to **424** (all 100 `B008` findings removed, `I001` re-resolved by the explicit `src`). Intermediate counts after each wave are diagnostics, not targets; the target is exit 0.
- **No behaviour changes.** No drive-by refactors, no reformatting (`ruff format` is not used), no consolidation "while I'm in there". A rule fix is the smallest edit that satisfies the rule.
- **Comments are forbidden in this repo — with one counted exception.** This cycle adds exactly ten `# noqa` directives (eight `BLE001`, one `S112` sharing a line with a `BLE001`, one `DTZ001`) at sites enumerated in Task 4. No other comment may be added.
- **No test may be added, removed, or skipped to make a wave green.** The only test edits permitted are the two assertion updates in Task 5, which pin the new exception type.
- **Run the full backend suite after every wave.** A wave is not done until it passes.
- Environment for the commands below:
  ```bash
  # from backend/
  export DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2- | sed 's#^postgresql://#postgresql+asyncpg://#')"
  export TEST_DATABASE_URL="$DATABASE_URL"
  ```
  `pytest` must run with `DATABASE_URL` unset:
  ```bash
  env -u DATABASE_URL uv run pytest -q
  ```
- Docs are updated in the same commit as the thing they describe (Task 8).

---

### Task 1: Root ruff configuration (eliminate `B008`)

**Files:**
- Create: `ruff.toml` (repository root)

**Interfaces:**
- Consumes: nothing.
- Produces: a root-level ruff config that governs both `backend/` and `plugins/`. Later tasks assume `B008` no longer exists.

- [ ] **Step 1: Create `ruff.toml` at the repository root**

```toml
target-version = "py310"
src = ["backend", "plugins"]

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

`extend-immutable-calls` is ruff's documented remedy for `B008` on FastAPI callables in argument defaults. `src` declares the two source roots explicitly, because a root-level config otherwise makes the repository root ruff's project root and changes `I001`'s first-party detection for `backend/` files (measured: +80 phantom `I001` findings, including `backend/app/mapping/matcher.py`, which is clean under the `backend/` cwd). With `src` set the results are cwd-independent. `backend/pyproject.toml` deliberately stays untouched: ruff walks past a `pyproject.toml` with no `[tool.ruff]` section and finds this file.

- [ ] **Step 2: Verify the config is actually picked up and `B008` is gone**

Run:
```bash
cd backend && uv run ruff check . ../plugins --select B008
```
Expected: `All checks passed!` (all 100 `B008` findings gone).

- [ ] **Step 3: Verify the total count and cwd-independence**

Run:
```bash
cd backend && uv run ruff check . ../plugins --output-format=concise 2>/dev/null | wc -l
cd .. && uv run --project backend ruff check backend plugins --output-format=concise 2>/dev/null | wc -l
```
Expected: both print `424` (was `520`). Identical counts from both cwds prove the `src` setting did its job. `SIM117` (101) and `I001` (87) now dominate what remains.

- [ ] **Step 4: Commit**

```bash
git add ruff.toml
git commit -m "chore(lint): add root ruff config teaching B008 that FastAPI callables are immutable"
```

---

### Task 2: Safe auto-fix wave

**Files:**
- Modify: ~130 files under `backend/` and `plugins/` (mechanical edits only)

**Interfaces:**
- Consumes: Task 1's config.
- Produces: a tree containing no safely-fixable ruff findings.

**Never narrow the rule selection when `RUF100` is involved.** `--select X,Y,RUF100 --fix` replaces the enabled rule set with `X,Y,RUF100`, which makes `RUF100` treat *every other rule's* `noqa` directive as unused and delete it. Measured during execution: that exact mistake deleted six justified `# noqa: UP031` directives in `app/ai/templates.py` (their message strings contain literal `{{%s}}`, which f-strings cannot express without quadrupled braces) and one `# noqa: BLE001` in `app/ai/service.py`. The wave below therefore runs the full default rule set and lets `RUF100` judge each directive against the rules that are actually enabled.

- [ ] **Step 1: Apply all safe fixes with the full rule set**

Run:
```bash
cd backend && uv run ruff check . ../plugins --fix
```
Expected final line: `Found N errors.` with `No fixes available (... --unsafe-fixes option)` — i.e. no safe fixes remain.

- [ ] **Step 2: Confirm only genuinely-unused `noqa` directives were removed**

Run:
```bash
git diff | grep -E "^-.*noqa"
```
Expected: exactly these six lines (or their post-edit equivalents), and nothing else:
```
-                StagingProduct.excluded == False,  # noqa: E712
-from plugin import evaluate_condition  # noqa: E402
-                       user: CurrentUser = Depends(get_current_user),  # noqa: B008 — plugin-route convention (see category plugin)
-                       db_session: Any = Depends(get_db_session)) -> dict[str, Any] | JSONResponse:  # noqa: B008
-                               user: CurrentUser = Depends(get_current_user),  # noqa: B008 — plugin-route convention
-                               db_session: Any = Depends(get_db_session),  # noqa: B008
```
The four `B008` directives became redundant when Task 1's config stopped `B008` firing on FastAPI callables; `E712`/`E402` are not enabled by this rule set. If any `UP031`, `BLE001` or other `noqa` line appears here, the run was narrowed — restore those lines (`git checkout <path>`) and re-run Step 1.

- [ ] **Step 3: Verify the remaining set**

Run:
```bash
cd backend && uv run ruff check . ../plugins --output-format=json 2>/dev/null | python3 -c "
import json,sys,collections
d=json.load(sys.stdin); c=collections.Counter(x['code'] for x in d)
[print(f'  {k:10} {v}') for k,v in c.most_common()]; print('TOTAL',len(d))"
```
Expected `TOTAL 127`: `RUF059` 59, `SIM117` 16, `TRY004` 10, `BLE001` 8, `F841` 8, `RUF015` 6, `PLW1510` 5, `RUF012` 3, `C408` 3, `SIM102` 2, `EXE001` 2, `S112` 1, `PIE810` 1, `SIM401` 1, `ASYNC221` 1, `DTZ001` 1.

- [ ] **Step 4: Run the full suite**

Run:
```bash
cd backend && env -u DATABASE_URL uv run pytest -q
```
Expected: `1295 passed`. A failure means one of the ~300 mechanical edits changed behaviour — find it from the failing test and revert only that hunk (`git checkout -p`).

- [ ] **Step 5: Commit**

```bash
git add -A backend plugins
git commit -m "style(lint): apply safe ruff autofixes (I001, F401, SIM117, FURB167, UP*, ...)"
```

---

### Task 3: Unsafe auto-fix wave

**Files:**
- Modify: a small number of files under `backend/` and `plugins/` (variable renames and similar)

**Interfaces:**
- Consumes: Task 2's tree.
- Produces: a tree with no auto-fixable findings at all.

- [ ] **Step 1: Snapshot the remaining findings**

Run:
```bash
cd backend && uv run ruff check . ../plugins --output-format=concise 2>/dev/null | tee /tmp/ruff-before-unsafe.txt | wc -l
```
Keep `/tmp/ruff-before-unsafe.txt`; Step 4 compares against it.

- [ ] **Step 2: Apply unsafe fixes**

Run:
```bash
cd backend && uv run ruff check . ../plugins --fix --unsafe-fixes
```

- [ ] **Step 3: Read the entire diff before accepting it**

Run:
```bash
git diff -U0 | head -200
git diff --stat
```
Expected shape: overwhelmingly `RUF059` (unused unpacked variables renamed to `_`/`_name`), plus `F841` (unused binding removed — the call is preserved), `C408` (`dict(...)` → `{...}`), `RUF015` (`[...][0]` → `next(...)`), `SIM102` and `PIE810` merges. Read every hunk that is **not** a pure rename. If any hunk changes behaviour (e.g. drops a value that is actually used, changes an exception, changes a default), revert that hunk:
```bash
git checkout -p -- <path>
```
and leave the finding for Task 4 instead.

One `F841` fix leaves a dead expression statement rather than deleting the line: `app/qc/rules.py` had `base = group[0]` (unused) rewritten to a bare `group[0]`. Delete that line entirely — it is the only such artifact.

- [ ] **Step 4: Run the full suite**

Run:
```bash
cd backend && env -u DATABASE_URL uv run pytest -q
```
Expected: PASS. `RUF059` renames are behaviour-neutral; a failure means an unsafe fix was not neutral — revert it and continue.

- [ ] **Step 5: Commit**

```bash
git add -A backend plugins
git commit -m "style(lint): apply unsafe ruff autofixes (RUF059 and friends)"
```

---

### Task 4: Hand-fix the remainder (backend)

**Files:**
- Modify: `app/ingest/xml_reader.py`, `app/pipeline/steps.py`, `app/plugins/contract.py`, `app/qc/image_probe.py`, `app/routes/pipeline.py`, `app/ingest/flat_notation.py`, `scripts/verify_m6_gate.py`, `scripts/verify_m9_gate.py`, `tests/test_m1_acceptance.py`, `tests/test_tooling.py`, `tests/test_custom_labels_delta.py`, `tests/test_export_service.py`, `tests/test_session_store.py`, plus any residual `SIM117` sites

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: `cd backend && uv run ruff check .` exits 0.

**The authoritative worklist is ruff's own output.** Line numbers below were captured before the waves and will have drifted; re-locate each site by its file and rule, never by the line number alone.

- [ ] **Step 1: Get the live worklist**

Run:
```bash
cd backend && uv run ruff check . --output-format=concise
```

- [ ] **Step 2: Merge the remaining nested `with` statements (`SIM117`)**

Ruff auto-fixed the cases it can; the rest need a human because the outer statement has other content (a `try`, a comment-bearing body, or a second statement). Transform:
```python
with outer() as a:
    with inner() as b:
        body()
```
into:
```python
with outer() as a, inner() as b:
    body()
```
Sites seen at the time of writing (re-locate by rule): `app/export/service.py:91`, `app/persistence/sessions.py:28,43,65`, `app/qc/persistence.py:21`, `tests/test_cascade_api.py:89`, `tests/test_dry_run_api.py:178`, `tests/test_export_bound.py:21`, `tests/test_export_service.py:54`, `tests/test_m2_acceptance.py:138`, `tests/test_m5_migration.py:69`, `tests/test_plugins_api.py:364`, `tests/test_plugins_discovery.py:220`, `tests/test_postgres_sessions.py:53`, `tests/test_scheduler_startup.py:35,76`.

- [ ] **Step 3: Add the counted `# noqa` directives**

Append the directive to the end of the existing line — do not otherwise change these lines:

| File | Line content | Directive |
|---|---|---|
| `app/ingest/xml_reader.py:150` | `except Exception as exc:` | `# noqa: BLE001` |
| `app/pipeline/steps.py:263` | `except Exception as exc:` | `# noqa: BLE001` |
| `app/plugins/contract.py:42` | `except Exception:` | `# noqa: BLE001` |
| `app/plugins/contract.py:63` | `except Exception:` | `# noqa: BLE001, S112` |
| `app/plugins/contract.py:81` | `except Exception as exc:` | `# noqa: BLE001` |
| `app/plugins/contract.py:110` | `except Exception:` | `# noqa: BLE001` |
| `app/qc/image_probe.py:62` | `except Exception as e:` | `# noqa: BLE001` |
| `app/routes/pipeline.py:94` | `except Exception as exc:` | `# noqa: BLE001` |
| `tests/test_session_store.py:90` | `InjectableTestClock(datetime(2026, 1, 1))` | `# noqa: DTZ001` |

Each of the eight `BLE001` sites is an intentional broad catch: per-item XML parse error collection, per-product plugin isolation, the plugin contract probes (whose entire job is to catch anything), image-probe failure caching, and `validate_config` error collection. The `DTZ001` site is `test_test_clock_rejects_naive_times` — a naive `datetime` is the value under test, so adding a `tzinfo` would destroy the test.

Example result:
```python
        except Exception as exc:  # noqa: BLE001
```

- [ ] **Step 4: Fix `PLW1510` (5 sites) by making the ignored exit code explicit**

`subprocess.run(...)` calls that inspect `result.returncode` themselves get `check=False`, which is explicit and preserves current behaviour:

| File | Fix |
|---|---|
| `scripts/verify_m6_gate.py:17` | add `check=False` to the `subprocess.run(...)` call (the caller inspects `result.returncode` and exits 1) |
| `scripts/verify_m9_gate.py:17` | same shape as `verify_m6_gate.py` — add `check=False` |
| `tests/test_tooling.py:79` | add `check=False` (assertion on `result.returncode` follows) |
| `tests/test_tooling.py:99` | add `check=False` |
| `tests/test_m1_acceptance.py:127` | add `check=False` |

- [ ] **Step 5: Fix `ASYNC221` by making the test synchronous**

`tests/test_m1_acceptance.py` — `test_m1_registry_artifact_is_fresh` is declared `async def` with `@pytest.mark.asyncio` but never awaits; it only runs a subprocess. Remove the decorator and the `async` keyword:

```python
def test_m1_registry_artifact_is_fresh():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/registry_check.py",
            "--source", "../gmc_def.md",
            "--output", "registry/attributes.json",
            "--check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
```
If `pytest` collects it as a sync test, the `@pytest.mark.asyncio` import remains used by other tests in the file — check before removing any import.

- [ ] **Step 6: Fix `RUF012` with `ClassVar`**

| File | Change |
|---|---|
| `tests/test_custom_labels_delta.py:48,52` | annotate `BASE_CONFIG` and `BASE_DATA` on `TestConfigHashSensitivity` as `ClassVar[dict]` |
| `tests/test_export_service.py:95` | annotate `configuration` on the local `FS` class as `ClassVar[dict]` |

Add `from typing import ClassVar` to each file if absent. Example:
```python
class TestConfigHashSensitivity:
    BASE_CONFIG: ClassVar[dict] = {"slotRules": [
        {"id": "r1", "name": "Mid", "isActive": True, "targetSlot": "custom_label_1",
         "matchField": "id", "valueTemplate": "{brand} - Mid"},
    ]}
    BASE_DATA: ClassVar[dict] = {"slotIds": {"r1": "a\nb"}}
```

- [ ] **Step 7: Fix `EXE001`**

The two gate scripts carry a shebang they cannot honour. Make it true:
```bash
chmod +x backend/scripts/verify_m6_gate.py backend/scripts/verify_m9_gate.py
git add backend/scripts/verify_m6_gate.py backend/scripts/verify_m9_gate.py
```
The resulting commit records the mode change; confirm with `git diff --cached --summary` showing `mode change 100644 => 100755`.

- [ ] **Step 8: Fix any residual `SIM102` / other single findings**

Merge nested `if`s, e.g. in `app/ingest/flat_notation.py`:
```python
if a:
    if b:
        body()
```
becomes
```python
if a and b:
    body()
```
Only do this where the two conditions are side-effect-free and the inner `if` is the only statement in the outer body.

- [ ] **Step 9: Verify `backend/` is clean**

Run:
```bash
cd backend && uv run ruff check .
```
Expected: `All checks passed!`

- [ ] **Step 10: Run the full suite**

Run:
```bash
cd backend && env -u DATABASE_URL uv run pytest -q
```
Expected: PASS, with `test_test_clock_rejects_naive_times` and `test_m1_registry_artifact_is_fresh` specifically still passing.

- [ ] **Step 11: Commit**

```bash
git add -A backend
git commit -m "style(lint): hand-fix remaining backend findings (SIM117, BLE001, PLW1510, RUF012, EXE001, DTZ001)"
```

---

### Task 5: Hand-fix the plugins (`TRY004`)

**Files:**
- Modify: `plugins/core/custom_labels/plugin.py`, `plugins/core/filter/plugin.py`, `plugins/core/rules/plugin.py`
- Modify: `backend/tests/test_rules_plugin.py`, `backend/tests/test_filter_plugin.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `cd backend && uv run ruff check ../plugins` exits 0.

`TRY004` wants `TypeError` when a `raise` exists solely to reject a wrong *type*. Ten sites qualify; all other `ValueError`s in these files are value checks and must not change.

- [ ] **Step 1: Change the ten type checks from `ValueError` to `TypeError`**

`plugins/core/custom_labels/plugin.py`:
```python
    if not isinstance(rules, list):
        raise TypeError("config.slotRules must be an array")
```
```python
        if not isinstance(rule, dict):
            raise TypeError(f"{path}: rule must be an object")
```
```python
        if not isinstance(fallback, str):
            raise TypeError(f"{path}: fallbackTemplate must be a string")
```

`plugins/core/filter/plugin.py`:
```python
    if not isinstance(config, dict):
        raise TypeError("config must be an object")
```
```python
    if not isinstance(conditions, list):
        raise TypeError("config.conditions must be an array")
```

`plugins/core/rules/plugin.py`:
```python
    if not isinstance(node, dict):
        raise TypeError(f"{path}: condition must be an object")
```
```python
    if not isinstance(config, dict):
        raise TypeError("config must be an object")
```
```python
    if not isinstance(rules, list):
        raise TypeError("config.rules must be an array")
```
```python
        if not isinstance(rule, dict):
            raise TypeError(f"{path}: rule must be an object")
```
```python
        if not isinstance(then, list):
            raise TypeError(f"{path}.then must be an array")
```
Lines 170/174/177/179/182/186 of `custom_labels`, 379/381 of `rules`, and the `field` checks in `filter`/`rules` combine an `isinstance` with a value condition (e.g. `if not isinstance(rule_id, str) or not rule_id:`) — leave all of those as `ValueError`.

- [ ] **Step 2: Update the two assertions that now expect `TypeError`**

`backend/tests/test_rules_plugin.py::test_validate_config_rejects_bad_shapes` — the first assertion passes a wrong *type* (`"nope"` instead of a list) and must become `TypeError`; the other four in that function stay `ValueError`:
```python
def test_validate_config_rejects_bad_shapes():
    with pytest.raises(TypeError):
        validate_config({"rules": "nope"})
    with pytest.raises(ValueError):
        validate_config({"rules": [{"no_id": True}]})
    with pytest.raises(ValueError):
        validate_config({"rules": [{"id": "r", "name": "n", "when": {"op": "all"}, "then": [
            {"op": "set", "field": "f"}
        ]}]})
    with pytest.raises(ValueError):
        validate_config({"rules": [{"id": "r", "name": "n", "when": {"op": "nope"}, "then": []}]})
    with pytest.raises(ValueError):
        validate_config({"rules": [{"id": "r", "name": "n", "when": {"op": "and", "children": []}, "then": []}]})
```

`backend/tests/test_filter_plugin.py::test_validate_config_rejects_bad_shapes` — same treatment for the first assertion only:
```python
def test_validate_config_rejects_bad_shapes():
    with pytest.raises(TypeError):
        validate_config({"conditions": "nope"})
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"op": "equals", "arg": "x"}]})
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"field": "", "op": "equals", "arg": "x"}]})
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"field": "f", "op": "nope"}]})
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"field": "f", "op": "equals"}]})
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"field": "f", "op": "exists", "arg": "x"}]})
```

Do not touch `test_validate_config_rejects_empty_find` (`test_rules_plugin.py:71`) or `test_unknown_action_op_raises` (`:96`) — both assert value errors that remain `ValueError`.

- [ ] **Step 3: Confirm the affected suites pass**

Run:
```bash
cd backend && env -u DATABASE_URL uv run pytest -q tests/test_rules_plugin.py tests/test_filter_plugin.py tests/test_custom_labels_plugin.py tests/test_category_plugin.py tests/test_plugin_contract.py
```
Expected: PASS. The contract suite catches bare `Exception`, so it is insensitive to the type change; the plugin suites are the real check.

- [ ] **Step 4: Verify the plugins are clean**

Run:
```bash
cd backend && uv run ruff check ../plugins
```
Expected: `All checks passed!`

- [ ] **Step 5: Run the full suite**

Run:
```bash
cd backend && env -u DATABASE_URL uv run pytest -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A plugins backend/tests
git commit -m "style(lint): prefer TypeError for type checks in plugin validate_config (TRY004)"
```

---

### Task 6: Align the models with the migrations (`alembic check` clean)

**Files:**
- Modify: `backend/app/models/feed_source.py`
- Modify: `backend/app/models/staging.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `alembic check` reports no new upgrade operations at HEAD. No migration file is created.

- [ ] **Step 1: Reproduce the drift**

Run:
```bash
cd backend && export DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2- | sed 's#^postgresql://#postgresql+asyncpg://#')" && uv run alembic check 2>&1 | tail -6
```
Expected: `FAILED: New upgrade operations detected` listing a removed index / added unique constraint on `feed_sources`, and a removed `ix_staging_products_removed_purge` index on `staging_products`.

- [ ] **Step 2: Align `feed_sources`**

In `backend/app/models/feed_source.py`, the column currently reads:
```python
    export_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, default=lambda: secrets.token_urlsafe(32))
```
Change it to drop `unique=True`, and declare the unique index the migration actually created:
```python
    export_token: Mapped[str] = mapped_column(String(64), nullable=False, default=lambda: secrets.token_urlsafe(32))
```
```python
    __table_args__ = (
        Index("ix_feed_sources_client_id", "client_id"),
        Index("uq_feed_sources_export_token", "export_token", unique=True),
    )
```
`Index` is already imported in this module.

- [ ] **Step 3: Align `staging_products`**

In `backend/app/models/staging.py`, `StagingProduct.__table_args__` currently reads:
```python
    __table_args__ = (UniqueConstraint("feed_source_id", "product_id", name="uq_staging_products_source_product"), Index("ix_staging_products_feed_source_id", "feed_source_id"), Index("ix_staging_products_ingestion_run_id", "ingestion_run_id"))
```
Add the partial index migration `m5` created, and import `text`:
```python
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, false, func, text
```
```python
    __table_args__ = (
        UniqueConstraint("feed_source_id", "product_id", name="uq_staging_products_source_product"),
        Index("ix_staging_products_feed_source_id", "feed_source_id"),
        Index("ix_staging_products_ingestion_run_id", "ingestion_run_id"),
        Index(
            "ix_staging_products_removed_purge",
            "removed_at",
            postgresql_where=text("status = 'removed'"),
        ),
    )
```
The `postgresql_where` predicate copies migration `m5`'s definition (`20260826_0001_m5_staging_delta.py`) exactly.

- [ ] **Step 4: Verify the drift is gone**

Run:
```bash
cd backend && uv run alembic check
```
Expected: `No new upgrade operations detected.`

- [ ] **Step 5: Run mypy and the full suite**

Run:
```bash
cd backend && uv run mypy . && env -u DATABASE_URL uv run pytest -q
```
Expected: `Success: no issues found` and PASS. Pay attention to `tests/test_migrations.py`, `tests/test_m1_acceptance.py`, `tests/test_m2_acceptance.py` and `tests/test_models.py`, which assert table/index inventories.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/feed_source.py backend/app/models/staging.py
git commit -m "fix(models): align export_token index and removed_purge partial index with migrations"
```

---

### Task 7: Flip the gate and enforce it in CI

**Files:**
- Delete: `backend/ruff-baseline.txt`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Tasks 1–6 (the tree must already be clean, or CI will fail on this commit).
- Produces: CI gates `ruff` exit-0 and `alembic check`.

- [ ] **Step 1: Confirm both gates pass locally first**

Run:
```bash
cd backend && uv run ruff check . ../plugins && uv run mypy .
cd backend && export DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2- | sed 's#^postgresql://#postgresql+asyncpg://#')" && uv run alembic check
```
Expected: `All checks passed!`, `Success: no issues found`, `No new upgrade operations detected.` Do not proceed until all three are green.

- [ ] **Step 2: Delete the baseline file**

```bash
git rm backend/ruff-baseline.txt
```

- [ ] **Step 3: Replace the ruff gate in `.github/workflows/ci.yml`**

Replace this step:
```yaml
      - name: Ruff baseline gate (no new lint errors)
        working-directory: backend
        run: |
          COUNT=$(uv run ruff check . --output-format=concise 2>/dev/null | wc -l)
          BASELINE=$(cat ruff-baseline.txt)
          echo "ruff errors: $COUNT (baseline $BASELINE)"
          if [ "$COUNT" -gt "$BASELINE" ]; then exit 1; fi
```
with:
```yaml
      - name: Ruff gate (exit-0, backend + plugins)
        working-directory: backend
        run: uv run ruff check . ../plugins
```

- [ ] **Step 4: Add the `alembic check` gate**

Immediately after the existing `Run alembic migrations` step, add:
```yaml
      - name: Alembic drift gate (no pending model changes)
        working-directory: backend
        run: uv run alembic check
```

- [ ] **Step 5: Verify the workflow file is valid and the commands match**

Run:
```bash
cd /home/ozon/gmc_feed_master && uv run --project backend python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text()); print('ci.yml parses')"
```
Expected: `ci.yml parses`

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: enforce ruff exit-0 (backend + plugins) and alembic check"
```

---

### Task 8: Documentation

**Files:**
- Modify: `backend/AGENTS.md`
- Modify: `docs/decisions.md`
- Modify: `TODO.md`
- Modify: `docs/decisions/0010-litellm-instructor-ai-transport.md`

**Interfaces:**
- Consumes: Tasks 1–7 (the gate wording must describe what actually exists).
- Produces: no document instructs anyone to consult a baseline file.

- [ ] **Step 1: Update `backend/AGENTS.md`**

Four places describe the 508 baseline. Rewrite each:

- The `HOW` command line:
  ```
  uv run ruff check .                       # gate: exact count vs backend/ruff-baseline.txt (508), zero new errors
  ```
  becomes
  ```
  uv run ruff check . ../plugins            # gate: exit-0, hard (flipped 2026-09-16, no baseline file)
  ```
- The preamble to "Python best practices (enforced via Ruff, not prose)": change the phrase "so the 508-baseline gate is the actual enforcement mechanism" to "so the `ruff` exit-0 gate is the actual enforcement mechanism".
- The paragraph beginning "New code must not add to the 508-error Ruff baseline; fixing pre-existing baseline errors is a separate, explicitly-scoped cleanup task …": replace it with a statement that the baseline is zero — new code must leave `ruff check . ../plugins` at exit 0, and there is no baseline file to update.
- The "CI gate (required, in order)" block: replace `uv run ruff check .     # exact match against backend/ruff-baseline.txt count (508) …` with `uv run ruff check . ../plugins   # exit-0, hard gate, no baseline file`, and add `uv run alembic check  # no pending model changes` to the list.

- [ ] **Step 2: Append a dated entry to `docs/decisions.md`**

Append (never rewrite history — the older baseline-gate entries stay):
```markdown
### 2026-09-16 — Ruff gate flipped to exit-0; alembic check enforced

**Topic:** Removing the count-file ruff baseline and making model↔DB drift a build failure.

**Decision:** `backend/ruff-baseline.txt` is deleted and `ruff` is now a hard exit-0 gate over `backend/` **and** `plugins/` (`uv run ruff check . ../plugins` from `backend/`). All 489 pre-existing `backend/` findings and 30 `plugins/` findings were fixed across five waves (config → safe autofix → unsafe autofix → hand-fix → plugin hand-fix). `B008` was resolved by configuration (`[tool.ruff.lint.flake8-bugbear] extend-immutable-calls` for the FastAPI callables) rather than by editing ~100 route signatures, which is ruff's documented remedy. `alembic check` is added to CI; the two reported drifts were fixed by aligning the models to the migrations (no new migration), because the migrations created the deployed objects.

**Rationale:** The baseline file had drifted from 508 to 489 and nobody maintained it, so the gate could not fail; and it did not cover `plugins/`, a first-class code root. This mirrors the mypy cleanup of 2026-09-10 (42 → 0, baseline deleted, gate hard). Note for future work: `ruff`'s `I001` resolves first-party modules from the project root, so the authoritative command must run from `backend/` — running from the repository root reports phantom `I001` findings on unchanged files.
```

- [ ] **Step 3: Update `TODO.md`**

- Add a cycle-log entry under `## Cycle log` describing this cycle: waves, counts, the exit-0 flip, the baseline deletion, the model alignment, the CI gates, and the gate commands.
- In "Working notes for the next agent", replace the phrase "Open ops items: ruff 508 pre-existing errors (pinned in the backend dev group + count-file gate `backend/ruff-baseline.txt`; zero-new-in-touched-files convention holds)" with a statement that ruff is now exit-0 with no baseline file, leaving only the vite/Caddyfile.dev dev-env item open (deferred to cycle 2).

- [ ] **Step 4: Fix the stale reference in ADR-0010**

`docs/decisions/0010-litellm-instructor-ai-transport.md` line ~90 says "no new `ruff-baseline.txt` exceptions". The file no longer exists; reword to "no new ruff findings (the gate is exit-0)".

- [ ] **Step 5: Verify no operative document references the deleted file**

Run:
```bash
cd /home/ozon/gmc_feed_master && rg -n "ruff-baseline" backend/AGENTS.md AGENTS.md .github/ frontend/ docs/decisions/0010-litellm-instructor-ai-transport.md
```
Expected: no matches.

Historical records are exempt and must not be rewritten: prior cycle-log entries in `TODO.md`, the older dated entries in `docs/decisions.md` (the repo's rule is *append, never rewrite history*), `backend/docs/mypy-baseline.md` (itself a closed historical record), and anything under `docs/superpowers/**` / `.superpowers/**`.

- [ ] **Step 6: Commit**

```bash
git add backend/AGENTS.md docs/decisions.md TODO.md docs/decisions/0010-litellm-instructor-ai-transport.md
git commit -m "docs: ruff exit-0 gate, baseline removal, and alembic check"
```

---

## Final verification

- [ ] **Gate 1 — lint:** `cd backend && uv run ruff check . ../plugins` → `All checks passed!`
- [ ] **Gate 2 — types:** `cd backend && uv run mypy .` → `Success: no issues found`
- [ ] **Gate 3 — schema:** `cd backend && uv run alembic check` → `No new upgrade operations detected.`
- [ ] **Gate 4 — tests:** `cd backend && env -u DATABASE_URL uv run pytest -q` → PASS
- [ ] **Gate 5 — baseline file gone:** `test ! -e backend/ruff-baseline.txt`
- [ ] **Gate 6 — frontend untouched:** `git diff --stat <cycle-start>..HEAD -- frontend` → empty
- [ ] **Gate 7 — no behaviour change:** `git log --oneline <cycle-start>..HEAD` shows only lint/model/CI/docs commits, and `git diff <cycle-start>..HEAD -- backend/app` contains no logic changes beyond the `TRY004` type checks and the five `check=False` additions.

## Self-review notes

- Spec coverage: Workstream 1 → Tasks 1–5; Workstream 2 → Task 6; Workstream 3 → Task 7; Workstream 4 → Task 8. The spec's "no other config" constraint is honoured (Task 1 adds no `select`).
- Measurement caveat carried into the plan: all counts use the `backend/` cwd form; the spec's per-area figures (489 backend / 34 plugins) were captured per-invocation and are consistent with the 520-line combined baseline used here.
- Two spec claims were refined by closer reading during planning: the `SIM102` site is `app/ingest/flat_notation.py` (not `registry/parser.py`), and `DTZ001` at `tests/test_session_store.py:90` must be `noqa`+left naive (the naive datetime is the value under test), not fixed with a `tzinfo`. Both are reflected in Task 4.
