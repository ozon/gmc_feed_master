# Findings-Detail Version Diff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retain QC findings per ingestion run and add a rule-grouped findings delta (added/fixed/persisted) to the export version diff.

**Architecture:** Findings stop being feed-latest-only: `persist_findings` keeps each run's rows and computes its delta against the previous run; the three latest-run readers are pinned to the newest run; `ExportService.diff` gains a bounded, rule-grouped `findings` block; the frontend renders it in the existing diff. No new dependencies, no DB migration.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + PostgreSQL; React 19 + TypeScript + Mantine + TanStack Query + vitest.

## Global Constraints

- **No new dependencies, no DB migration.**
- Delta keys stay `(code, product_id, field)` with `product_id` normalized to `"cross_product"`.
- Findings sample cap: **20** product ids per bucket; counts remain exact.
- `a_qc`/`b_qc` are true only when the version's `ExportRun.ingestion_run_id` is not `None` (rollback → false).
- Retention stays with `purge_expired_ingestion_runs` (deletes findings by `ingestion_run_id`).
- Backend gates (from `backend/`): `uv run ruff check . ../plugins`, `uv run mypy .`, `uv run pytest`.
- Frontend gates (from `frontend/`): `npm run test`, `npm run typecheck`, `npm run lint`, `npm run format:check`.
- Lazy `%s` logging; no bare `print`; no code comments unless already the file's style.
- Docs affected by behavior/API changes are updated in the same commit.

---

### Task 1: Backend — retain findings per run

**Files:**
- Modify: `backend/app/qc/persistence.py`
- Test: `backend/tests/test_qc_delta.py`
- Modify: `backend/docs/data-model.md` (QualityFinding retention, lines ~237 and ~425)

**Interfaces:**
- Consumes: existing `Finding(rule_id, severity, field, message, product_id)` and `ExportRun` model.
- Produces: `persist_findings` now retains rows per `ingestion_run_id` and computes `fixed/new/remaining` against the previous run (max `ingestion_run_id` for the feed below the current one).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_qc_delta.py` (the file already imports `select`, `QualityFinding`, `Finding`, `persist_findings`, and has the `session_factory` + `feed_source_id` fixtures):

```python
async def _finding_rows(session_factory, feed_source_id):
    async with session_factory() as session:
        return list((await session.execute(
            select(
                QualityFinding.ingestion_run_id,
                QualityFinding.product_id,
                QualityFinding.field,
            )
            .where(QualityFinding.feed_source_id == feed_source_id)
            .order_by(QualityFinding.id)
        )).all())


async def test_persist_findings_retains_previous_runs(session_factory, feed_source_id):
    run_one = [
        Finding(rule_id="r", severity="critical", field="title", message="m", product_id="p1"),
    ]
    await persist_findings(session_factory, feed_source_id, 100, run_one, 1)
    run_two = [
        Finding(rule_id="r", severity="critical", field="gtin", message="m", product_id="p3"),
    ]
    await persist_findings(session_factory, feed_source_id, 101, run_two, 1)

    rows = await _finding_rows(session_factory, feed_source_id)
    assert {(r.ingestion_run_id, r.product_id, r.field) for r in rows} == {
        (100, "p1", "title"),
        (101, "p3", "gtin"),
    }


async def test_persist_findings_is_idempotent_per_run(session_factory, feed_source_id):
    findings = [
        Finding(rule_id="r", severity="critical", field="title", message="m", product_id="p1"),
    ]
    await persist_findings(session_factory, feed_source_id, 100, findings, 1)
    await persist_findings(session_factory, feed_source_id, 100, findings, 1)

    rows = await _finding_rows(session_factory, feed_source_id)
    assert len(rows) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/gmc_feed uv run pytest tests/test_qc_delta.py -k "retains_previous_runs or idempotent" -v`
Expected: `retains_previous_runs` FAILS (the feed-keyed delete wipes run 100 → only `(101, ...)`); `idempotent` may already pass.

- [ ] **Step 3: Rewrite the delta + delete logic**

In `backend/app/qc/persistence.py`, change the import line to include `func`:

```python
from sqlalchemy import delete, func, select
```

Replace the block that currently reads `old_rows = ...` through the feed-keyed delete (lines ~22-38) with:

```python
        previous_run_id = (await session.execute(
            select(func.max(QualityFinding.ingestion_run_id)).where(
                QualityFinding.feed_source_id == feed_source_id,
                QualityFinding.ingestion_run_id < ingestion_run_id,
            )
        )).scalar_one_or_none()

        old_keys: set[tuple[str, str, str | None]] = set()
        if previous_run_id is not None:
            old_rows = (await session.execute(
                select(QualityFinding.code, QualityFinding.product_id, QualityFinding.field)
                .where(
                    QualityFinding.feed_source_id == feed_source_id,
                    QualityFinding.ingestion_run_id == previous_run_id,
                )
            )).all()
            old_keys = {(row.code, row.product_id, row.field) for row in old_rows}

        new_keys = {
            (finding.rule_id, finding.product_id or "cross_product", finding.field)
            for finding in findings
        }
        fixed = len(old_keys - new_keys)
        added = len(new_keys - old_keys)
        remaining = len(old_keys & new_keys)

        # Idempotent replace of this run's rows only; other runs are retained.
        await session.execute(
            delete(QualityFinding).where(
                QualityFinding.ingestion_run_id == ingestion_run_id
            )
        )
