from datetime import datetime
from typing import Any
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class StagingProduct(Base):
    __tablename__ = "staging_products"
    __table_args__ = (UniqueConstraint("feed_source_id", "product_id", name="uq_staging_products_source_product"), Index("ix_staging_products_feed_source_id", "feed_source_id"), Index("ix_staging_products_ingestion_run_id", "ingestion_run_id"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed_source_id: Mapped[int] = mapped_column(ForeignKey("feed_sources.id", ondelete="RESTRICT"), nullable=False)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="RESTRICT"), nullable=False)
    product_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class StagingHistory(Base):
    __tablename__ = "staging_history"
    __table_args__ = (Index("ix_staging_history_staging_product_id", "staging_product_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    staging_product_id: Mapped[int] = mapped_column(ForeignKey("staging_products.id", ondelete="CASCADE"), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
