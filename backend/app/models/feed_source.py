from __future__ import annotations

from datetime import datetime
from typing import Any
from typing import TYPE_CHECKING
from sqlalchemy import DateTime, ForeignKey, Integer, String, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from .pipeline import ModulePipeline


class FeedSource(Base):
    __tablename__ = "feed_sources"
    __table_args__ = (Index("ix_feed_sources_client_id", "client_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False)
    active_pipeline_id: Mapped[int | None] = mapped_column(
        ForeignKey("module_pipelines.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    field_mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    pipelines: Mapped[list["ModulePipeline"]] = relationship(
        "ModulePipeline", back_populates="feed_source", foreign_keys="ModulePipeline.feed_source_id"
    )
    active_pipeline: Mapped["ModulePipeline | None"] = relationship(
        "ModulePipeline", back_populates="active_for_feed_source", foreign_keys=[active_pipeline_id], uselist=False
    )