```

Leave the insert loop, counts, and `ExportRun` write unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/gmc_feed uv run pytest tests/test_qc_delta.py -v`
Expected: PASS (all three tests, including the pre-existing delta test).

- [ ] **Step 5: Update the retention docs**

In `backend/docs/data-model.md`, after the `### QualityFinding` table (line ~249) add:

```markdown
Retention: rows are kept per `ingestion_run_id` and deleted with the run by `purge_expired_ingestion_runs` (see the retention table below). They can outlive an `ExportVersion` pruned by history retention.
```

Change the retention table row at line ~425 from:

```markdown
| `QualityFinding` (detail) | Latest run per feed_source only |
```

to:

```markdown
| `QualityFinding` (detail) | Retained per `ingestion_run_id`; purged with the ingestion run |
```

- [ ] **Step 6: Commit**

```bash
cd backend && uv run ruff check . ../plugins && uv run mypy .
git add app/qc/persistence.py tests/test_qc_delta.py docs/data-model.md
git commit -m "feat(qc): retain findings per ingestion run"
```

---

### Task 2: Backend — scope latest-run readers

**Files:**
- Modify: `backend/app/routes/quality.py` (`get_quality_findings`, ~line 54)
- Modify: `backend/app/chat/tools.py` (`_query_qc_findings`, ~line 101)
- Modify: `backend/app/pipeline/steps.py` (`_ai_qc_context`, ~line 546)
- Test: `backend/tests/test_quality_api.py`, `backend/tests/test_chat_tools.py`, `backend/tests/test_qc_delta.py`

**Interfaces:**
- Consumes: `QualityFinding.ingestion_run_id`, `ExportRun.ingestion_run_id` (already imported in `quality.py`).
- Produces: all three readers return only the feed's latest run's findings.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_quality_api.py` (imports already include `QualityFinding`, `IngestionRun`, `ExportRun`):

```python
async def test_quality_findings_excludes_older_runs(app_factory):
    _, factory = app_factory
    _, feed_source_id = await _seed_feed_source(app_factory)

    async with factory() as session, session.begin():
        old_run = IngestionRun(feed_source_id=feed_source_id, status="completed")
        new_run = IngestionRun(feed_source_id=feed_source_id, status="completed")
        session.add_all([old_run, new_run])
        await session.flush()

        session.add(ExportRun(
            feed_source_id=feed_source_id, ingestion_run_id=new_run.id,
            status="completed", product_count=1,
            critical_finding_count=1, warning_finding_count=0, info_finding_count=0,
        ))
        session.add(QualityFinding(
            feed_source_id=feed_source_id, ingestion_run_id=old_run.id,
            product_id="OLD", severity="critical", code="old_rule",
            field="title", message="old", details={},
        ))
        session.add(QualityFinding(
            feed_source_id=feed_source_id, ingestion_run_id=new_run.id,
            product_id="NEW", severity="critical", code="new_rule",
            field="title", message="new", details={},
        ))

    client = await logged_in_client(app_factory)
    resp = await client.get(f"/feed-sources/{feed_source_id}/quality-findings")
    assert resp.status_code == 200
    findings = resp.json()["findings"]
    assert [f["code"] for f in findings] == ["new_rule"]
```

Append to `backend/tests/test_chat_tools.py` (imports include `QualityFinding`, `IngestionRun` — verify; the file imports `QualityFinding` at line 14 and uses `seed[4]`):

```python
async def test_query_qc_findings_scopes_to_latest_run(seed, db, client_user):
    factory = db
    async with factory() as session, session.begin():
        old_run = IngestionRun(feed_source_id=seed[2], status="completed")
        new_run = IngestionRun(feed_source_id=seed[2], status="completed")
        session.add_all([old_run, new_run])
        await session.flush()
        session.add(QualityFinding(
            feed_source_id=seed[2], ingestion_run_id=old_run.id,
            product_id="OLD", severity="critical", code="old_rule",
            field=None, message="old", details={},
        ))
        session.add(QualityFinding(
            feed_source_id=seed[2], ingestion_run_id=new_run.id,
            product_id="NEW", severity="critical", code="new_rule",
            field=None, message="new", details={},
        ))
    async with factory() as session:
        result = await execute_tool(
            session, client_user, "query_qc_findings", {"feed_source_id": seed[2]}
        )
    codes = {f["code"] for f in result["findings"]}
    assert codes == {"new_rule"}
