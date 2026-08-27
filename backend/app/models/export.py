from datetime import datetime
from typing import Any
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


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


class ExportVersion(Base):
    __tablename__ = "export_versions"
    __table_args__ = (
        UniqueConstraint("feed_source_id", "version_number", name="uq_export_versions_source_version"),
        Index("ix_export_versions_feed_source_id", "feed_source_id"),
        Index("ix_export_versions_export_run_id", "export_run_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed_source_id: Mapped[int] = mapped_column(ForeignKey("feed_sources.id", ondelete="RESTRICT"), nullable=False)
    export_run_id: Mapped[int] = mapped_column(ForeignKey("export_runs.id", ondelete="RESTRICT"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
