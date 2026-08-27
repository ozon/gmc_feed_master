# M7 Quality Check Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a QC engine that evaluates export-bound products against 12 rules, persists findings with feed-scoped replace semantics, and exposes findings via API.

**Architecture:** A new `app/qc/` package holds the engine, rules, image probe, and persistence. `QualityCheckStep` replaces the no-op stub in the pipeline, runs after plugins and before export. The engine is evaluative and non-blocking — findings are persisted but never prevent a run from completing.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 (async), Pillow (image dimensions), httpx (image fetch), PostgreSQL (existing), Alembic (migration).

## Global Constraints

- Python ≥3.11
- SQLAlchemy 2.0 async patterns only
- Pillow pinned to exact version (latest stable)
- httpx async client for image fetching
- All QC findings are feed-scoped (`feed_source_id` NOT NULL)
- Severity vocabulary: `critical` / `warning` / `info`
- QC engine never raises on findings; only infra errors fail the run
- Image size enforcement date: `2027-01-31`
- Exempt taxonomy IDs: Books {784, 543541, 543542, 543543}, DVDs & Videos {839, 543527, 543528, 543529}, Music & Sound Recordings {855, 543522, 543523, 543524, 543525, 543526}

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `backend/app/qc/__init__.py` | Package exports |
| `backend/app/qc/engine.py` | `QcContext`, `Finding`, `PerProductRule`, `CrossProductRule` protocols, `run_engine()` |
| `backend/app/qc/rules.py` | All 12 rule implementations |
| `backend/app/qc/image_probe.py` | `ImageProbe` — httpx fetch + Pillow parse + DB cache |
| `backend/app/qc/persistence.py` | `persist_findings()` — feed-keyed delete + insert + ExportRun write |
| `backend/app/qc/constants.py` | `EXEMPT_TAXONOMY_IDS`, `IMAGE_FORMATS`, `IMAGE_SIZE_ENFORCEMENT_DATE` |
| `backend/app/routes/quality.py` | `GET /feed-sources/{id}/quality-findings` |
| `backend/tests/test_m7_migration.py` | Migration upgrade/downgrade tests |
| `backend/tests/test_qc_engine.py` | Engine unit tests |
| `backend/tests/test_qc_rules.py` | Rule unit tests (one per rule) |
| `backend/tests/test_image_probe.py` | Image probe unit tests |
| `backend/tests/test_quality_api.py` | API endpoint tests |
| `backend/tests/test_m7_acceptance.py` | End-to-end acceptance gate |

### Modified files
| File | Changes |
|------|---------|
| `backend/app/models/export.py` | Rename `error_finding_count` → `critical_finding_count`; add `ingestion_run_id` FK |
| `backend/app/models/quality.py` | Replace `staging_product_id` with `feed_source_id` + `product_id` + `field` |
| `backend/app/models/feed_source.py` | Add `volume_drop_threshold_pct` column |
| `backend/app/models/__init__.py` | Add `ImageDimension` to exports |
| `backend/app/pipeline/steps.py` | Replace `QualityCheckStep` no-op with real impl; extend `default_steps` signature |
| `backend/app/main.py` | Wire QC engine in `create_app`; include quality router |
| `backend/app/schemas/clients.py` | Add `volume_drop_threshold_pct` to `FeedSourceOut` and `FeedSourceUpdate` |
| `backend/registry/model.py` | Add `min_items`, `item_max_length` to `Cardinality` |
| `backend/registry/parser.py` | Fix `_constraints()` regex; add `min_items` + `item_max_length` capture |
| `backend/registry/generate.py` | Include new `Cardinality` fields in `_as_json()` |
| `backend/registry/loader.py` | Parse new `Cardinality` fields from JSON |
| `backend/pyproject.toml` | Pin Pillow dependency |
| `backend/registry/attributes.json` | Regenerated (new fields) |
| `backend/tests/test_pipeline_steps.py` | Update no-op test for `QualityCheckStep` |
| `backend/tests/test_models.py` | Update `export_runs` column assertions |
| `backend/tests/test_registry_parser.py` | Update cardinality assertions for corrected values |

---

### Task 1: Registry Extension — Cardinality Fields + Parser Fix

**Goal:** Add `min_items` and `item_max_length` to `Cardinality`, fix the parser regex to capture them, and regenerate `attributes.json`.

**Files:**
- Modify: `backend/registry/model.py`
- Modify: `backend/registry/parser.py`
- Modify: `backend/registry/generate.py`
- Modify: `backend/registry/loader.py`
- Regenerate: `backend/registry/attributes.json`
- Modify: `backend/tests/test_registry_parser.py`

**Interfaces:**
- Produces: `Cardinality.min_items: int | None`, `Cardinality.item_max_length: int | None`

#### Steps

- [ ] **Step 1: Add `min_items` and `item_max_length` to `Cardinality`**

```python
# backend/registry/model.py — Cardinality dataclass
@dataclass(frozen=True, slots=True)
class Cardinality:
    max_items: int | None = None
    min_items: int | None = None
    item_max_length: int | None = None
```

- [ ] **Step 2: Fix parser `_constraints()` regex and add `min_items`/`item_max_length` extraction**

The current fallback regex `max\.?\s*(?:of\s*)?(\d+)\b` matches "max 500 MB" as `max_length=500`. Fix it to require the word "char" or be inside a character-length context. Also add extraction of `min_items` from "min. N" patterns and `item_max_length` from "1–150 chars each" patterns.

```python
# backend/registry/parser.py — _constraints function (lines 46-90)
def _constraints(description: str) -> tuple[Constraints, Cardinality]:
    constraints = Constraints()
    cardinality = Cardinality()

    # Existing exact patterns (keep as-is)
    if m := re.search(r"max(?:imum)?\s+(\d[\d,]*)\s+char", description, re.IGNORECASE):
        constraints.max_length = _parse_int(m.group(1))
    if m := re.search(r"min(?:imum)?\s+(\d[\d,]*)\s+char", description, re.IGNORECASE):
        constraints.min_length = _parse_int(m.group(1))
    if m := re.search(r"exactly\s+(\d[\d,]*)\s+char", description, re.IGNORECASE):
        constraints.max_length = constraints.min_length = _parse_int(m.group(1))

    # Fixed fallback: only match "max N" when followed by char/letter context or at end of sentence
    if constraints.max_length is None:
        if m := re.search(r"max\.?\s*(\d+)\s*(?:char|letter)", description, re.IGNORECASE):
            constraints.max_length = _parse_int(m.group(1))
        elif m := re.search(r"max\.?\s*(\d+)\s*\.", description):
            constraints.max_length = _parse_int(m.group(1))

    # Format detection (keep as-is)
    if re.search(r"\bURL\b", description):
        constraints.format = "url"
    elif re.search(r"\bISO\s+8601\b", description):
        constraints.format = "date"

    # Cardinality: max_items from "up to N" or "max. N" (non-char context)
    if m := re.search(r"up\s+to\s+(\d+)", description, re.IGNORECASE):
        cardinality.max_items = _parse_int(m.group(1))
    if m := re.search(r"max\.?\s*(\d+)\s*(?:item|product|entry|element|value)", description, re.IGNORECASE):
        cardinality.max_items = _parse_int(m.group(1))

    # NEW: min_items from "min. N" patterns
    if m := re.search(r"min\.?\s*(\d+)\s*(?:item|product|entry|element|value)", description, re.IGNORECASE):
        cardinality.min_items = _parse_int(m.group(1))

    # NEW: item_max_length from "1–150 chars each" or "up to 150 chars each"
    if m := re.search(r"(?:up\s+to\s+)?(\d+)\s*[-–]\s*(\d+)\s*char", description, re.IGNORECASE):
        cardinality.item_max_length = _parse_int(m.group(2))
    elif m := re.search(r"(\d+)\s+char\s+each", description, re.IGNORECASE):
        cardinality.item_max_length = _parse_int(m.group(1))

    return constraints, cardinality
```

- [ ] **Step 3: Update `_type_info()` to populate `min_items` from "up to N" patterns**

```python
# backend/registry/parser.py — _type_info function (around line 225)
# After existing cardinality.max_items assignment, add:
    # min_items from "min. N items" pattern
    if m := re.search(r"min\.?\s*(\d+)\s*(?:item|product|entry|element|value)", description, re.IGNORECASE):
        cardinality.min_items = _parse_int(m.group(1))
```