```

If `IngestionRun` is not imported in `test_chat_tools.py`, add it to the existing `app.models` import block.

Append to `backend/tests/test_qc_delta.py`:

```python
async def test_ai_qc_context_scopes_to_latest_run(session_factory, feed_source_id):
    from app.models.feed_source import FeedSource
    from app.pipeline.steps import _ai_qc_context

    async with session_factory() as session, session.begin():
        feed = await session.get(FeedSource, feed_source_id)
        feed.configuration = {"ai_qc": {"enabled": True, "budget": 10}}
        session.add(QualityFinding(
            feed_source_id=feed_source_id, ingestion_run_id=100, product_id="old",
            severity="info", code="ai_policy_check", field=None, message="m", details={},
        ))
        session.add(QualityFinding(
            feed_source_id=feed_source_id, ingestion_run_id=101, product_id="new",
            severity="info", code="ai_policy_check", field=None, message="m", details={},
        ))

    async with session_factory() as session:
        feed = await session.get(FeedSource, feed_source_id)
        _, _, _, previous_ids = await _ai_qc_context(session_factory, feed, object())

    assert previous_ids == frozenset({"new"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/gmc_feed uv run pytest tests/test_quality_api.py::test_quality_findings_excludes_older_runs tests/test_chat_tools.py::test_query_qc_findings_scopes_to_latest_run tests/test_qc_delta.py::test_ai_qc_context_scopes_to_latest_run -v`
Expected: FAIL — each returns both runs' findings / both product ids.

- [ ] **Step 3: Scope the quality route**

In `backend/app/routes/quality.py`, replace the findings query (lines ~54-58) with:

```python
    findings_result = await session.execute(
        select(QualityFinding)
        .where(
            QualityFinding.feed_source_id == feed_source_id,
            QualityFinding.ingestion_run_id == export_run.ingestion_run_id,
        )
        .order_by(QualityFinding.id)
    )
```

- [ ] **Step 4: Scope the chat tool**

In `backend/app/chat/tools.py`, change the import line `from sqlalchemy import select, true` to `from sqlalchemy import func, select, true`.

Replace the feed-source branch in `_query_qc_findings` (lines ~105-113):

```python
    if args.feed_source_id is not None:
        feed_source = await _visible_feed_source(session, user, args.feed_source_id)
        if feed_source is None:
            return {"error": "feed source not found"}
        latest_run_id = (await session.execute(
            select(func.max(QualityFinding.ingestion_run_id)).where(
                QualityFinding.feed_source_id == args.feed_source_id
            )
        )).scalar_one_or_none()
        stmt = stmt.where(
            QualityFinding.feed_source_id == args.feed_source_id,
            QualityFinding.ingestion_run_id == latest_run_id,
        )
    else:
        scope = _feed_scope(user)
        if scope is not None:
            stmt = stmt.join(FeedSource, QualityFinding.feed_source_id == FeedSource.id).where(scope)
```

- [ ] **Step 5: Scope the ai_qc context**

In `backend/app/pipeline/steps.py`, change `from sqlalchemy import select as sa_select` (line ~555) to `from sqlalchemy import func, select as sa_select`, then replace the session block (lines ~559-565):

```python
    async with session_factory() as session:
        latest_run_id = (await session.execute(
            sa_select(func.max(QualityFinding.ingestion_run_id)).where(
                QualityFinding.feed_source_id == feed_source.id
            )
        )).scalar_one_or_none()
        if latest_run_id is None:
            ids: frozenset[str] = frozenset()
        else:
            ids = frozenset((await session.execute(
                sa_select(QualityFinding.product_id).where(
                    QualityFinding.feed_source_id == feed_source.id,
                    QualityFinding.code == "ai_policy_check",
                    QualityFinding.ingestion_run_id == latest_run_id,
                )
            )).scalars())
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/gmc_feed uv run pytest tests/test_quality_api.py tests/test_chat_tools.py tests/test_qc_delta.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd backend && uv run ruff check . ../plugins && uv run mypy .
git add app/routes/quality.py app/chat/tools.py app/pipeline/steps.py tests/test_quality_api.py tests/test_chat_tools.py tests/test_qc_delta.py
git commit -m "fix(qc): scope findings readers to the latest run"
```

---

### Task 3: Backend — findings diff in the version compare

**Files:**
- Modify: `backend/app/schemas/export.py`
- Modify: `backend/app/export/service.py` (`diff` + new `_findings_diff` helper)
- Test: `backend/tests/test_findings_diff.py` (create), `backend/tests/test_export_history_api.py`
- Modify: `backend/docs/api.md` (Export History / diff line ~139)

**Interfaces:**
- Consumes: `QualityFinding`, `ExportRun`, `ExportVersion`.
- Produces: `DiffOut.findings: FindingsDiffOut`; module-level `_findings_diff(a, b, a_qc, b_qc) -> FindingsDiffOut`.

- [ ] **Step 1: Add the schemas**

In `backend/app/schemas/export.py`, append before `DiffOut` (or after `DiffProductOut`):

```python
class FindingRuleDiffOut(BaseModel):
    code: str
    severity: str
    added: int
    fixed: int
    persisted: int
    sample_added: list[str]
    sample_fixed: list[str]
    sample_persisted: list[str]


class FindingsDeltaTotals(BaseModel):
    added: int
    fixed: int
    persisted: int


class FindingsDiffOut(BaseModel):
    a_qc: bool
    b_qc: bool
    totals: FindingsDeltaTotals
    rules: list[FindingRuleDiffOut]
```

Change `DiffOut` to add the field:

```python
class DiffOut(BaseModel):
    version: int
    against: int
    added: list[str]
    removed: list[str]
    changed: list[DiffProductOut]
    findings: FindingsDiffOut
```

- [ ] **Step 2: Write the failing unit test**

Create `backend/tests/test_findings_diff.py`:

```python
from dataclasses import dataclass

from app.export.service import _findings_diff


@dataclass
class _Row:
    code: str
    severity: str
    product_id: str
    field: str | None


def test_groups_by_rule_and_computes_buckets():
    a = [
        _Row("rule_a", "warning", "p1", "title"),
        _Row("rule_a", "warning", "p2", "title"),
    ]
    b = [
        _Row("rule_a", "warning", "p1", "title"),  # persisted
        _Row("rule_b", "critical", "p3", "gtin"),  # added
    ]

    result = _findings_diff(a, b, a_qc=True, b_qc=True)

    assert result.totals.model_dump() == {"added": 1, "fixed": 1, "persisted": 1}
    assert [r.code for r in result.rules] == ["rule_b", "rule_a"]  # critical before warning
    rule_a = next(r for r in result.rules if r.code == "rule_a")
    assert (rule_a.added, rule_a.fixed, rule_a.persisted) == (0, 1, 1)
    assert rule_a.sample_fixed == ["p2"]
    assert rule_a.sample_persisted == ["p1"]
    rule_b = next(r for r in result.rules if r.code == "rule_b")
    assert (rule_b.added, rule_b.fixed, rule_b.persisted) == (1, 0, 0)
    assert rule_b.sample_added == ["p3"]


def test_caps_samples_but_keeps_totals():
    a = []
    b = [_Row("rule_a", "info", f"p{i}", None) for i in range(25)]

    result = _findings_diff(a, b, a_qc=True, b_qc=True)

    rule = result.rules[0]
    assert rule.added == 25
    assert len(rule.sample_added) == 20


def test_not_qc_side_yields_empty():
    result = _findings_diff([_Row("rule_a", "info", "p1", None)], [], a_qc=False, b_qc=True)
    assert result.a_qc is False
    assert result.totals.model_dump() == {"added": 0, "fixed": 0, "persisted": 0}
    assert result.rules == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_findings_diff.py -v`
Expected: FAIL — `_findings_diff` does not exist.

- [ ] **Step 4: Implement `_findings_diff` and wire it into `diff`**

In `backend/app/export/service.py`, add `from ..models.quality import QualityFinding` to the model imports, then add the schemas import:

```python
from ..schemas.export import (
    ExportFindingCounts,
    ExportSource,
    ExportVersionOut,
    FindingRuleDiffOut,
    FindingsDeltaTotals,
    FindingsDiffOut,
)
```

Add this module-level helper near `_field_diff` (bottom of the file):

```python
FINDING_SAMPLE_CAP = 20
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


class _FindingRow(Protocol):
    code: str
    severity: str
    product_id: str
    field: str | None


def _findings_diff(
    a: Sequence[_FindingRow],
    b: Sequence[_FindingRow],
    a_qc: bool,
    b_qc: bool,
) -> FindingsDiffOut:
    if not (a_qc and b_qc):
        return FindingsDiffOut(
            a_qc=a_qc,
            b_qc=b_qc,
            totals=FindingsDeltaTotals(added=0, fixed=0, persisted=0),
            rules=[],
        )
    a_map = {(row.code, row.product_id, row.field): row for row in a}
    b_map = {(row.code, row.product_id, row.field): row for row in b}
    added = set(b_map) - set(a_map)
    fixed = set(a_map) - set(b_map)
    persisted = set(a_map) & set(b_map)

    severity_by_code: dict[str, str] = {}
    for row in (*a, *b):
        current = severity_by_code.get(row.code)
        if current is None or _SEVERITY_RANK.get(row.severity, 3) < _SEVERITY_RANK.get(current, 3):
            severity_by_code[row.code] = row.severity

    def products(keys: set[tuple[str, str, str | None]], code: str) -> list[str]:
        return sorted({key[1] for key in keys if key[0] == code})

    rules = [
        FindingRuleDiffOut(
            code=code,
            severity=severity_by_code.get(code, "info"),
            added=sum(1 for key in added if key[0] == code),
            fixed=sum(1 for key in fixed if key[0] == code),
            persisted=sum(1 for key in persisted if key[0] == code),
            sample_added=products(added, code)[:FINDING_SAMPLE_CAP],
            sample_fixed=products(fixed, code)[:FINDING_SAMPLE_CAP],
            sample_persisted=products(persisted, code)[:FINDING_SAMPLE_CAP],
        )
        for code in {key[0] for key in added | fixed | persisted}
    ]
    rules.sort(key=lambda rule: (_SEVERITY_RANK.get(rule.severity, 3), rule.code))

    return FindingsDiffOut(
        a_qc=a_qc,
        b_qc=b_qc,
        totals=FindingsDeltaTotals(
            added=len(added), fixed=len(fixed), persisted=len(persisted)
        ),
        rules=rules,
    )
```

Add the `Protocol` import at the top: `from typing import Any, Protocol, cast` (keep the existing names).

In `ExportService.diff`, inside the existing `async with self._session_factory() as session:` block, after `against_version` is validated, resolve run ids and load findings; then include them in the return:

```python
            run_ids = dict(
                (await session.execute(
                    select(ExportVersion.version_number, ExportRun.ingestion_run_id)
                    .join(ExportRun, ExportVersion.export_run_id == ExportRun.id)
                    .where(
                        ExportVersion.feed_source_id == feed_source_id,
                        ExportVersion.version_number.in_([version_number, against]),
                    )
                )).all()
            )
            run_a = run_ids.get(against)
            run_b = run_ids.get(version_number)
            findings_by_run: dict[int, list[QualityFinding]] = {}
            present = [run_id for run_id in (run_a, run_b) if run_id is not None]
            if present:
                rows = (await session.execute(
                    select(QualityFinding).where(
                        QualityFinding.feed_source_id == feed_source_id,
                        QualityFinding.ingestion_run_id.in_(present),
                    )
                )).scalars()
                for row in rows:
                    findings_by_run.setdefault(row.ingestion_run_id, []).append(row)
```

Then change the tail of `diff` from:

```python
        new_products = self._load_version_products(feed_source_id, version_number, registry)
        old_products = self._load_version_products(feed_source_id, against, registry)
        return _field_diff(old_products, new_products, version_number, against)
```

to:

```python
        new_products = self._load_version_products(feed_source_id, version_number, registry)
        old_products = self._load_version_products(feed_source_id, against, registry)
        result = _field_diff(old_products, new_products, version_number, against)
        result["findings"] = _findings_diff(
            findings_by_run.get(run_a, []),
            findings_by_run.get(run_b, []),
            a_qc=run_a is not None,
            b_qc=run_b is not None,
        ).model_dump()
        return result
```

- [ ] **Step 5: Run unit test to verify it passes**

Run: `cd backend && uv run pytest tests/test_findings_diff.py -v`
Expected: PASS.

- [ ] **Step 6: Add the API test**

Append to `backend/tests/test_export_history_api.py` (add `QualityFinding` and `select` to imports; `ExportRun`/`ExportVersion`/`IngestionRun` are already imported):

```python
async def _ingestion_run_for_version(factory, feed_source_id, version_number):
    async with factory() as session:
        return (await session.execute(
            select(ExportRun.ingestion_run_id)
            .join(ExportVersion, ExportVersion.export_run_id == ExportRun.id)
            .where(
                ExportVersion.feed_source_id == feed_source_id,
                ExportVersion.version_number == version_number,
            )
        )).scalar_one()


async def test_diff_reports_findings_added_fixed_persisted(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, CHANGED])
    _, factory, _ = app_factory
    run_one = await _ingestion_run_for_version(factory, feed_source_id, 1)
    run_two = await _ingestion_run_for_version(factory, feed_source_id, 2)

    async with factory() as session, session.begin():
        session.add(QualityFinding(
            feed_source_id=feed_source_id, ingestion_run_id=run_one,
            product_id="A", severity="critical", code="enum_values",
            field="availability", message="m", details={},
        ))
        session.add(QualityFinding(
            feed_source_id=feed_source_id, ingestion_run_id=run_one,
            product_id="B", severity="warning", code="gtin_mpn",
            field="gtin", message="m", details={},
        ))
        session.add(QualityFinding(
            feed_source_id=feed_source_id, ingestion_run_id=run_two,
            product_id="A", severity="critical", code="enum_values",
            field="availability", message="m", details={},
        ))
        session.add(QualityFinding(
            feed_source_id=feed_source_id, ingestion_run_id=run_two,
            product_id="C", severity="info", code="image_requirements",
            field="image_link", message="m", details={},
        ))

    client = await logged_in_client(app_factory)
    resp = await client.get(f"/feed-sources/{feed_source_id}/export-history/2/diff?against=1")
    assert resp.status_code == 200
    findings = resp.json()["findings"]
    assert findings["a_qc"] is True and findings["b_qc"] is True
    assert findings["totals"] == {"added": 1, "fixed": 1, "persisted": 1}
    by_code = {rule["code"]: rule for rule in findings["rules"]}
    assert by_code["enum_values"]["persisted"] == 1
    assert by_code["gtin_mpn"]["fixed"] == 1
    assert by_code["image_requirements"]["added"] == 1
    assert [rule["code"] for rule in findings["rules"]][0] == "enum_values"  # critical first


async def test_diff_marks_rollback_side_not_qc(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, CHANGED])
    client = await logged_in_client(app_factory)
    rollback = await client.post(f"/feed-sources/{feed_source_id}/export-history/1/rollback")
    assert rollback.status_code == 201

    resp = await client.get(f"/feed-sources/{feed_source_id}/export-history/3/diff?against=2")
    assert resp.status_code == 200
    findings = resp.json()["findings"]
    assert findings["b_qc"] is False
    assert findings["totals"] == {"added": 0, "fixed": 0, "persisted": 0}
    assert findings["rules"] == []
