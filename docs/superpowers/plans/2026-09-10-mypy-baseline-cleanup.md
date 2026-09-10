# Mypy Baseline Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zero the 42-error mypy baseline and flip CI + `backend/AGENTS.md` to a hard exit-0 mypy gate (TODO 10.1).

**Architecture:** Five cluster commits (rename/local-var → None-narrowing → route annotations → pydantic-mypy plugin → test typing), each verified by mypy count + that cluster's tests, then a final commit flipping the CI gate to exit-0, deleting `mypy-baseline.txt`, and closing TODO 10.1. Every fix is a real fix — no `# type: ignore` anywhere.

**Tech Stack:** Python 3.10+, mypy 2.3.1 (`[tool.mypy]` in `backend/pyproject.toml`), pydantic v2 + `pydantic.mypy` plugin (already installed with pydantic-settings), pytest, SQLAlchemy 2.0.

## Global Constraints

- Working directory for every command: `/home/ozon/gmc_feed_master/backend` unless noted.
- Backend tests need the test database URL first: `export $(grep -E '^TEST_DATABASE_URL=' ../.env | xargs)`.
- No `# type: ignore` directives anywhere in this cycle (operator decision 2). The existing `alembic/env.py:18` directive is REMOVED by Task 4.
- Zero runtime behavior change is the success bar. If a fix would change behavior, stop and record a deviation in the commit message + TODO instead of forcing it.
- After every cluster commit: `uv run mypy . 2>&1 | grep -c ': error:'` must equal the expected post-commit count (43→36→23→14→11→0 minus per-task numbers below — see each task).
- Both baseline files update in the SAME commit as their fixes: `mypy-baseline.txt` (bare count number) and the removed lines from `backend/docs/mypy-baseline.md`'s "## Baseline" sorted list.
- Ruff must stay at 506 (`uv run ruff check . 2>&1 | grep '^Found'`) — zero new.
- Frontend is untouched this cycle (no frontend files, no frontend gates except the final full-suite sanity in Task 6).
- No code comments in code changes (house convention).
- Expected error-count trajectory: start 42 → Task 1: 32 → Task 2: 19 → Task 3: 10 → Task 4: 7 → Task 5: 0.

---

### Task 1: C1 — renames and typed locals (10 errors)

**Files:**
- Modify: `app/routes/quality.py:47-50` (rename reused `result`)
- Modify: `app/staging/persistence.py:124-128` (typed local for the Result)
- Modify: `registry/parser.py:294-296` (list variable instead of tuple-typed)
- Modify: `mypy-baseline.txt`, `backend/docs/mypy-baseline.md`

**Interfaces:**
- Consumes: none (pure refactor, no API changes).
- Produces: none (later tasks unaffected; `quality.py` route behavior unchanged).

- [ ] **Step 1: quality.py — rename the second `result` binding**

`app/routes/quality.py` lines 47-50 currently:

```python
    result = await session.execute(
        select(QualityFinding)
        .where(QualityFinding.feed_source_id == feed_source_id)
        .order_by(QualityFinding.id)
    )
    rows = list(result.scalars().all())
```

Change to:

```python
    findings_result = await session.execute(
        select(QualityFinding)
        .where(QualityFinding.feed_source_id == feed_source_id)
        .order_by(QualityFinding.id)
    )
    rows = list(findings_result.scalars().all())
```

This resolves all 6 `attr-defined` errors (mypy was joining `row` with the earlier `ExportRun` binding through the shared `result` name).

- [ ] **Step 2: persistence.py — typed local for the Result**

`app/staging/persistence.py` lines 124-128 currently:

```python
                rows = await session.execute(
                    select(StagingProduct.id, StagingProduct.product_id)
                    .where(StagingProduct.id.in_(group))
                )
                for pk, product_id in rows.all():
                    pk_map[product_id] = pk
```

Earlier in the function (around line 90), the name `rows` is a `list[StagingProduct]` — mypy infers the variable from first use. Rename the later binding to a typed local:

```python
                reactivation_rows = await session.execute(
                    select(StagingProduct.id, StagingProduct.product_id)
                    .where(StagingProduct.id.in_(group))
                )
                for pk, product_id in reactivation_rows.all():
                    pk_map[product_id] = pk
```

- [ ] **Step 3: registry/parser.py — list-typed variable**

`registry/parser.py` lines 294-296 currently:

```python
            fields = []
            for raw_name, spec in _object_parts(object_match.group(0)):
                fields.append(_field_spec(raw_name, spec, description, line) if spec else SubField(raw_name, "String", RequirementStatus.OPTIONAL, _constraints(description)[0]))
```

Wait — this section already uses `fields = []` (list). The errors at 294-296 concern the OTHER binding: find the `tuple[SubField, SubField]` variable. In `registry/parser.py`, grep for the ambiguous-order branch around line 294:

```bash
grep -n "pair" registry/parser.py
```

