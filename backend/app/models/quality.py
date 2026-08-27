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