```

- [ ] **Step 7: Run API tests**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/gmc_feed uv run pytest tests/test_export_history_api.py tests/test_findings_diff.py -v`
Expected: PASS.

- [ ] **Step 8: Update the API doc**

In `backend/docs/api.md`, change the diff line (~139) to:

```markdown
- `GET /feed-sources/{id}/export-history/{v}/diff?against={v2}` — field-based diff (per product + attribute, old vs new) plus `findings`: QC findings delta grouped by rule (`a_qc`/`b_qc`, `totals {added, fixed, persisted}`, `rules[{code, severity, added, fixed, persisted, sample_added, sample_fixed, sample_persisted}]`, samples capped at 20 product ids)
```

- [ ] **Step 9: Commit**

```bash
cd backend && uv run ruff check . ../plugins && uv run mypy .
git add app/schemas/export.py app/export/service.py tests/test_findings_diff.py tests/test_export_history_api.py docs/api.md
git commit -m "feat(export): add findings delta to the version diff"
```

---

### Task 4: Frontend — render the findings delta

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/features/export/ExportVersionDiff.tsx`
- Modify: `frontend/src/features/export/ExportVersionDiff.test.tsx`
- Modify: `frontend/public/locales/en/export.json`, `frontend/public/locales/de/export.json`

**Interfaces:**
- Consumes: `DiffOut.findings` from Task 3; `RuleLabel` and `SeverityBadge` from `frontend/src/features/monitoring/findings/`.
- Produces: a QC-findings section (`data-testid="findings-diff"`) inside `ExportVersionDiff`.

- [ ] **Step 1: Add the types**

In `frontend/src/api/types.ts`, add before `DiffOut`:

```ts
export type FindingRuleDiffOut = {
  code: string;
  severity: string;
  added: number;
  fixed: number;
  persisted: number;
  sample_added: string[];
  sample_fixed: string[];
  sample_persisted: string[];
};