The variable (call it what grep shows, commonly `pair = (fld_a, fld_b)`) is later reassigned `pair = [...]` (a list) and `pair.append(...)` is called on it. Change the initial binding from tuple to list so all uses type-check: `pair = [fld_a, fld_b]` (preserve element order; downstream only indexes/iterates — verify by grepping call sites of the variable).

If the two uses are `pair[0]`/`pair[1]` indexing only, the list change is safe. If a tuple is unpacked somewhere (`a, b = pair`), list also works. Confirm with:

```bash
grep -n "<varname>" registry/parser.py
```

and check every hit before changing.

- [ ] **Step 4: Verify mypy count = 32**

```bash
uv run mypy . 2>&1 | grep -c ': error:'
```

Expected: `32`

- [ ] **Step 5: Run the affected tests**

```bash
export $(grep -E '^TEST_DATABASE_URL=' ../.env | xargs)
uv run pytest tests/test_quality_api.py tests/test_staging_delta.py tests/test_staging_purge.py tests/test_registry_parser.py tests/test_reconcile.py -q
```

Expected: all pass (baseline green; zero behavior change).

- [ ] **Step 6: Update baseline files**

`mypy-baseline.txt`: content becomes `32`.

`backend/docs/mypy-baseline.md`: delete the removed lines from the "## Baseline" list (the 6 quality.py, 2 persistence.py, 2 parser.py lines); update the "Notes on clusters" entries for quality.py, staging/persistence.py, registry/parser.py to past tense / removed status (or drop those bullets).

Doc edits are advisory on style; keep them minimal — remove fixed lines from the Baseline list, strike or drop the three cluster notes.

- [ ] **Step 7: Commit**

```bash
git add app/routes/quality.py app/staging/persistence.py registry/parser.py mypy-baseline.txt docs/mypy-baseline.md
git commit -m "refactor(types): disambiguate reused bindings (C1: quality, persistence, parser)

- quality.py: rename second 'result' to 'findings_result' — resolves the
  ExportRun/QualityFinding inference artifact (6 attr-defined)
- staging/persistence.py: 'rows' Result local renamed 'reactivation_rows'
  so it no longer collides with the earlier list[StagingProduct] binding
- registry/parser.py: ambiguous-pair variable typed as list, not tuple

mypy: 42 -> 32. No behavior change."
```

---

### Task 2: C2 — None-narrowing family (13 errors)

**Files:**
- Modify: `app/pipeline/steps.py:293` (arg 1 to PluginOutcome), `steps.py:371-382` (QcContext + rule lists)
- Modify: `app/pipeline/runner.py:120,144` (run: IngestionRun | None assignment)
- Modify: `app/qc/engine.py:91,93` (rule loop variable reuse)
- Modify: `app/pipeline/dry_run.py:94` (QcContext arg type)
- Modify: `app/pipeline/scheduler.py:53` (validate_cron arg)
- Modify: `app/ingest/fetch.py:28` (client: AsyncClient | None)
- Modify: `app/ingest/xml_reader.py:58` (child.text.strip() on None)
- Modify: `mypy-baseline.txt`, `backend/docs/mypy-baseline.md`

**Interfaces:**
- Consumes: none.
- Produces: none (all internal).

- [ ] **Step 1: steps.py:293 — narrow the PluginOutcome action**

Current (line ~293, inside the plugin drop branch):

```python
                if pk is not None:
                    outcomes.append(PluginOutcome(pid, pk, "dropped", None))
```

Wait — the error says `Argument 1 to "PluginOutcome" has incompatible type "Any | None"; expected "str"` — argument 1 is `pid` (from `pk` context: `pk = pks.get(pid) if isinstance(pid, str) else None`). `pid` comes from a `str | None`-ish source. Fix by guarding on `pid` too. Check the enclosing loop; the guard becomes:

```python
                if pk is not None and pid is not None:
                    outcomes.append(PluginOutcome(pid, pk, "dropped", None))
```

But verify the loop shape first — read `app/pipeline/steps.py` lines 270-300 before editing. If `pid` is guaranteed non-None at this point (e.g. loop iterates `for pid in dropped_ids` typed `str`), the clean fix is a narrowed local:

```python
                product_id = pid if isinstance(pid, str) else ""
```

and use `product_id` in the PluginOutcome call. Pick whichever matches the real code; do not change drop semantics (outcome recorded identically).

- [ ] **Step 2: steps.py:371-382 — QcContext and rule-list typing**

`image_probe=self._image_probe` errors because `self._image_probe` is `ImageProbe | None` while `QcContext.image_probe: ImageProbe`. Check the class constructor: `QualityCheckStep.__init__` receives an optional probe. The runtime invariant: the step receives a probe from the runner which always passes one. Fix by widening `QcContext.image_probe` to `ImageProbe | None`:

In `app/qc/engine.py` (QcContext dataclass):

```python
    image_probe: ImageProbe | None
```

and narrow at use: `run_engine`'s rule implementations call `ctx.image_probe.probe(...)`. Grep for `image_probe` in `app/qc/rules.py`:

```bash
grep -n "image_probe" app/qc/rules.py
```

At each call site the code must handle `None` (skip the rule with a warning-finding? No — do not change behavior). The real runtime contract (verified from runner wiring): the runner always passes a real probe; `None` never occurs in practice (steps.py passes `self._image_probe` which is required at construction). The minimal fix that preserves this: keep `QcContext.image_probe: ImageProbe` and instead fix the type of `QualityCheckStep.__init__`'s parameter and attribute:

```bash
grep -n "_image_probe\|image_probe" app/pipeline/steps.py | head
```

If the attribute is declared `ImageProbe | None`, narrow via assert in the QC step body where the context is built:

```python
        probe = self._image_probe
        assert probe is not None
        qc_ctx = QcContext(
            ...,
            image_probe=probe,
            previous_export_run=previous_export_run,
        )
```

`assert` is allowed (it's a real narrowing, not an ignore) — but house rule "no comments in code" doesn't ban asserts; only add if the constructor truly guarantees non-None. Read the constructor first; if the parameter is typed `ImageProbe | None = None`, then `assert` masks a design looseness — prefer typing the constructor parameter as required `ImageProbe` (no default) IF no caller passes None. Grep callers:

```bash
grep -rn "QualityCheckStep(" app tests --include="*.py"
```

If all callers pass a probe, change the signature to required `ImageProbe` and remove the `| None` from the attribute — a real fix with zero behavior change.

- [ ] **Step 3: steps.py:372 + dry_run.py:94 — ExportRun protocol mismatch**

Both errors: `Argument "previous_export_run" to "QcContext" has incompatible type "app.models.export.ExportRun | None"; expected "app.qc.engine.ExportRun | None"`. The engine declares a local Protocol `ExportRun` (structural type) and the ORM model satisfies it structurally, but mypy nominal-matching complains. Real fix: import the engine Protocol in steps.py/dry_run.py contexts or annotate the local as the protocol type. In both files, annotate:

`app/pipeline/steps.py` (where `previous_export_run` is fetched):

```python
from ..qc.engine import ImageProbe, ExportRun as ExportRunProtocol
...
        previous_export_run: ExportRunProtocol | None = (await session.execute(...)).scalar_one_or_none()
```

Wait — the return is the ORM class. Better: change the engine protocol's consumer instead. Simplest real fix: in `app/qc/engine.py`, replace the local `ExportRun` Protocol with an import of the ORM model:

```python
from ..models.export import ExportRun
```

and delete the Protocol class (lines ~58-63). Check what the Protocol defines (fields feed_source_id, ingestion_run_id, product_count, ...finding counts) — the ORM model has all of these as mapped columns, so the Protocol is redundant. Grep for `ExportRun` imports of the engine version:

```bash
grep -rn "from ..qc.engine import\|from app.qc.engine import" app tests --include="*.py"
```

If only steps.py/dry_run.py import the engine's ExportRun (or none do — the Protocol is engine-internal), deleting the Protocol and importing the ORM model closes both errors with zero behavior change. The `from __future__ import annotations` in engine.py keeps the dataclass field annotation lazy so the import works fine.

- [ ] **Step 3 implementation detail — deleting the Protocol from `app/qc/engine.py`:**

Delete lines 58-63 (the `@runtime_checkable class ExportRun(Protocol)` block). Add `from ..models.export import ExportRun` to the imports. Verify engine.py imports stay sorted (ruff isort rules apply — run `uv run ruff check app/qc/engine.py` after).

- [ ] **Step 4: steps.py:382 — rule list types**

```python
        per_product_rules = [
            BaselineRequired(), BrandRequired(), GtinMpn(), EnumValues(),
            ConditionalRequired(), DateFormat(), LengthLimits(), CardinalityRule(),
            CurrencyConsistency(), ImageRequirements(),
        ]
        cross_product_rules = [VariantConsistency(), VolumeDrop()]
```

errors: `list[object]` because mypy can't join heterogeneous rule classes without a common base. Annotate:

```python
        per_product_rules: list[PerProductRule] = [...]
        cross_product_rules: list[CrossProductRule] = [...]
```

with `from ..qc.engine import PerProductRule, CrossProductRule` added to steps.py imports (verify current imports in steps.py line 21 area: `from ..qc.engine import ImageProbe` exists — extend it).

- [ ] **Step 5: runner.py:120,144 — IngestionRun | None assignment**

`_start`/`_finish` in `app/pipeline/runner.py`:

```python
                    run = await session.get(IngestionRun, run_id)
                    if run is None:
                        raise ValueError(f"unknown run id {run_id}")
                    run.status = status
```

mypy complains because the FIRST binding of `run` in the function is `IngestionRun(...)` (not-None) so the later `| None` re-assignment fails. Rename the fetched one:

```python
                    existing = await session.get(IngestionRun, run_id)
                    if existing is None:
                        raise ValueError(f"unknown run id {run_id}")
                    existing.status = status
                    run = existing
```

Wait — check what the subsequent code uses. In `_start` (line ~120):

```python
                run = await session.get(IngestionRun, run_id)
                if run is None:
                    raise ValueError(f"unknown run id {run_id}")
                run.status = "running"
                return run.id
```

Fix: rename to `existing` and return `existing.id`:

```python
                existing = await session.get(IngestionRun, run_id)
                if existing is None:
                    raise ValueError(f"unknown run id {run_id}")
                existing.status = "running"
                return existing.id
```

Same pattern at line 144 in `_finish` (rename and update the subsequent field assignments `run.processed_count = ...` → `existing.processed_count = ...` through to the `return existing.id` or equivalent — read lines 138-160 first and rename consistently).

- [ ] **Step 6: engine.py:91,93 — rule loop variable**

`app/qc/engine.py` lines 86-93:

```python
    for rule in cross_product_rules:
        try:
            rule_findings = await rule.check(products, ctx)
            findings.extend(rule_findings)
```

Error: line 91 `CrossProductRule` assigned to a variable mypy typed `PerProductRule` (joined from the earlier loop) and line 93 `check(products, ...)` signature mismatch. Fix: rename the cross-product loop variable:

```python
    for cross_rule in cross_product_rules:
        try:
            rule_findings = await cross_rule.check(products, ctx)
            findings.extend(rule_findings)
```

(and the logger line: `logger.exception("cross-product rule %s failed", cross_rule.rule_id)`).

- [ ] **Step 7: scheduler.py:53 — validate_cron narrowing**

`app/pipeline/scheduler.py` line 53 in `register`:

```python
    def register(self, feed_source: FeedSource) -> None:
        trigger = validate_cron(feed_source.cron_expression)
```

`cron_expression` is `str | None`. The register contract (read lines 36-66): scheduler only registers feeds with a cron expression. Fix by narrowing with an explicit guard that PRESERVES behavior — check `start()`/`register()` call sites:

```bash
grep -n "register(" app/pipeline/scheduler.py app/main.py
```

If register is only called when `cron_expression` is truthy, the fix is:

```python
    def register(self, expressor: FeedSource) -> None:
```

No — simplest real fix preserving behavior: narrow inside register:

```python
        cron = feed_source.cron_expression
        if cron is None:
            return
        trigger = validate_cron(cron)
```

Verify against the current body: if the body already guards (e.g. caller `start()` filters `if not feed_source.cron_expression: continue` at line 109), then the silent `return` on None is unreachable and behavior is unchanged. Read scheduler.py lines 40-66 and 100-115 first.

- [ ] **Step 8: fetch.py:28 — AsyncClient | None assignment**

`app/ingest/fetch.py` lines 22-28:

```python
        own_client = _client is None
        if own_client:
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
            )
        else:
            client = _client
```

Fix: annotate the local:

```python
        client: httpx.AsyncClient
        if _client is None:
            client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout))
        else:
            client = _client
```

Wait — `own_client = _client is None` is still used later (line 54 area: `if own_client: await client.aclose()`). Keep `own_client` as-is; only add the annotation to `client` (declare before the if/else). `own_client` narrows `_client` implicitly; the annotation makes the join explicit.

- [ ] **Step 9: xml_reader.py:58 — strip on None**

`app/ingest/xml_reader.py` lines 52-58:

```python
        has_text = child.text is not None and child.text.strip()
        has_children = len(child) > 0
        ...
        elif has_text:
            value = child.text.strip()
```

Fix: cache the text once:

```python
        text = child.text
        has_text = text is not None and text.strip() != ""
        has_children = len(child) > 0
        ...
        elif has_text:
            value = text.strip()
```

Read lines 40-66 first; preserve the mixed-content check order exactly (the ValueError for mixed content must still raise first).

- [ ] **Step 10: Verify mypy count = 19**

```bash
uv run mypy . 2>&1 | grep -c ': error:'
```

Expected: `19`

- [ ] **Step 11: Run affected tests**

```bash
export $(grep -E '^TEST_DATABASE_URL=' ../.env | xargs)
uv run pytest tests/test_qc_engine.py tests/test_qc_rules.py tests/test_pipeline_steps.py tests/test_pipeline_runner.py tests/test_dry_run_api.py tests/test_scheduler_service.py tests/test_fetch.py tests/test_xml_reader.py tests/test_ingest_step.py tests/test_plugin_step.py -q
```

Expected: all pass.

- [ ] **Step 12: Update baseline files**

`mypy-baseline.txt`: `19`. `docs/mypy-baseline.md`: remove the 13 fixed lines from the Baseline list; drop/prune the corresponding cluster notes.

- [ ] **Step 13: Commit**

```bash
git add -A app/pipeline app/qc/engine.py app/ingest mypy-baseline.txt docs/mypy-baseline.md
git commit -m "refactor(types): None-narrowing across pipeline/qc/ingest (C2)

- steps.py: plugin-outcome pid guard, image-probe narrowed, rule lists
  annotated list[PerProductRule]/list[CrossProductRule]
- qc/engine.py: delete redundant ExportRun Protocol (ORM model imported);
  cross-rule loop variable renamed
- runner.py: fetched-run local 'existing' separates from new-run binding
- dry_run.py: benefits from engine protocol removal
- scheduler.py: cron None guard in register (unreachable; callers filter)
- fetch.py: annotated client local
- xml_reader.py: cached child.text, strip on narrowed text

mypy: 32 -> 19. No behavior change."
```

---

### Task 3: C3 — route annotations (9 errors)

**Files:**
- Modify: `app/routes/pipeline.py:97,120` (JSONResponse return), `pipeline.py:191,196` (pipeline None)
- Modify: `app/routes/plugins.py:122` (usage dict annotation)
- Modify: `app/routes/dashboard.py:47-48` (item_counts annotation)
- Modify: `mypy-baseline.txt`, `backend/docs/mypy-baseline.md`

**Interfaces:**
- Consumes: none.
- Produces: none (route handlers keep exact response shapes; FastAPI response_models untouched).

- [ ] **Step 1: pipeline.py:97,120 — JSONResponse on dict-annotated routes**

Both `put_pipeline` and (the 422 path in) `get_pipeline` return `_validation_error(errors)` (a `JSONResponse`) from a handler annotated `-> dict`. Real fix: widen the return annotation to match reality. FastAPI allows union returns on the error path only when `response_model` is set (it is: `response_model=PipelineOut` on the decorator) — the function annotation is for mypy only. Change:

```python
async def put_pipeline(
    ...
) -> dict:
```

to

```python
async def put_pipeline(
    ...
) -> dict | JSONResponse:
```

and the same for the other flagged handler (line ~97 is inside `get_pipeline`'s validation-error path — read both handlers around lines 29-60 and 59-170 first). Import `JSONResponse` — `app/routes/pipeline.py` already imports it (used by `_validation_error`), verify the import list.

- [ ] **Step 2: pipeline.py:191,196 — pipeline is None narrowing**

`patch_pipeline_instance` (lines ~186-200):

```python
        pipeline = await session.get(ModulePipeline, feed_source.active_pipeline_id)
        rows = (await session.execute(
            select(ModuleInstance, Plugin)
            .join(Plugin, ModuleInstance.plugin_id == Plugin.id)
            .where(ModuleInstance.pipeline_id == pipeline.id)
            ...
```

`active_pipeline_id` is `int | None` but the guard at line ~179 already raised 404 when `feed_source.active_pipeline_id is None`. mypy can't track through the guard. Fix: narrow once:

```python
        active_pipeline_id = feed_source.active_pipeline_id
        pipeline = await session.get(ModulePipeline, active_pipeline_id)
        if pipeline is None:
            raise HTTPException(status_code=404, detail="instance not found")
```

Read the full handler first (lines 170-216); the 404 on `pipeline is None` is a strictness improvement but unreachable (FK guarantees the row exists) — this is the same pattern as the existing `instance is None` guard right above; it mirrors the handler's own established style.

- [ ] **Step 3: plugins.py:122 — usage dict annotation**

`app/routes/plugins.py` line 122:

```python
    usage = dict((await session.execute(
        select(ModuleInstance.plugin_id, func.count(func.distinct(ModulePipeline.feed_source_id)))
        .join(ModulePipeline, ModuleInstance.pipeline_id == ModulePipeline.id)
        ...
```

Fix: annotate:

```python
    usage: dict[int, int] = dict((await session.execute(
        ...
```

(verify the select columns are int,int — plugin_id is Integer, count() is BigInt→int; annotate `dict[int, int]`).

- - [ ] **Step 4: dashboard.py:47-48 — item_counts annotation**

`app/routes/dashboard.py` lines 47-49:

```python
        item_counts = dict(
            (await session.execute(
                select(StagingProduct.feed_source_id, func.count())
                ...
```

Fix:

```python
        item_counts: dict[int, int] = dict(
            (await session.execute(
                ...
```

If the `Sequence[Row]` incompatibility persists after annotation (Row isn't `tuple[int,int]` to mypy), convert through a comprehension:

```python
        item_counts: dict[int, int] = {
            row[0]: row[1]
            for row in (await session.execute(
                select(StagingProduct.feed_source_id, func.count())
                .where(...)
                .group_by(StagingProduct.feed_source_id)
            ))
        }
```

mirroring the same shape as the plugins.py fix — apply whichever form makes both errors resolve; prefer annotation-first, comprehension fallback. Same for plugins.py:122 if annotation alone doesn't clear both its errors.

- [ ] **Step 5: Verify mypy count = 10**

```bash
uv run mypy . 2>&1 | grep -c ': error:'
```

Expected: `10`

- [ ] **Step 6: Run affected tests**

```bash
export $(grep -E '^TEST_DATABASE_URL=' ../.env | xargs)
uv run pytest tests/test_pipeline_api.py tests/test_plugins_api.py tests/test_dashboard_api.py -q
```

Expected: all pass (1019-suite subset).

- [ ] **Step 7: Update baseline files**

`mypy-baseline.txt`: `10`. `docs/mypy-baseline.md`: remove the 9 fixed lines (7 cluster lines + the 2 dashboard/plugins annotation pairs — the file lists each `: error:` line).

- [ ] **Step 8: Commit**

```bash
git add app/routes/pipeline.py app/routes/plugins.py app/routes/dashboard.py mypy-baseline.txt docs/mypy-baseline.md
git commit -m "refactor(types): route annotations (C3: pipeline, plugins, dashboard)

- pipeline.py: put/get handlers return dict | JSONResponse; pipeline None
  guard mirrors the existing 404 style
- plugins.py: usage dict[int, int] annotation
- dashboard.py: item_counts dict[int, int] annotation

mypy: 19 -> 10. No behavior change."
```

---

### Task 4: C4 — pydantic mypy plugin (3 errors + alembic ignore)

**Files:**
- Modify: `pyproject.toml` (`[tool.mypy]` add plugins line)
- Modify: `alembic/env.py:18` (remove the `# type: ignore[call-arg]`)
- Modify: `mypy-baseline.txt`, `backend/docs/mypy-baseline.md`

**Interfaces:**
- Consumes: pydantic v2 (installed) — `pydantic.mypy` ships with it; no new dependency.
- Produces: none (config typing only).

**Pre-validated approach** (controller verified 2026-09-10): enabling `plugins = ["pydantic.mypy"]` removes exactly the 3 config.py:45 errors, introduces zero new errors elsewhere, requires zero code change, and leaves `tests/test_config.py` fully green (its constructs pass explicit kwargs; pydantic runtime strictness untouched). With the plugin active, `Settings(database_url=...)` in `alembic/env.py` also type-checks without the ignore directive.

- [ ] **Step 1: Enable the plugin in pyproject.toml**

```toml
[tool.mypy]
python_version = "3.10"
plugins = ["pydantic.mypy"]
```

- [ ] **Step 2: Remove the alembic ignore directive**

`alembic/env.py` line 18 — remove the trailing `  # type: ignore[call-arg]` so the line reads:

```python
        "sqlalchemy.url", Settings(database_url=_database_url).async_database_url
```

- [ ] **Step 3: Verify mypy count = 7**

```bash
uv run mypy . 2>&1 | grep -c ': error:'
```

Expected: `7`

- [ ] **Step 4: Run config + alembic-path tests**

```bash
export $(grep -E '^TEST_DATABASE_URL=' ../.env | xargs)
uv run pytest tests/test_config.py tests/test_config_bundle.py tests/test_config_merge.py tests/test_environment_docs.py tests/test_tooling.py -q
```

Expected: all pass. (`test_environment_docs.py` / `test_tooling.py` watch docs/CI files — verify they still pass after Task 6's doc edits too.)

- [ ]  **Step 5: Update baseline files**

`mypy-baseline.txt`: `7`. Doc: remove the 3 config.py lines from the Baseline list; prune the config-cluster note (mentioning the alembic ignore removal).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml alembic/env.py mypy-baseline.txt docs/mypy-baseline.md
git commit -m "build(types): enable pydantic.mypy plugin (C4)

- [tool.mypy] plugins = ['pydantic.mypy'] — Settings() no-arg construct
  type-checks via synthesized __init__; runtime strictness (required env
  vars) unchanged; pydantic itself still enforces presence
- alembic/env.py: drop the type-ignore directive the plugin unblocked
- validated: plugin removes exactly the 3 baseline errors, zero new

mypy: 10 -> 7. No behavior change."
```

---

### Task 5: C5 — tests typing (7 errors)

**Files:**
- Modify: `tests/test_export_token_log_redaction.py:21,28,35`
- Modify: `tests/test_rules_conditions.py:9`, `tests/test_rules_plugin.py:11` (via mypy overrides, not code edits)
- Modify: `pyproject.toml` (mypy overrides)
- Modify: `mypy-baseline.txt`, `backend/docs/mypy-baseline.md`

**Interfaces:**
- Consumes: none.
- Produces: mypy-clean test suite.

- [ ] **Step 1: redaction test — LogRecord.args typing**

`tests/test_export_token_log_redaction.py` builds records via `_access_record(path)` which sets `args=("127.0.0.1:54321", "GET", path, "1.1", 200)`. mypy complains: `LogRecord.args` is typed `tuple[Any, ...] | Mapping[str, Any] | None`; int-indexing a Mapping branch and iterating when None. Real fix — read the file first (lines 1-40). The helper:

```python
def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:54321", "GET", path, "1.1", 200),
        exc_info=None,
    )
```

Fix pattern: narrow `args` in the assertions with isinstance:

```python
def test_export_token_redacted_in_access_record() -> None:
    record = _access_record("/export/secret-token-value.xml")
    assert _ExportTokenRedactor().filter(record) is True
    assert isinstance(record.args, tuple)
    assert record.args[2] == "/export/[REDACTED]"
    assert "secret-token-value" not in record.getMessage()


def test_non_export_path_is_untouched() -> None:
    record = _access_record("/health")
    assert _ExportTokenRedactor().filter(record) is True
    assert isinstance(record.args, tuple)
    assert record.args[2] == "/health"
    assert record.getMessage().endswith('GET /health HTTP/1.1" 200')
```

and for the five-tuple unpacking test (line 35 `client_addr, method, full_path, http_version, status_code = record.args`):

```python
def test_redaction_preserves_five_tuple_for_uvicorn_formatter() -> None:
    record = _access_record("/export/abc123.xml")
    _ExportTokenRedactor().filter(record)
    assert isinstance(record.args, tuple)
    client_addr, method, full_path, http_version, status_code = record.args
    ...
```

`assert isinstance(record.args, tuple)` narrows the union to tuple — `record.args[2]` (int index on tuple) and the unpacking both type-check. All 5 errors resolved by 3 added isinstance asserts.

- [ ] **Step 2: rules-plugin tests — plugin module imports**

`tests/test_rules_conditions.py:9` and `tests/test_rules_plugin.py:11` do `from plugin import ...` after `sys.path.insert(0, .../plugins/core/rules)`. mypy can't resolve `plugin` (import-not-found). Real fix: mypy module overrides so mypy resolves `plugin` as `Any`:

`pyproject.toml` — extend the existing overrides table:

```toml
[[tool.mypy.overrides]]
module = ["jsonschema.*", "apscheduler.*", "asyncpg"]
ignore_missing_imports = true
```

Add after it:

```toml
[[tool.mypy.overrides]]
module = ["plugin"]
ignore_missing_imports = true
```

Wait — this makes mypy treat `plugin` as Any (missing-import). Is that a "real fix"? Yes: mypy cannot follow `sys.path` manipulation performed at runtime inside test files; documenting the runtime import trick via the mypy config (the standard tool for exactly this) is the canonical remedy — same class as the existing `jsonschema.*`/`asyncpg` stub-ignore already accepted in the config. (Design doc C5 said "register under `[[tool.mypy.overrides]]` or import via the plugin loader" — overrides chosen: zero test-code churn, loader import would restructure the tests.)

- [ ] **Step 3: Verify mypy count = 0**

```bash
uv run mypy . 2>&1 | grep -c ': error:'
```

Expected: `0`

- [ ] **Step 4: Run the affected tests**

```bash
export $(grep -E '^TEST_DATABASE_URL=' ../.env | xargs)
uv run pytest tests/test_export_token_log_redaction.py tests/test_rules_conditions.py tests/test_rules_plugin.py tests/test_rules_contract.py -q
```

Expected: all pass (assert additions are runtime no-ops on green paths).

- [ ] **Step 5: Update baseline files**

`mypy-baseline.txt`: `0`. `docs/mypy-baseline.md`: remove the 7 test lines from the Baseline list; prune the tests cluster note.

- [ ] **Step 6: Commit**

```bash
git add tests/test_export_token_log_redaction.py pyproject.toml mypy-baseline.txt docs/mypy-baseline.md
git commit -m "test(types): LogRecord.args narrowing + plugin-module override (C5)

- token-redaction tests: isinstance(record.args, tuple) narrows the
  tuple|Mapping|None union before indexing/unpacking
- [tool.mypy.overrides] module=['plugin'] for the sys.path-based core
  plugin imports (runtime import trick; mypy can't follow it)

mypy: 7 -> 0."
```

---

### Task 6: Gate flip + docs (close TODO 10.1)

**Files:**
- Modify: `.github/workflows/ci.yml:44-48` (mypy step → exit-0)
- Delete: `backend/mypy-baseline.txt`
- Modify: `backend/docs/mypy-baseline.md` (record the flip)
- Modify: `backend/AGENTS.md:16` (gate on exit-0)
- Modify: `TODO.md` (close 10.1; cycle log entry)

**Interfaces:**
- Consumes: Task 5's zero-error state (gate flip only valid at 0).
- Produces: hard exit-0 mypy gate in CI; TODO 10.1 closed.

- [ ] **Step 1: Flip CI mypy step to exit-0**

`.github/workflows/ci.yml` lines 44-48 currently:

```yaml
      - name: Mypy baseline gate (no new type errors)
        working-directory: backend
        run: |
          COUNT=$(uv run mypy . 2>/dev/null | grep -c ': error:')
          BASELINE=$(cat mypy-baseline.txt)
          echo "mypy errors: $COUNT (baseline $BASELINE)"
          if [ "$COUNT" -gt "$BASELINE" ]; then exit 1; fi
```

Change to:

```yaml
      - name: Mypy gate (exit-0)
        working-directory: backend
        run: |
          uv run mypy .
          echo "mypy: clean (0 errors)"
```

The `grep -c` exit-1-when-zero landmine (noted in design) is gone with the baseline compare.

- [ ] **Step 2: Delete the baseline count file**

```bash
git rm backend/mypy-baseline.txt
```

(Working directory for this command: repo root `/home/ozon/gmc_feed_master`.)

- [ ] **Step 3: Update backend/docs/mypy-baseline.md**

Keep the doc as the historical record. Replace the header intro line:

```markdown
CI enforces the count via `backend/mypy-baseline.txt`; keep both in sync — each fix removes lines from both files in the same commit.
```

with:

```markdown
> **Closed 2026-09-10:** the baseline reached 0 and the CI gate was flipped to hard exit-0 (`uv run mypy .`). `mypy-baseline.txt` is deleted. This doc remains as the historical record of the 42-error baseline and its clusters.
```

Prune the now-empty "## Baseline" list and the resolved cluster notes, or keep them marked resolved — keep the doc minimal: the flip note + the original cluster notes as history.

- [ ] **Step 4: Update backend/AGENTS.md gate line**

`backend/AGENTS.md` line 16 currently:

```markdown
uv run mypy .                            # known baseline: docs/mypy-baseline.md (42 errors, no new errors allowed)
```

Change to:

```markdown
uv run mypy .                            # gate: exit-0 (must pass clean; see docs/mypy-baseline.md history)
```

- [ ] **Step 5: Update TODO.md — close 10.1**

In `## Section 10 — Ops: mypy baseline cleanup (2026-09-08)`, change `### 10.1 [ ]` to `### 10.1 [x]` and append to the entry:

```markdown
**Closed 2026-09-10 (branch `mypy-baseline-cleanup`):** all 8 clusters fixed in 5 cluster commits + gate-flip commit. C4 via `pydantic.mypy` plugin (validated: removes exactly the 3 config.py errors, zero new, no code change, `test_config.py` untouched); C5 tests typing via isinstance narrowing + a mypy module override for the sys.path plugin imports; `alembic/env.py` ignore directive removed by C4. CI gate hard exit-0, `mypy-baseline.txt` deleted. Gates: mypy 0, backend 1019, ruff 506 exact.
```

Also add a cycle-log entry at the top of `## Cycle log` (before the `plugin-optimistic-locking` entry):

```markdown
- **2026-09-10 (branch `mypy-baseline-cleanup`, mypy baseline cleanup cycle):** 6 tasks per the plan `docs/superpowers/plans/2026-09-10-mypy-baseline-cleanup.md`, executed <execution-mode>. 42 errors → 0 across 5 cluster commits (C1 renames/locals 10, C2 None-narrowing 13, C3 route annotations 9, C4 pydantic.mypy plugin 3, C5 test typing 7) + gate flip. Highlights: qc/engine.py's redundant `ExportRun` Protocol deleted (ORM model imported instead — protocol/model mismatch was the steps.py/dry_run.py cluster); `Settings()` no-arg construct fixed by enabling `pydantic.mypy` (pre-validated: removes exactly the 3 errors, zero new; `alembic/env.py` ignore directive removed with it); CI `grep -c` landmine (exit-1 when count hits 0) eliminated with the hard gate. Gates: mypy 0; backend 1019; ruff 506 exact; frontend untouched.
```

- [ ] **Step 6: Full gates**

```bash
export $(grep -E '^TEST_DATABASE_URL=' ../.env | xargs)
uv run pytest -n auto -q
uv run ruff check . 2>&1 | grep '^Found'
uv run mypy .
```

Expected: `1019 passed`, `Found 506 errors.`, `Success: no issues found in 219 source files`.

Frontend sanity (untouched but cheap): repo root:

```bash
cd ../frontend && npm test -- --run 2>&1 | grep "Tests "
```

Expected: `Tests  417 passed` — wait, 417 was the OL cycle's count; frontend untouched this cycle so the count should still be 417. Use: expect the same count as the last cycle (`417 passed`).

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/ci.yml backend/AGENTS.md backend/docs/mypy-baseline.md TODO.md
git commit -m "ci(types): mypy hard exit-0 gate; delete baseline (close TODO 10.1)

- ci.yml: drop count/baseline compare (and its grep -c exit-1 landmine);
  gate is uv run mypy . exit-0
- mypy-baseline.txt deleted; docs/mypy-baseline.md records the flip
- backend/AGENTS.md: mypy now gates exit-0 like ruff

mypy: 0. backend: 1019. ruff: 506 exact."
```

(The `git rm` from Step 2 stages the deletion; the `git add` list covers the rest.)

---

## Post-plan tasks (controller)

After Task 6 commit: final whole-branch review (this cycle: diff per commit is small; verify no behavior changes, no ignores, count trajectory 42→32→19→10→7→0, baseline-file sync each commit), then merge `mypy-baseline-cleanup` → main ff-only, push, delete branch, ledger + TODO close-out.
