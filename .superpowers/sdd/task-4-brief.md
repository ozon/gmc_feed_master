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