- [ ] **Step 4: Update `generate.py` `_as_json()` to include new fields**

```python
# backend/registry/generate.py — _as_json function (line 10)
def _as_json(document: RegistryDocument) -> dict[str, Any]:
    return {
        "attributes": {
            name: {
                "type": info.type,
                "cardinality": {
                    key: value
                    for key, value in {
                        "max_items": info.cardinality.max_items,
                        "min_items": info.cardinality.min_items,
                        "item_max_length": info.cardinality.item_max_length,
                    }.items()
                    if value is not None
                } if info.cardinality.max_items is not None or info.cardinality.min_items is not None or info.cardinality.item_max_length is not None else None,
                "constraints": {
                    key: value
                    for key, value in {
                        "max_length": info.constraints.max_length,
                        "min_length": info.constraints.min_length,
                        "format": info.constraints.format,
                    }.items()
                    if value is not None
                } if info.constraints else None,
                "enum_values": info.enum_values or None,
            }
            for name, info in document.attributes.items()
        }
    }
```

- [ ] **Step 5: Update `loader.py` to parse new fields**

```python
# backend/registry/loader.py — _parse_attributes function (line 53)
# Update Cardinality construction:
    cardinality_data = attr.get("cardinality") or {}
    cardinality = Cardinality(
        max_items=cardinality_data.get("max_items"),
        min_items=cardinality_data.get("min_items"),
        item_max_length=cardinality_data.get("item_max_length"),
    )
```

- [ ] **Step 6: Run tests to verify parser changes don't break existing behavior**

Run: `cd backend && python -m pytest tests/test_registry_parser.py tests/test_registry_generation.py -v`
Expected: PASS (existing tests should still pass with updated expectations)

- [ ] **Step 7: Update parser test assertions**

```python
# backend/tests/test_registry_parser.py — update cardinality assertions
# The product_highlight attribute should now have min_items=2, max_items=100, item_max_length=150
# The additional_image_link attribute should have max_items=10
# Update any test that asserts cardinality.max_items for additional_image_link:
assert document.attributes["additional_image_link"].cardinality.max_items == 10
# Add new assertions for min_items and item_max_length where applicable
```

- [ ] **Step 8: Regenerate attributes.json and verify gate**

Run: `cd backend && python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json`
Run: `cd backend && python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json --check`
Expected: PASS (gate green)

- [ ] **Step 9: Commit**

```bash
git add backend/registry/model.py backend/registry/parser.py backend/registry/generate.py backend/registry/loader.py backend/registry/attributes.json backend/tests/test_registry_parser.py
git commit -m "feat(registry): add min_items/item_max_length to Cardinality, fix parser regex"
```

---

### Task 2: Pin Pillow Dependency

**Goal:** Add Pillow as an exact-pinned dependency.

**Files:**
- Modify: `backend/pyproject.toml`

#### Steps

- [ ] **Step 1: Add Pillow to pyproject.toml**

```toml
# backend/pyproject.toml — dependencies section
dependencies = [
    "alembic>=1.13,<2",
    "fastapi>=0.111,<1",
    "httpx>=0.27,<1",
    "itsdangerous>=2.2,<3",
    "passlib[bcrypt]>=1.7,<2",
    "pillow>=10.4,<11",
    "pydantic>=2.7,<3",
    "pyjwt>=2.8,<3",
    "sqlalchemy[asyncio]>=2.0,<3",
    "uvicorn[standard]>=0.30,<1",
]
```

- [ ] **Step 2: Lock the dependency**