export type FindingsDeltaTotals = {
  added: number;
  fixed: number;
  persisted: number;
};

export type FindingsDiffOut = {
  a_qc: boolean;
  b_qc: boolean;
  totals: FindingsDeltaTotals;
  rules: FindingRuleDiffOut[];
};
```

Change `DiffOut`:

```ts
export type DiffOut = {
  version: number;
  against: number;
  added: string[];
  removed: string[];
  changed: DiffProductOut[];
  findings: FindingsDiffOut;
};
```

- [ ] **Step 2: Add the i18n keys**

In `frontend/public/locales/en/export.json`, add a top-level `findingsDiff` object (after the `"download"` object):

```json
  "findingsDiff": {
    "title": "QC findings",
    "added": "added",
    "fixed": "fixed",
    "persisted": "persisted",
    "notQcd": "QC findings unavailable — a compared version was not quality-checked.",
    "noChanges": "No QC finding changes."
  },
```

In `frontend/public/locales/de/export.json`, add:

```json
  "findingsDiff": {
    "title": "QC-Befunde",
    "added": "neu",
    "fixed": "behoben",
    "persisted": "weiterhin",
    "notQcd": "QC-Befunde nicht verfügbar – eine verglichene Version wurde nicht geprüft.",
    "noChanges": "Keine Änderungen bei den QC-Befunden."
  },
