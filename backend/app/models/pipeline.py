from __future__ import annotations

from datetime import datetime
from typing import Any
from typing import TYPE_CHECKING
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from .feed_source import FeedSource


class ModulePipeline(Base):
    __tablename__ = "module_pipelines"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_module_pipelines_name_version"), Index("ix_module_pipelines_feed_source_id", "feed_source_id"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed_source_id: Mapped[int] = mapped_column(ForeignKey("feed_sources.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    feed_source: Mapped["FeedSource"] = relationship(
        "FeedSource", back_populates="pipelines", foreign_keys=[feed_source_id]
    )
    active_for_feed_source: Mapped["FeedSource | None"] = relationship(
        "FeedSource", back_populates="active_pipeline", foreign_keys="FeedSource.active_pipeline_id", uselist=False
    )


class ModuleInstance(Base):
    __tablename__ = "module_instances"
    __table_args__ = (Index("ix_module_instances_pipeline_id", "pipeline_id"), Index("ix_module_instances_plugin_id", "plugin_id"), UniqueConstraint("pipeline_id", "position", name="uq_module_instances_pipeline_position"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("module_pipelines.id", ondelete="RESTRICT"), nullable=False)
    plugin_id: Mapped[int] = mapped_column(ForeignKey("plugins.id", ondelete="RESTRICT"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