Run: `cd backend && uv lock`
Expected: Pillow added to uv.lock

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "deps: pin Pillow for image dimension parsing"
```

---

### Task 3: Migration — Schema Changes

**Goal:** Create Alembic migration for all M7 schema changes.

**Files:**
- Create: `backend/alembic/versions/20260827_0002_m7_quality_check.py`
- Create: `backend/tests/test_m7_migration.py`

#### Steps

- [ ] **Step 1: Write the migration**

```python
# backend/alembic/versions/20260827_0002_m7_quality_check.py
"""M7 quality check engine

Revision ID: 20260827_0002
Revises: 20260827_0001
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

revision = "20260827_0002"
down_revision = "20260827_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Rename export_runs.error_finding_count → critical_finding_count
    op.alter_column("export_runs", "error_finding_count", new_column_name="critical_finding_count")

    # 2. Add export_runs.ingestion_run_id (nullable FK)
    op.add_column("export_runs", sa.Column("ingestion_run_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_export_runs_ingestion_run_id", "export_runs", "ingestion_runs", ["ingestion_run_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_export_runs_ingestion_run_id", "export_runs", ["ingestion_run_id"])

    # 3. Create image_dimensions table
    op.create_table(
        "image_dimensions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.String(2048), nullable=False, unique=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fetch_error", sa.String(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 4. Add feed_sources.volume_drop_threshold_pct
    op.add_column("feed_sources", sa.Column("volume_drop_threshold_pct", sa.Integer(), nullable=False, server_default="20"))

    # 5. Modify quality_findings: add feed_source_id, product_id, field; drop staging_product_id
    op.add_column("quality_findings", sa.Column("feed_source_id", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("quality_findings", sa.Column("product_id", sa.String(255), nullable=False, server_default=""))
    op.add_column("quality_findings", sa.Column("field", sa.String(255), nullable=True))
    op.create_foreign_key("fk_quality_findings_feed_source_id", "quality_findings", "feed_sources", ["feed_source_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_quality_findings_feed_source_id", "quality_findings", ["feed_source_id"])
    op.drop_index("ix_quality_findings_staging_product_id", table_name="quality_findings")
    op.drop_constraint("quality_findings_staging_product_id_fkey", "quality_findings", type_="foreignkey")
    op.drop_column("quality_findings", "staging_product_id")


def downgrade() -> None:
    # Reverse quality_findings changes
    op.add_column("quality_findings", sa.Column("staging_product_id", sa.Integer(), nullable=False))
    op.create_foreign_key("quality_findings_staging_product_id_fkey", "quality_findings", "staging_products", ["staging_product_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_quality_findings_staging_product_id", "quality_findings", ["staging_product_id"])
    op.drop_index("ix_quality_findings_feed_source_id", table_name="quality_findings")
    op.drop_constraint("fk_quality_findings_feed_source_id", "quality_findings", type_="foreignkey")
    op.drop_column("quality_findings", "field")
    op.drop_column("quality_findings", "product_id")
    op.drop_column("quality_findings", "feed_source_id")

    # Reverse feed_sources change
    op.drop_column("feed_sources", "volume_drop_threshold_pct")

    # Drop image_dimensions
    op.drop_table("image_dimensions")

    # Reverse export_runs changes
    op.drop_index("ix_export_runs_ingestion_run_id", table_name="export_runs")
    op.drop_constraint("fk_export_runs_ingestion_run_id", "export_runs", type_="foreignkey")
    op.drop_column("export_runs", "ingestion_run_id")
    op.alter_column("export_runs", "critical_finding_count", new_column_name="error_finding_count")
```

- [ ] **Step 2: Write migration tests**

```python
# backend/tests/test_m7_migration.py
import asyncio
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio


def _alembic_config(url):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


async def _columns(url, table):
    engine = create_async_engine(url, pool_size=2, max_overflow=0)

    def _run(connection):
        inspector = inspect(connection)
        return {c["name"] for c in inspector.get_columns(table)}

    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_run)
    finally:
        await engine.dispose()


async def test_upgrade_adds_qc_columns(isolated_database_url):
    export_cols = await _columns(isolated_database_url, "export_runs")
    assert "critical_finding_count" in export_cols
    assert "ingestion_run_id" in export_cols
    assert "error_finding_count" not in export_cols

    quality_cols = await _columns(isolated_database_url, "quality_findings")
    assert "feed_source_id" in quality_cols
    assert "product_id" in quality_cols
    assert "field" in quality_cols
    assert "staging_product_id" not in quality_cols

    feed_cols = await _columns(isolated_database_url, "feed_sources")
    assert "volume_drop_threshold_pct" in feed_cols

    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)

    def _has_table(connection):
        inspector = inspect(connection)
        return "image_dimensions" in inspector.get_table_names()

    try:
        async with engine.connect() as connection:
            assert await connection.run_sync(_has_table)
    finally:
        await engine.dispose()


async def test_downgrade_reverses_qc_changes(isolated_database_url):
    await asyncio.to_thread(
        command.downgrade, _alembic_config(isolated_database_url), "20260827_0001"
    )

    export_cols = await _columns(isolated_database_url, "export_runs")
    assert "error_finding_count" in export_cols
    assert "critical_finding_count" not in export_cols
    assert "ingestion_run_id" not in export_cols

    quality_cols = await _columns(isolated_database_url, "quality_findings")
    assert "staging_product_id" in quality_cols
    assert "feed_source_id" not in quality_cols

    await asyncio.to_thread(command.upgrade, _alembic_config(isolated_database_url), "head")
```

- [ ] **Step 3: Run migration tests**

Run: `cd backend && python -m pytest tests/test_m7_migration.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/20260827_0002_m7_quality_check.py backend/tests/test_m7_migration.py
git commit -m "feat(migration): M7 schema changes for QC engine"
```

---

### Task 4: Update Models

**Goal:** Update SQLAlchemy models to match the new schema.

**Files:**
- Modify: `backend/app/models/export.py`
- Modify: `backend/app/models/quality.py`
- Modify: `backend/app/models/feed_source.py`
- Create: `backend/app/models/image_dimension.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/tests/test_models.py`

#### Steps

- [ ] **Step 1: Update `ExportRun` model**

```python
# backend/app/models/export.py — ExportRun class
class ExportRun(Base):
    __tablename__ = "export_runs"
    __table_args__ = (
        Index("ix_export_runs_feed_source_id", "feed_source_id"),
        Index("ix_export_runs_export_version_id", "export_version_id"),
        Index("ix_export_runs_ingestion_run_id", "ingestion_run_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed_source_id: Mapped[int] = mapped_column(ForeignKey("feed_sources.id", ondelete="RESTRICT"), nullable=False)
    export_version_id: Mapped[int | None] = mapped_column(ForeignKey("export_versions.id", ondelete="RESTRICT"))
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    product_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    info_finding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_finding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    critical_finding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 2: Update `QualityFinding` model**

```python
# backend/app/models/quality.py
from datetime import datetime
from typing import Any
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class QualityFinding(Base):
    __tablename__ = "quality_findings"
    __table_args__ = (
        Index("ix_quality_findings_feed_source_id", "feed_source_id"),
        Index("ix_quality_findings_ingestion_run_id", "ingestion_run_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed_source_id: Mapped[int] = mapped_column(ForeignKey("feed_sources.id", ondelete="CASCADE"), nullable=False)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="RESTRICT"), nullable=False)
    product_id: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

- [ ] **Step 3: Add `volume_drop_threshold_pct` to `FeedSource`**

```python
# backend/app/models/feed_source.py — add after source_url column
    volume_drop_threshold_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=20, server_default="20")
```

- [ ] **Step 4: Create `ImageDimension` model**

```python
# backend/app/models/image_dimension.py
from datetime import datetime
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class ImageDimension(Base):
    __tablename__ = "image_dimensions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetch_error: Mapped[str | None] = mapped_column(String(), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

- [ ] **Step 5: Update `__init__.py` exports**

```python
# backend/app/models/__init__.py — add ImageDimension to imports and __all__
from .image_dimension import ImageDimension
```

- [ ] **Step 6: Update `test_models.py` assertions**

```python
# backend/tests/test_models.py — test_review_contract_fields_and_foreign_key_indexes
# Update the export_runs assertion:
    assert {"product_count", "info_finding_count", "warning_finding_count", "critical_finding_count", "export_version_id"} <= set(tables["export_runs"].c.keys())

# Update the quality_findings assertion:
    assert {"feed_source_id", "product_id", "ingestion_run_id"} <= set(tables["quality_findings"].c.keys())
    assert "staging_product_id" not in set(tables["quality_findings"].c.keys())
```

- [ ] **Step 7: Run model tests**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/export.py backend/app/models/quality.py backend/app/models/feed_source.py backend/app/models/image_dimension.py backend/app/models/__init__.py backend/tests/test_models.py
git commit -m "feat(models): update for M7 QC engine schema"
```

---

### Task 5: QC Engine — Types and Core

**Goal:** Create the QC engine types (`QcContext`, `Finding`, rule protocols) and the `run_engine()` function.

**Files:**
- Create: `backend/app/qc/__init__.py`
- Create: `backend/app/qc/constants.py`
- Create: `backend/app/qc/engine.py`
- Create: `backend/tests/test_qc_engine.py`

#### Steps

- [ ] **Step 1: Create constants**

```python
# backend/app/qc/constants.py
from datetime import date

EXEMPT_TAXONOMY_IDS: frozenset[int] = frozenset({
    # Books
    784, 543541, 543542, 543543,
    # DVDs & Videos
    839, 543527, 543528, 543529,
    # Music & Sound Recordings
    855, 543522, 543523, 543524, 543525, 543526,
})

IMAGE_FORMATS: frozenset[str] = frozenset({
    "jpg", "jpeg", "webp", "png", "gif", "bmp", "tiff", "tif",
})

IMAGE_SIZE_ENFORCEMENT_DATE: date = date(2027, 1, 31)

IMAGE_FETCH_CAP_BYTES: int = 10 * 1024 * 1024  # 10 MB

IMAGE_CONCURRENCY: int = 8
```

- [ ] **Step 2: Create engine types and `run_engine()`**

```python
# backend/app/qc/engine.py
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from registry.model import RegistryDocument

from ..clock import Clock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QcContext:
    feed_source_id: int
    currency: str | None
    volume_drop_threshold_pct: int
    registry: RegistryDocument
    clock: Clock
    image_probe: ImageProbe
    previous_export_run: ExportRun | None


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str  # "critical" | "warning" | "info"
    field: str | None
    message: str
    product_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class PerProductRule(Protocol):
    rule_id: str

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]: ...


@runtime_checkable
class CrossProductRule(Protocol):
    rule_id: str

    async def check(self, products: list[dict], ctx: QcContext) -> list[Finding]: ...


@runtime_checkable
class ImageProbe(Protocol):
    async def probe(self, url: str) -> tuple[int | None, int | None, str | None]:
        """Return (width, height, error_message). error_message is None on success."""
        ...


@runtime_checkable
class ExportRun(Protocol):
    feed_source_id: int
    ingestion_run_id: int
    product_count: int
    critical_finding_count: int
    warning_finding_count: int
    info_finding_count: int


async def run_engine(
    products: list[dict],
    product_ids: list[str],
    ctx: QcContext,
    per_product_rules: list[PerProductRule],
    cross_product_rules: list[CrossProductRule],
) -> list[Finding]:
    findings: list[Finding] = []

    # Per-product rules — attach product_id to each finding
    for product, product_id in zip(products, product_ids):
        for rule in per_product_rules:
            try:
                rule_findings = await rule.check(product, ctx)
                for f in rule_findings:
                    findings.append(Finding(
                        rule_id=f.rule_id, severity=f.severity,
                        field=f.field, message=f.message,
                        product_id=product_id, details=f.details,
                    ))
            except Exception:
                logger.exception("rule %s failed on product %s", rule.rule_id, product_id)

    # Cross-product rules — no product_id (findings apply to the feed as a whole)
    for rule in cross_product_rules:
        try:
            rule_findings = await rule.check(products, ctx)
            findings.extend(rule_findings)
        except Exception:
            logger.exception("cross-product rule %s failed", rule.rule_id)

    return findings
```

- [ ] **Step 3: Create package init**

```python
# backend/app/qc/__init__.py
from .engine import QcContext, Finding, PerProductRule, CrossProductRule, ImageProbe, ExportRun, run_engine
from .constants import EXEMPT_TAXONOMY_IDS, IMAGE_FORMATS, IMAGE_SIZE_ENFORCEMENT_DATE

__all__ = [
    "QcContext", "Finding", "PerProductRule", "CrossProductRule",
    "ImageProbe", "ExportRun", "run_engine",
    "EXEMPT_TAXONOMY_IDS", "IMAGE_FORMATS", "IMAGE_SIZE_ENFORCEMENT_DATE",
]
```

- [ ] **Step 4: Write engine unit tests**

```python
# backend/tests/test_qc_engine.py
import pytest
from app.qc.engine import QcContext, Finding, PerProductRule, CrossProductRule, run_engine
from registry.model import RegistryDocument
from app.clock import TestClock

pytestmark = pytest.mark.asyncio


class StubImageProbe:
    async def probe(self, url):
        return (800, 600, None)


class StubPerProductRule:
    rule_id = "stub_per"

    async def check(self, product, ctx):
        if not product.get("title"):
            return [Finding(rule_id="stub_per", severity="warning", field="title", message="missing title")]
        return []


class StubCrossProductRule:
    rule_id = "stub_cross"

    async def check(self, products, ctx):
        if len(products) < 2:
            return [Finding(rule_id="stub_cross", severity="info", field=None, message="need more products")]
        return []


def _make_ctx(**overrides):
    defaults = dict(
        feed_source_id=1,
        currency="USD",
        volume_drop_threshold_pct=20,
        registry=RegistryDocument(attributes={}),
        clock=TestClock(__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc)),
        image_probe=StubImageProbe(),
        previous_export_run=None,
    )
    defaults.update(overrides)
    return QcContext(**defaults)


async def test_per_product_rule_finds_issues():
    products = [{"id": "1"}, {"id": "2", "title": "Good"}]
    product_ids = ["1", "2"]
    ctx = _make_ctx()
    findings = await run_engine(products, product_ids, ctx, [StubPerProductRule()], [])
    assert len(findings) == 1
    assert findings[0].rule_id == "stub_per"
    assert findings[0].field == "title"
    assert findings[0].product_id == "1"


async def test_cross_product_rule_finds_issues():
    products = [{"id": "1"}]
    product_ids = ["1"]
    ctx = _make_ctx()
    findings = await run_engine(products, product_ids, ctx, [], [StubCrossProductRule()])
    assert len(findings) == 1
    assert findings[0].rule_id == "stub_cross"


async def test_no_findings_on_clean_data():
    products = [{"id": "1", "title": "Good"}, {"id": "2", "title": "Also good"}]
    product_ids = ["1", "2"]
    ctx = _make_ctx()
    findings = await run_engine(products, product_ids, ctx, [StubPerProductRule()], [StubCrossProductRule()])
    assert findings == []


async def test_rule_exception_does_not_crash_engine():
    class BrokenRule:
        rule_id = "broken"
        async def check(self, product, ctx):
            raise RuntimeError("boom")

    products = [{"id": "1"}]
    product_ids = ["1"]
    ctx = _make_ctx()
    findings = await run_engine(products, product_ids, ctx, [BrokenRule()], [])
    assert findings == []
```

- [ ] **Step 5: Run engine tests**

Run: `cd backend && python -m pytest tests/test_qc_engine.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/qc/ backend/tests/test_qc_engine.py
git commit -m "feat(qc): engine types, protocols, and run_engine()"
```

---

### Task 6: QC Rules — All 12 Implementations

**Goal:** Implement all 12 QC rules.

**Files:**
- Create: `backend/app/qc/rules.py`
- Create: `backend/tests/test_qc_rules.py`

#### Steps

- [ ] **Step 1: Create rules module with all 12 rules**

```python
# backend/app/qc/rules.py
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from ..clock import Clock
from .constants import EXEMPT_TAXONOMY_IDS, IMAGE_FORMATS, IMAGE_SIZE_ENFORCEMENT_DATE
from .engine import QcContext, Finding


class BaselineRequired:
    rule_id = "baseline_required"
    _REQUIRED = ("id", "link", "image_link", "availability", "price", "condition")

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        findings = []
        for field_name in self._REQUIRED:
            if not product.get(field_name):
                findings.append(Finding(
                    rule_id=self.rule_id, severity="critical",
                    field=field_name, message=f"missing required field {field_name}",
                ))
        # title or structured_title
        if not product.get("title") and not product.get("structured_title"):
            findings.append(Finding(
                rule_id=self.rule_id, severity="critical",
                field="title", message="missing required field title/structured_title",
            ))
        # description or structured_description
        if not product.get("description") and not product.get("structured_description"):
            findings.append(Finding(
                rule_id=self.rule_id, severity="critical",
                field="description", message="missing required field description/structured_description",
            ))
        return findings


class BrandRequired:
    rule_id = "brand_required"

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        if not product.get("brand"):
            cat_id = product.get("google_product_category")
            if cat_id is not None:
                try:
                    cat_int = int(cat_id)
                except (ValueError, TypeError):
                    cat_int = None
                if cat_int in EXEMPT_TAXONOMY_IDS:
                    return []
            return [Finding(
                rule_id=self.rule_id, severity="warning",
                field="brand", message="missing brand",
            )]
        return []


class GtinMpn:
    rule_id = "gtin_mpn"

    @staticmethod
    def _gs1_checksum(gtin: str) -> bool:
        if not gtin.isdigit() or len(gtin) < 8:
            return False
        digits = [int(d) for d in reversed(gtin)]
        total = sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits))
        return total % 10 == 0

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        gtin = product.get("gtin")
        if not gtin:
            if not product.get("mpn") or not product.get("brand"):
                return [Finding(
                    rule_id=self.rule_id, severity="warning",
                    field="gtin", message="missing gtin requires mpn and brand",
                )]
            return []
        if not self._gs1_checksum(str(gtin)):
            return [Finding(
                rule_id=self.rule_id, severity="critical",
                field="gtin", message="invalid GTIN checksum",
            )]
        return []


class EnumValues:
    rule_id = "enum_values"

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        findings = []
        for attr_name, attr_info in ctx.registry.attributes.items():
            if not attr_info.enum_values:
                continue
            value = product.get(attr_name)
            if value is not None and value not in attr_info.enum_values:
                findings.append(Finding(
                    rule_id=self.rule_id, severity="critical",
                    field=attr_name, message=f"invalid value for {attr_name}: {value}",
                ))
        return findings


class ConditionalRequired:
    rule_id = "conditional_required"

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        findings = []
        if product.get("availability") == "preorder" and not product.get("availability_date"):
            findings.append(Finding(
                rule_id=self.rule_id, severity="warning",
                field="availability_date", message="availability_date required for preorder",
            ))
        if product.get("unit_pricing_base_measure") and not product.get("unit_pricing_measure"):
            findings.append(Finding(
                rule_id=self.rule_id, severity="warning",
                field="unit_pricing_measure", message="unit_pricing_measure required when base_measure is set",
            ))
        return findings


class DateFormat:
    rule_id = "date_format"
    _FIELDS = ("availability_date", "expiration_date", "sale_price_effective_date")

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        findings = []
        for field_name in self._FIELDS:
            value = product.get(field_name)
            if not value:
                continue
            try:
                parsed = datetime.fromisoformat(str(value))
                if parsed.tzinfo is None:
                    findings.append(Finding(
                        rule_id=self.rule_id, severity="critical",
                        field=field_name, message=f"{field_name} must include timezone",
                    ))
            except (ValueError, TypeError):
                findings.append(Finding(
                    rule_id=self.rule_id, severity="critical",
                    field=field_name, message=f"invalid date format for {field_name}",
                ))
        return findings


class LengthLimits:
    rule_id = "length_limits"

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        findings = []
        for attr_name, attr_info in ctx.registry.attributes.items():
            if not attr_info.constraints or not attr_info.constraints.max_length:
                continue
            value = product.get(attr_name)
            if value is not None and len(str(value)) > attr_info.constraints.max_length:
                findings.append(Finding(
                    rule_id=self.rule_id, severity="warning",
                    field=attr_name, message=f"{attr_name} exceeds max length {attr_info.constraints.max_length}",
                ))
        return findings


class CardinalityRule:
    rule_id = "cardinality"

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        findings = []
        for attr_name, attr_info in ctx.registry.attributes.items():
            if not attr_info.cardinality:
                continue
            value = product.get(attr_name)
            if value is None:
                continue
            if isinstance(value, list):
                max_items = attr_info.cardinality.max_items
                min_items = attr_info.cardinality.min_items
                if max_items is not None and len(value) > max_items:
                    findings.append(Finding(
                        rule_id=self.rule_id, severity="warning",
                        field=attr_name, message=f"{attr_name} has {len(value)} items, max is {max_items}",
                    ))
                if min_items is not None and len(value) < min_items:
                    findings.append(Finding(
                        rule_id=self.rule_id, severity="warning",
                        field=attr_name, message=f"{attr_name} has {len(value)} items, min is {min_items}",
                    ))
                if attr_info.cardinality.item_max_length:
                    for i, item in enumerate(value):
                        if len(str(item)) > attr_info.cardinality.item_max_length:
                            findings.append(Finding(
                                rule_id=self.rule_id, severity="warning",
                                field=f"{attr_name}.{i+1}",
                                message=f"{attr_name}[{i+1}] exceeds max length {attr_info.cardinality.item_max_length}",
                            ))
        return findings


class CurrencyConsistency:
    rule_id = "currency_consistency"

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        if not ctx.currency:
            return []
        findings = []
        for field_name in ("price", "sale_price"):
            value = product.get(field_name)
            if not value:
                continue
            parts = str(value).split(" ")
            if len(parts) >= 2 and parts[0] != ctx.currency:
                findings.append(Finding(
                    rule_id=self.rule_id, severity="critical",
                    field=field_name, message=f"currency mismatch: {parts[0]} vs {ctx.currency}",
                ))
        return findings


class ImageRequirements:
    rule_id = "image_requirements"

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        findings = []
        urls = []
        if product.get("image_link"):
            urls.append(("image_link", str(product["image_link"])))
        for i, url in enumerate(product.get("additional_image_link") or [], start=1):
            urls.append((f"additional_image_link.{i}", str(url)))

        for field_name, url in urls:
            ext = url.rsplit(".", 1)[-1].lower() if "." in url else ""
            if ext not in IMAGE_FORMATS:
                findings.append(Finding(
                    rule_id=self.rule_id, severity="warning",
                    field=field_name, message=f"unrecognized image format: {ext or '(none)'}",
                ))
            width, height, error = await ctx.image_probe.probe(url)
            if error:
                findings.append(Finding(
                    rule_id=self.rule_id, severity="info",
                    field=field_name, message=f"image fetch error: {error}",
                ))
                continue
            if width is None or height is None:
                continue
            if width < 500 or height < 500:
                severity = "critical" if ctx.clock.now().date() >= IMAGE_SIZE_ENFORCEMENT_DATE else "warning"
                findings.append(Finding(
                    rule_id=self.rule_id, severity=severity,
                    field=field_name, message=f"image too small: {width}x{height}",
                ))
            elif width < 1500 or height < 1500:
                findings.append(Finding(
                    rule_id=self.rule_id, severity="info",
                    field=field_name, message=f"image below recommended size: {width}x{height}",
                ))
        return findings


class VariantConsistency:
    rule_id = "variant_consistency"
    _BASE_ATTRS = ("id", "title", "description", "link", "image_link", "availability", "condition", "price")

    async def check(self, products: list[dict], ctx: QcContext) -> list[Finding]:
        groups: dict[str, list[dict]] = {}
        for p in products:
            gid = p.get("item_group_id")
            if gid:
                groups.setdefault(str(gid), []).append(p)

        findings = []
        for gid, group in groups.items():
            if len(group) < 2:
                continue
            base = group[0]
            for attr in self._BASE_ATTRS:
                values = {str(p.get(attr)) for p in group if p.get(attr) is not None}
                if len(values) > 1:
                    findings.append(Finding(
                        rule_id=self.rule_id, severity="warning",
                        field=attr, message=f"inconsistent {attr} across variant group {gid}",
                    ))
        return findings


class VolumeDrop:
    rule_id = "volume_drop"

    async def check(self, products: list[dict], ctx: QcContext) -> list[Finding]:
        if ctx.previous_export_run is None:
            return []
        prev_count = ctx.previous_export_run.product_count
        if prev_count == 0:
            return []
        current_count = len(products)
        drop_pct = ((prev_count - current_count) / prev_count) * 100
        if drop_pct >= ctx.volume_drop_threshold_pct:
            return [Finding(
                rule_id=self.rule_id, severity="warning",
                field=None,
                message=f"volume drop {drop_pct:.1f}% exceeds threshold {ctx.volume_drop_threshold_pct}%",
                details={"previous_count": prev_count, "current_count": current_count, "drop_pct": round(drop_pct, 1)},
            )]
        return []
```

- [ ] **Step 2: Write rule unit tests**

```python
# backend/tests/test_qc_rules.py
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from app.qc.rules import (
    BaselineRequired, BrandRequired, GtinMpn, EnumValues,
    ConditionalRequired, DateFormat, LengthLimits, CardinalityRule,
    CurrencyConsistency, ImageRequirements, VariantConsistency, VolumeDrop,
)
from app.qc.engine import QcContext, Finding
from registry.model import RegistryDocument, AttributeInfo, Cardinality, Constraints
from app.clock import TestClock

pytestmark = pytest.mark.asyncio


def _make_ctx(**overrides):
    defaults = dict(
        feed_source_id=1,
        currency="USD",
        volume_drop_threshold_pct=20,
        registry=RegistryDocument(attributes={}),
        clock=TestClock(datetime(2026, 6, 1, tzinfo=timezone.utc)),
        image_probe=AsyncMock(),
        previous_export_run=None,
    )
    defaults.update(overrides)
    return QcContext(**defaults)


# -- BaselineRequired --

async def test_baseline_required_finds_missing():
    rule = BaselineRequired()
    findings = await rule.check({}, _make_ctx())
    assert len(findings) > 0
    assert findings[0].severity == "critical"


async def test_baseline_required_passes_complete():
    rule = BaselineRequired()
    product = {"id": "1", "title": "T", "description": "D", "link": "http://x", "image_link": "http://x.jpg", "availability": "in_stock", "price": "10 USD", "condition": "new"}
    findings = await rule.check(product, _make_ctx())
    assert findings == []


# -- BrandRequired --

async def test_brand_required_exempts_books():
    rule = BrandRequired()
    product = {"google_product_category": 784}
    findings = await rule.check(product, _make_ctx())
    assert findings == []


async def test_brand_required_warns_when_missing():
    rule = BrandRequired()
    findings = await rule.check({}, _make_ctx())
    assert len(findings) == 1
    assert findings[0].severity == "warning"


# -- GtinMpn --

async def test_gtin_valid_checksum():
    rule = GtinMpn()
    product = {"gtin": "0012345678905"}  # valid GS1
    findings = await rule.check(product, _make_ctx())
    assert findings == []


async def test_gtin_invalid_checksum():
    rule = GtinMpn()
    product = {"gtin": "0012345678900"}
    findings = await rule.check(product, _make_ctx())
    assert len(findings) == 1
    assert findings[0].severity == "critical"


async def test_gtin_missing_requires_mpn_brand():
    rule = GtinMpn()
    findings = await rule.check({}, _make_ctx())
    assert len(findings) == 1
    assert findings[0].severity == "warning"


# -- EnumValues --

async def test_enum_values_invalid():
    rule = EnumValues()
    registry = RegistryDocument(attributes={
        "availability": AttributeInfo(type="enumeration", enum_values=["in_stock", "out_of_stock"]),
    })
    ctx = _make_ctx(registry=registry)
    findings = await rule.check({"availability": "maybe"}, ctx)
    assert len(findings) == 1


# -- ConditionalRequired --

async def test_conditional_preorder_needs_date():
    rule = ConditionalRequired()
    findings = await rule.check({"availability": "preorder"}, _make_ctx())
    assert len(findings) == 1


# -- DateFormat --

async def test_date_format_missing_timezone():
    rule = DateFormat()
    findings = await rule.check({"availability_date": "2026-01-15"}, _make_ctx())
    assert len(findings) == 1
    assert "timezone" in findings[0].message


async def test_date_format_valid():
    rule = DateFormat()
    findings = await rule.check({"availability_date": "2026-01-15T00:00:00+00:00"}, _make_ctx())
    assert findings == []


# -- LengthLimits --

async def test_length_limits_exceeds():
    rule = LengthLimits()
    registry = RegistryDocument(attributes={
        "title": AttributeInfo(type="string", constraints=Constraints(max_length=10)),
    })
    ctx = _make_ctx(registry=registry)
    findings = await rule.check({"title": "a" * 11}, ctx)
    assert len(findings) == 1


# -- CardinalityRule --

async def test_cardinality_max_exceeded():
    rule = CardinalityRule()
    registry = RegistryDocument(attributes={
        "color": AttributeInfo(type="enumeration", cardinality=Cardinality(max_items=3)),
    })
    ctx = _make_ctx(registry=registry)
    findings = await rule.check({"color": ["a", "b", "c", "d"]}, ctx)
    assert len(findings) == 1


async def test_cardinality_item_max_length():
    rule = CardinalityRule()
    registry = RegistryDocument(attributes={
        "highlight": AttributeInfo(type="enumeration", cardinality=Cardinality(max_items=5, item_max_length=10)),
    })
    ctx = _make_ctx(registry=registry)
    findings = await rule.check({"highlight": ["short", "this is way too long"]}, ctx)
    assert len(findings) == 1
    assert findings[0].field == "highlight.2"


# -- CurrencyConsistency --

async def test_currency_mismatch():
    rule = CurrencyConsistency()
    findings = await rule.check({"price": "10 EUR"}, _make_ctx(currency="USD"))
    assert len(findings) == 1
    assert findings[0].severity == "critical"


# -- ImageRequirements --

async def test_image_requirements_too_small():
    probe = AsyncMock()
    probe.probe.return_value = (200, 200, None)
    rule = ImageRequirements()
    ctx = _make_ctx(image_probe=probe)
    findings = await rule.check({"image_link": "http://example.com/img.jpg"}, ctx)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


async def test_image_requirements_before_enforcement():
    probe = AsyncMock()
    probe.probe.return_value = (200, 200, None)
    rule = ImageRequirements()
    clock = TestClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    ctx = _make_ctx(image_probe=probe, clock=clock)
    findings = await rule.check({"image_link": "http://example.com/img.jpg"}, ctx)
    assert findings[0].severity == "warning"


async def test_image_requirements_after_enforcement():
    probe = AsyncMock()
    probe.probe.return_value = (200, 200, None)
    rule = ImageRequirements()
    clock = TestClock(datetime(2027, 2, 1, tzinfo=timezone.utc))
    ctx = _make_ctx(image_probe=probe, clock=clock)
    findings = await rule.check({"image_link": "http://example.com/img.jpg"}, ctx)
    assert findings[0].severity == "critical"


# -- VariantConsistency --

async def test_variant_consistency_inconsistent():
    rule = VariantConsistency()
    products = [
        {"item_group_id": "G1", "title": "A"},
        {"item_group_id": "G1", "title": "B"},
    ]
    findings = await rule.check(products, _make_ctx())
    assert len(findings) == 1


# -- VolumeDrop --

async def test_volume_drop_fires():
    rule = VolumeDrop()
    prev = type("Prev", (), {"product_count": 100})()
    ctx = _make_ctx(previous_export_run=prev)
    products = [{"id": str(i)} for i in range(70)]
    findings = await rule.check(products, ctx)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


async def test_volume_drop_skipped_without_prior():
    rule = VolumeDrop()
    findings = await rule.check([{"id": "1"}], _make_ctx())
    assert findings == []
```

- [ ] **Step 3: Run rule tests**

Run: `cd backend && python -m pytest tests/test_qc_rules.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/qc/rules.py backend/tests/test_qc_rules.py
git commit -m "feat(qc): implement all 12 QC rules"
```

---

### Task 7: Image Probe — Pillow + Cache

**Goal:** Implement `ImageProbe` with httpx fetch, Pillow dimension parsing, and DB-backed cache.

**Files:**
- Create: `backend/app/qc/image_probe.py`
- Create: `backend/tests/test_image_probe.py`

#### Steps

- [ ] **Step 1: Create image probe implementation**

```python
# backend/app/qc/image_probe.py
from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from typing import Protocol

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.image_dimension import ImageDimension
from .constants import IMAGE_FETCH_CAP_BYTES, IMAGE_CONCURRENCY

logger = logging.getLogger(__name__)


class ImageProbeImpl:
    def __init__(self, session_factory, client: httpx.AsyncClient) -> None:
        self._session_factory = session_factory
        self._client = client
        self._semaphore = asyncio.Semaphore(IMAGE_CONCURRENCY)

    async def probe(self, url: str) -> tuple[int | None, int | None, str | None]:
        async with self._session_factory() as session:
            cached = await session.execute(
                select(ImageDimension).where(ImageDimension.url == url)
            )
            row = cached.scalar_one_or_none()
            if row is not None:
                if row.fetch_error:
                    return None, None, row.fetch_error
                return row.width, row.height, None

        async with self._semaphore:
            try:
                response = await self._client.get(
                    url,
                    headers={"User-Agent": "GMC-Feed-Engine/1.0"},
                    follow_redirects=True,
                    timeout=30.0,
                )
                response.raise_for_status()

                content_length = int(response.headers.get("content-length", 0))
                if content_length > IMAGE_FETCH_CAP_BYTES:
                    error = f"image too large: {content_length} bytes"
                    await self._cache_error(url, error)
                    return None, None, error

                body = response.content[:IMAGE_FETCH_CAP_BYTES]
                img = Image.open(BytesIO(body))
                width, height = img.size

                await self._cache_dimensions(url, width, height)
                return width, height, None

            except httpx.HTTPStatusError as e:
                error = f"HTTP {e.response.status_code}"
                await self._cache_error(url, error)
                return None, None, error
            except Exception as e:
                error = str(e)[:500]
                await self._cache_error(url, error)
                return None, None, error

    async def _cache_dimensions(self, url: str, width: int, height: int) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                row = ImageDimension(url=url, width=width, height=height)
                session.add(row)

    async def _cache_error(self, url: str, error: str) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                row = ImageDimension(url=url, fetch_error=error)
                session.add(row)
```

- [ ] **Step 2: Write image probe tests**

```python
# backend/tests/test_image_probe.py
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock
from app.qc.image_probe import ImageProbeImpl
from app.models.image_dimension import ImageDimension

pytestmark = pytest.mark.asyncio


class FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, responses):
        self._responses = responses

    async def handle_async_request(self, request):
        url = str(request.url)
        if url in self._responses:
            status, headers, body = self._responses[url]
            return httpx.Response(status, headers=headers, content=body)
        return httpx.Response(404)


def _make_jpeg_bytes(width=100, height=100):
    from PIL import Image
    from io import BytesIO
    buf = BytesIO()
    Image.new("RGB", (width, height)).save(buf, format="JPEG")
    return buf.getvalue()


async def test_probe_cache_hit():
    session_factory = AsyncMock()
    mock_session = AsyncMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    cached = ImageDimension(url="http://example.com/img.jpg", width=800, height=600)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = cached
    mock_session.execute = AsyncMock(return_value=mock_result)

    client = httpx.AsyncClient()
    probe = ImageProbeImpl(session_factory, client)
    width, height, error = await probe.probe("http://example.com/img.jpg")
    assert width == 800
    assert height == 600
    assert error is None


async def test_probe_fetch_success():
    jpeg = _make_jpeg_bytes(200, 150)
    transport = FakeTransport({
        "http://example.com/img.jpg": (200, {"content-length": str(len(jpeg))}, jpeg),
    })
    client = httpx.AsyncClient(transport=transport)

    session_factory = AsyncMock()
    mock_session = AsyncMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    # Cache miss
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    probe = ImageProbeImpl(session_factory, client)
    width, height, error = await probe.probe("http://example.com/img.jpg")
    assert width == 200
    assert height == 150
    assert error is None


async def test_probe_http_error():
    transport = FakeTransport({})
    client = httpx.AsyncClient(transport=transport)

    session_factory = AsyncMock()
    mock_session = AsyncMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    probe = ImageProbeImpl(session_factory, client)
    width, height, error = await probe.probe("http://example.com/missing.jpg")
    assert width is None
    assert height is None
    assert error is not None
```

- [ ] **Step 3: Run image probe tests**

Run: `cd backend && python -m pytest tests/test_image_probe.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/qc/image_probe.py backend/tests/test_image_probe.py
git commit -m "feat(qc): image probe with Pillow and DB cache"
```

---

### Task 8: QC Persistence — Feed-Keyed Replace + ExportRun

**Goal:** Implement `persist_findings()` with feed-keyed delete/insert semantics and ExportRun creation.

**Files:**
- Create: `backend/app/qc/persistence.py`
- Create: (test embedded in Task 10 integration tests)

#### Steps

- [ ] **Step 1: Create persistence module**

```python
# backend/app/qc/persistence.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.export import ExportRun
from ..models.quality import QualityFinding
from .engine import Finding


async def persist_findings(
    session_factory: Callable[[], AsyncSession],
    feed_source_id: int,
    ingestion_run_id: int,
    findings: list[Finding],
    product_count: int,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            # Feed-keyed delete
            await session.execute(
                delete(QualityFinding).where(QualityFinding.feed_source_id == feed_source_id)
            )

            # Insert findings (product_id already attached by engine)
            for finding in findings:
                session.add(QualityFinding(
                    feed_source_id=feed_source_id,
                    ingestion_run_id=ingestion_run_id,
                    product_id=finding.product_id or "cross_product",
                    severity=finding.severity,
                    code=finding.rule_id,
                    field=finding.field,
                    message=finding.message,
                    details=finding.details,
                ))

            # Count by severity
            counts = {"critical": 0, "warning": 0, "info": 0}
            for f in findings:
                counts[f.severity] = counts.get(f.severity, 0) + 1

            # Write ExportRun
            session.add(ExportRun(
                feed_source_id=feed_source_id,
                ingestion_run_id=ingestion_run_id,
                status="completed",
                product_count=product_count,
                critical_finding_count=counts["critical"],
                warning_finding_count=counts["warning"],
                info_finding_count=counts["info"],
                export_version_id=None,
            ))
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/qc/persistence.py
git commit -m "feat(qc): persistence layer with feed-keyed replace semantics"
```

---

### Task 9: QualityCheckStep — Wire Into Pipeline

**Goal:** Replace the `QualityCheckStep` no-op with the real implementation and extend `default_steps`.

**Files:**
- Modify: `backend/app/pipeline/steps.py`
- Modify: `backend/tests/test_pipeline_steps.py`

#### Steps

- [ ] **Step 1: Replace `QualityCheckStep` no-op**

```python
# backend/app/pipeline/steps.py — replace QualityCheckStep class
class QualityCheckStep:
    name = "quality_check"

    def __init__(
        self,
        registry: RegistryDocument,
        clock: Clock,
        image_probe: ImageProbe,
    ) -> None:
        self._registry = registry
        self._clock = clock
        self._image_probe = image_probe

    async def execute(self, ctx: StepContext) -> StepResult:
        async with ctx.session_factory() as session:
            async with session.begin():
                feed_source = await session.get(FeedSource, ctx.feed_source_id)

        if feed_source is None:
            raise LookupError(f"feed source {ctx.feed_source_id} not found")

        # Load active staged products
        async with ctx.session_factory() as session:
            from sqlalchemy import select
            from ..models.staging import StagingProduct
            result = await session.execute(
                select(StagingProduct).where(
                    StagingProduct.feed_source_id == ctx.feed_source_id,
                    StagingProduct.status == "active",
                    StagingProduct.excluded == False,
                )
            )
            rows = list(result.scalars().all())

        products = []
        product_ids = []
        for row in rows:
            product = row.processed_data if row.processed_data is not None else row.raw_data
            products.append(product)
            product_ids.append(row.product_id)

        # Load previous ExportRun for volume drop
        async with ctx.session_factory() as session:
            from sqlalchemy import select, desc
            from ..models.export import ExportRun
            result = await session.execute(
                select(ExportRun).where(
                    ExportRun.feed_source_id == ctx.feed_source_id
                ).order_by(desc(ExportRun.id)).limit(1)
            )
            previous_export_run = result.scalar_one_or_none()

        from ..qc.engine import QcContext, run_engine
        from ..qc.rules import (
            BaselineRequired, BrandRequired, GtinMpn, EnumValues,
            ConditionalRequired, DateFormat, LengthLimits, CardinalityRule,
            CurrencyConsistency, ImageRequirements, VariantConsistency, VolumeDrop,
        )
        from ..qc.persistence import persist_findings

        qc_ctx = QcContext(
            feed_source_id=ctx.feed_source_id,
            currency=feed_source.currency,
            volume_drop_threshold_pct=feed_source.volume_drop_threshold_pct,
            registry=self._registry,
            clock=self._clock,
            image_probe=self._image_probe,
            previous_export_run=previous_export_run,
        )

        per_product_rules = [
            BaselineRequired(), BrandRequired(), GtinMpn(), EnumValues(),
            ConditionalRequired(), DateFormat(), LengthLimits(), CardinalityRule(),
            CurrencyConsistency(), ImageRequirements(),
        ]
        cross_product_rules = [VariantConsistency(), VolumeDrop()]

        findings = await run_engine(products, product_ids, qc_ctx, per_product_rules, cross_product_rules)

        await persist_findings(
            ctx.session_factory,
            ctx.feed_source_id,
            ctx.ingestion_run_id,
            findings,
            len(products),
        )

        counts = {"critical": 0, "warning": 0, "info": 0}
        for f in findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1

        return StepResult(
            processed_count=len(products),
            statistics={"qc": {"products": len(products), **counts}},
        )
```

- [ ] **Step 2: Update `default_steps` signature**

```python
# backend/app/pipeline/steps.py — default_steps function
def default_steps(
    fetcher: HttpFetcher,
    registry: RegistryDocument,
    plugin_registry: dict[str, Any] | None = None,
    clock: Clock | None = None,
    image_probe: ImageProbe | None = None,
) -> tuple[PipelineStep, ...]:
    from ..clock import SystemClock
    if clock is None:
        clock = SystemClock()
    return (
        IngestStep(fetcher, registry),
        MappingStep(registry),
        StagingStep(),
        PluginStep(plugin_registry),
        QualityCheckStep(registry, clock, image_probe),
        ExportStep(),
    )
```

- [ ] **Step 3: Update `test_pipeline_steps.py` — no-op test**

```python
# backend/tests/test_pipeline_steps.py — update the no-op test
# The QualityCheckStep is no longer a no-op, so update the test
# that asserts it's in the step list. The step order test should still pass.
# Remove the QualityCheckStep from the no-op assertion or update it.
```

- [ ] **Step 4: Update imports in `steps.py`**

Add to the top of `steps.py`:
```python
from ..clock import Clock
from ..qc.engine import ImageProbe
```

- [ ] **Step 5: Run pipeline step tests**

Run: `cd backend && python -m pytest tests/test_pipeline_steps.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/steps.py backend/tests/test_pipeline_steps.py
git commit -m "feat(pipeline): replace QualityCheckStep no-op with real implementation"
```

---

### Task 10: API Endpoint — GET /feed-sources/{id}/quality-findings

**Goal:** Implement the quality findings API endpoint.

**Files:**
- Create: `backend/app/routes/quality.py`
- Modify: `backend/app/routes/__init__.py`
- Create: `backend/tests/test_quality_api.py`

#### Steps

- [ ] **Step 1: Create quality router**

```python
# backend/app/routes/quality.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..db.session import get_session
from ..models.feed_source import FeedSource
from ..models.quality import QualityFinding
from ..models.export import ExportRun

router = APIRouter()


@router.get("/feed-sources/{feed_source_id}/quality-findings")
async def get_quality_findings(
    feed_source_id: int,
    session: AsyncSession = Depends(get_session),
    _user=Depends(get_current_user),
):
    # Verify feed source exists
    feed_source = await session.get(FeedSource, feed_source_id)
    if feed_source is None:
        raise HTTPException(status_code=404, detail="feed source not found")

    # Get latest ExportRun for this feed source
    result = await session.execute(
        select(ExportRun).where(
            ExportRun.feed_source_id == feed_source_id
        ).order_by(desc(ExportRun.id)).limit(1)
    )
    export_run = result.scalar_one_or_none()

    if export_run is None:
        return {
            "ingestion_run_id": None,
            "counts": {"critical": 0, "warning": 0, "info": 0},
            "findings": [],
        }

    # Get findings for this feed source
    result = await session.execute(
        select(QualityFinding).where(
            QualityFinding.feed_source_id == feed_source_id
        ).order_by(QualityFinding.id)
    )
    rows = list(result.scalars().all())

    findings = [
        {
            "severity": row.severity,
            "code": row.code,
            "field": row.field,
            "message": row.message,
            "product_id": row.product_id,
            "details": row.details,
        }
        for row in rows
    ]

    return {
        "ingestion_run_id": export_run.ingestion_run_id,
        "counts": {
            "critical": export_run.critical_finding_count,
            "warning": export_run.warning_finding_count,
            "info": export_run.info_finding_count,
        },
        "findings": findings,
    }
```

- [ ] **Step 2: Register the router in `__init__.py`**

```python
# backend/app/routes/__init__.py — add import and export
from .quality import router as quality_router
```

- [ ] **Step 3: Include router in `main.py`**

```python
# backend/app/main.py — add after other router includes
from .routes.quality import router as quality_router
app.include_router(quality_router)
```

- [ ] **Step 4: Write API tests**

```python
# backend/tests/test_quality_api.py
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, FeedSource, IngestionRun, ExportRun, QualityFinding
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(QualityFinding))
            await session.execute(delete(ExportRun))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="pw",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _seed_feed_source(app_factory):
    _, factory = app_factory
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id,
                name="Main feed",
                source_format="tsv",
                source_url="http://test.local/feed.tsv",
                configuration={},
            )
            session.add(feed_source)
            await session.flush()
            return client.id, feed_source.id


async def test_404_for_missing_feed_source(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/feed-sources/9999/quality-findings")
    assert resp.status_code == 404


async def test_empty_result_when_no_qc_run(app_factory):
    _, feed_source_id = await _seed_feed_source(app_factory)
    client = await logged_in_client(app_factory)
    resp = await client.get(f"/feed-sources/{feed_source_id}/quality-findings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["counts"] == {"critical": 0, "warning": 0, "info": 0}
    assert data["findings"] == []


async def test_returns_findings(app_factory):
    _, factory = app_factory
    _, feed_source_id = await _seed_feed_source(app_factory)

    async with factory() as session:
        async with session.begin():
            export_run = ExportRun(
                feed_source_id=feed_source_id,
                status="completed",
                product_count=5,
                critical_finding_count=1,
                warning_finding_count=2,
                info_finding_count=0,
            )
            session.add(export_run)
            await session.flush()

            finding = QualityFinding(
                feed_source_id=feed_source_id,
                ingestion_run_id=1,
                product_id="SKU-1",
                severity="critical",
                code="enum_values",
                field="availability",
                message="invalid value",
                details={},
            )
            session.add(finding)

    client = await logged_in_client(app_factory)
    resp = await client.get(f"/feed-sources/{feed_source_id}/quality-findings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["counts"]["critical"] == 1
    assert data["counts"]["warning"] == 2
    assert len(data["findings"]) == 1
    assert data["findings"][0]["code"] == "enum_values"
```

- [ ] **Step 5: Run API tests**

Run: `cd backend && python -m pytest tests/test_quality_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/quality.py backend/app/routes/__init__.py backend/app/main.py backend/tests/test_quality_api.py
git commit -m "feat(api): GET /feed-sources/{id}/quality-findings endpoint"
```

---

### Task 11: Acceptance Gate — End-to-End Test

**Goal:** Create `test_m7_acceptance.py` following the M5/M6 pattern.

**Files:**
- Create: `backend/tests/test_m7_acceptance.py`

#### Steps

- [ ] **Step 1: Create acceptance test**

```python
# backend/tests/test_m7_acceptance.py
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, FeedSource, IngestionRun, ExportRun, QualityFinding
from app.models.staging import StagingProduct
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(QualityFinding))
            await session.execute(delete(ExportRun))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="pw",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory, engine
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _seed_feed_source(app_factory):
    _, factory, _ = app_factory
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id,
                name="Main feed",
                source_format="tsv",
                source_url="http://test.local/feed.tsv",
                configuration={},
            )
            session.add(feed_source)
            await session.flush()
            return client.id, feed_source.id


async def test_end_to_end_qc_finds_issues(app_factory):
    _, factory, _ = app_factory
    _, feed_source_id = await _seed_feed_source(app_factory)

    # Seed staging products with QC issues
    async with factory() as session:
        async with session.begin():
            ingestion_run = IngestionRun(
                feed_source_id=feed_source_id,
                status="completed",
                processed_count=3,
                failed_count=0,
            )
            session.add(ingestion_run)
            await session.flush()

            products = [
                {
                    "id": "SKU-1",
                    "title": "Good Product",
                    "description": "A product",
                    "link": "http://example.com/1",
                    "image_link": "http://example.com/1.jpg",
                    "availability": "in_stock",
                    "price": "10 USD",
                    "condition": "new",
                    "brand": "Acme",
                    "gtin": "0012345678905",
                },
                {
                    "id": "SKU-2",
                    "description": "Missing title",
                    "link": "http://example.com/2",
                    "image_link": "http://example.com/2.jpg",
                    "availability": "in_stock",
                    "price": "20 USD",
                    "condition": "new",
                },
                {
                    "id": "SKU-3",
                    "title": "Bad Enum",
                    "description": "Product",
                    "link": "http://example.com/3",
                    "image_link": "http://example.com/3.jpg",
                    "availability": "invalid_status",
                    "price": "30 EUR",
                    "condition": "new",
                    "brand": "Widget",
                },
            ]

            for product in products:
                row = StagingProduct(
                    feed_source_id=feed_source_id,
                    ingestion_run_id=ingestion_run.id,
                    product_id=product["id"],
                    content_hash="abc",
                    config_hash="def",
                    status="active",
                    raw_data=product,
                    processed_data=product,
                )
                session.add(row)

    client = await logged_in_client(app_factory)

    # Verify findings exist
    resp = await client.get(f"/feed-sources/{feed_source_id}/quality-findings")
    assert resp.status_code == 200
    data = resp.json()

    # Should have findings for SKU-2 (missing title) and SKU-3 (invalid enum + currency)
    assert data["counts"]["critical"] >= 1
    assert data["counts"]["warning"] >= 1
    assert len(data["findings"]) >= 2

    # Verify ExportRun was created
    async with factory() as session:
        result = await session.execute(
            select(ExportRun).where(ExportRun.feed_source_id == feed_source_id)
        )
        export_runs = list(result.scalars().all())
        assert len(export_runs) == 1
        assert export_runs[0].status == "completed"
        assert export_runs[0].product_count == 3
        assert export_runs[0].critical_finding_count >= 1
```

- [ ] **Step 2: Run acceptance test**

Run: `cd backend && python -m pytest tests/test_m7_acceptance.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_m7_acceptance.py
git commit -m "test: M7 acceptance gate"
```

---

### Task 12: Final Verification

**Goal:** Run the full test suite and verify CI gates.

#### Steps

- [ ] **Step 1: Run full test suite**

Run: `cd backend && python -m pytest -x -v`
Expected: ALL PASS

- [ ] **Step 2: Run registry check gate**

Run: `cd backend && python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json --check`
Expected: PASS (gate green)

- [ ] **Step 3: Run Alembic upgrade head**

Run: `cd backend && alembic upgrade head`
Expected: No errors

- [ ] **Step 4: Verify Python compilation**

Run: `cd backend && python -m compileall app/ -q`
Expected: No errors

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address review feedback for M7"
```

---

## Spec Coverage Checklist

| Spec Section | Task |
|---|---|
| §7 QC rule set (12 rules) | Task 6 |
| §4 QualityFinding/ExportRun semantics | Task 4, Task 8 |
| §8 GET /feed-sources/{id}/quality-findings | Task 10 |
| Registry extension (min_items, item_max_length) | Task 1 |
| Image probe (Pillow, cache, concurrency) | Task 7 |
| Migrations (rename, new table, new columns) | Task 3 |
| QualityCheckStep wiring | Task 9 |
| Acceptance gate | Task 11 |
| docs/decisions.md verification | Already verified (lines 469–510 complete) |