```

- [ ] **Step 3: Write the failing test**

In `frontend/src/features/export/ExportVersionDiff.test.tsx`:

Change the `beforeAll` to also load the monitoring namespace (for `RuleLabel`/`SeverityBadge`):

```tsx
beforeAll(async () => {
  await i18n.loadNamespaces('export');
  await i18n.loadNamespaces('monitoring');
});
```

Add an `emptyFindings` constant and include `findings: emptyFindings` in every existing `diff={{ ... }}` fixture in the file:

```tsx
const emptyFindings = {
  a_qc: true,
  b_qc: true,
  totals: { added: 0, fixed: 0, persisted: 0 },
  rules: [],
};
```

Add this test:

```tsx
  it('renders the QC findings delta grouped by rule', () => {
    render(
      <ExportVersionDiff
        diff={{
          version: 3,
          against: 2,
          added: [],
          removed: [],
          changed: [],
          findings: {
            a_qc: true,
            b_qc: true,
            totals: { added: 1, fixed: 0, persisted: 1 },
            rules: [
              {
                code: 'enum_values',
                severity: 'critical',
                added: 1,
                fixed: 0,
                persisted: 1,
                sample_added: ['p9'],
                sample_fixed: [],
                sample_persisted: ['p1'],
              },
            ],
          },
        }}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={{ critical: 0, warning: 0, info: 0 }}
        findingsB={{ critical: 0, warning: 0, info: 0 }}
      />,
    );
    const section = screen.getByTestId('findings-diff');
    expect(section.textContent).toContain('enum_values');
    expect(section.textContent).toContain('p9');
  });

  it('shows the not-QC notice when a compared version was not quality-checked', () => {
    render(
      <ExportVersionDiff
        diff={{
          version: 3,
          against: 2,
          added: [],
          removed: [],
          changed: [],
          findings: {
            a_qc: true,
            b_qc: false,
            totals: { added: 0, fixed: 0, persisted: 0 },
            rules: [],
          },
        }}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={{ critical: 0, warning: 0, info: 0 }}
        findingsB={{ critical: 0, warning: 0, info: 0 }}
      />,
    );
    expect(screen.getByTestId('findings-diff').textContent).toMatch(/not quality-checked/i);
  });
```

Note: the existing `renders empty state when no changes` test keeps `findings: emptyFindings` (all-zero) so it still shows the product "no changes" empty state.

- [ ] **Step 4: Add `findings` to the ExportPage diff stubs**

`frontend/src/features/export/ExportPage.tsx` reads `diff.findings`, and `ExportPage.test.tsx` stubs diff responses typed only as JSON — add the field so the component does not read `undefined`. At the top of `frontend/src/features/export/ExportPage.test.tsx` (after the `versions` fixture), add:

```tsx
const emptyFindings = {
  a_qc: true,
  b_qc: true,
  totals: { added: 0, fixed: 0, persisted: 0 },
  rules: [],
};
```

Then, in every `stubFetch` handler in that file, replace

```tsx
return jsonResponse({ version: 3, against: 2, added: [], removed: [], changed: [] });
```

with

```tsx
return jsonResponse({ version: 3, against: 2, added: [], removed: [], changed: [], findings: emptyFindings });
```

(There are several identical occurrences; replace them all.)

- [ ] **Step 5: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/features/export/ExportVersionDiff.test.tsx`
Expected: FAIL — `findings` missing on `DiffOut` (typecheck/test) and no `findings-diff` testid.

- [ ] **Step 6: Implement the section**

In `frontend/src/features/export/ExportVersionDiff.tsx`:

Add imports:

```tsx
import { RuleLabel } from '../monitoring/findings/RuleLabel';
import { SeverityBadge } from '../monitoring/findings/SeverityBadge';
import type { DiffOut, ExportVersionOut, FindingsDiffOut } from '../../api/types';
```

Add the section component above `export function ExportVersionDiff`:

```tsx
function FindingsDiffSection({ findings }: { findings: FindingsDiffOut }) {
  const { t } = useTranslation('export');
  if (!findings.a_qc || !findings.b_qc) {
    return (
      <Text c="dimmed" size="sm">
        {t('findingsDiff.notQcd')}
      </Text>
    );
  }
  const hasChanges =
    findings.totals.added > 0 || findings.totals.fixed > 0 || findings.totals.persisted > 0;
  if (!hasChanges) {
    return (
      <Text c="dimmed" size="sm">
        {t('findingsDiff.noChanges')}
      </Text>
    );
  }
  const buckets = ['added', 'fixed', 'persisted'] as const;
  return (
    <Stack gap="xs" data-testid="findings-diff">
      <Group gap="sm">
        <Badge color="red" variant="light">
          +{findings.totals.added} {t('findingsDiff.added')}
        </Badge>
        <Badge color="green" variant="light">
          -{findings.totals.fixed} {t('findingsDiff.fixed')}
        </Badge>
        <Badge color="gray" variant="light">
          ={findings.totals.persisted} {t('findingsDiff.persisted')}
        </Badge>
      </Group>
      <Accordion variant="contained">
        {findings.rules.map((rule) => (
          <Accordion.Item key={rule.code} value={rule.code}>
            <Accordion.Control>
              <Group justify="space-between">
                <Group gap="xs">
                  <RuleLabel code={rule.code} />
                  <SeverityBadge severity={rule.severity} />
                </Group>
                <Group gap="xs">
                  {rule.added > 0 ? (
                    <Text size="xs" c="red">
                      +{rule.added}
                    </Text>
                  ) : null}
                  {rule.fixed > 0 ? (
                    <Text size="xs" c="green">
                      -{rule.fixed}
                    </Text>
                  ) : null}
                  {rule.persisted > 0 ? (
                    <Text size="xs" c="dimmed">
                      ={rule.persisted}
                    </Text>
                  ) : null}
                </Group>
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap={4}>
                {buckets.map((bucket) => {
                  const samples: Record<(typeof buckets)[number], string[]> = {
                    added: rule.sample_added,
                    fixed: rule.sample_fixed,
                    persisted: rule.sample_persisted,
                  };
                  const ids = samples[bucket];
                  if (ids.length === 0) return null;
                  return (
                    <Group key={bucket} gap={4}>
                      <Text size="xs" c="dimmed">
                        {t(`findingsDiff.${bucket}`)}:
                      </Text>
                      {ids.map((id) => (
                        <Badge key={id} size="xs" variant="light">
                          {id}
                        </Badge>
                      ))}
                    </Group>
                  );
                })}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
    </Stack>
  );
}
```

In the render, replace the `hasChanges` computation:

```tsx
  const findingsTotals = diff.findings.totals;
  const hasChanges =
    diff.added.length > 0 ||
    diff.removed.length > 0 ||
    diff.changed.length > 0 ||
    findingsTotals.added > 0 ||
    findingsTotals.fixed > 0 ||
    findingsTotals.persisted > 0;
```

Immediately after the existing `findings-delta` `Card`, add:

```tsx
      <Card withBorder padding="sm">
        <Text size="sm" fw={600} mb={4}>
          {t('findingsDiff.title')}
        </Text>
        <FindingsDiffSection findings={diff.findings} />
      </Card>
```

- [ ] **Step 7: Run tests and typecheck**

Run: `cd frontend && npm run test -- src/features/export/ExportVersionDiff.test.tsx && npm run typecheck`
Expected: PASS and clean typecheck.

- [ ] **Step 8: Commit**

```bash
cd frontend && npm run format && npm run lint
git add src/api/types.ts src/features/export/ExportVersionDiff.tsx src/features/export/ExportVersionDiff.test.tsx public/locales/en/export.json public/locales/de/export.json
git commit -m "feat(export): show QC findings delta in the version diff"
```

---

### Task 5: Full verification

**Files:**
- None expected (fix docs/tests only if a gate fails).

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: green gates on the branch.

- [ ] **Step 1: Run all backend gates**

```bash
cd backend
uv run ruff check . ../plugins
uv run mypy .
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/gmc_feed uv run pytest -q
```
Expected: ruff 0, mypy 0, pytest all pass (baseline before this cycle 1424; expect a few more).

- [ ] **Step 2: Run all frontend gates**

```bash
cd frontend
npm run test -- --run
npm run typecheck
npm run lint
npm run format:check
```
Expected: all pass (lint 334 warnings, cap 338). Re-run a single unrelated failure solo before diagnosing (known parallel-load flakes).

- [ ] **Step 3: Confirm docs**

Verify `backend/docs/data-model.md` states per-run findings retention and `backend/docs/api.md` documents the diff `findings` block. Fix and commit if missing.

- [ ] **Step 4: Commit any doc fixes**

```bash
git add backend/docs/data-model.md backend/docs/api.md
git commit -m "docs: align findings retention and diff docs"
```

(Skip if there are no changes.)

---

## Self-Review

- **Spec coverage:** retain per run → Task 1; scope readers (quality, chat, ai_qc) → Task 2; findings diff response → Task 3; docs (data-model Task 1, api Task 3); frontend section → Task 4; verification → Task 5. All spec sections covered.
- **Placeholder scan:** no TBD/TODO; every code step has complete code.
- **Type consistency:** `_findings_diff` / `FindingsDiffOut` / `FindingRuleDiffOut` / `FindingsDeltaTotals` names match across schemas, service, and tests; frontend `FindingsDiffOut`/`FindingRuleDiffOut`/`FindingsDeltaTotals` match the API; `data-testid="findings-diff"` used by test and component; `DiffOut.findings` required in both backend schema and TS type.
- **Note:** `ExportVersionDiff`'s empty-state now also triggers on findings-only changes (fixed in Task 4 Step 5), so a config-driven finding change with identical product data still renders the diff.
