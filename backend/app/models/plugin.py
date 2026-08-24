from datetime import datetime
from typing import Any
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class Plugin(Base):
    __tablename__ = "plugins"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_plugins_name_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PluginConfig(Base):
    __tablename__ = "plugin_configs"
    __table_args__ = (
        UniqueConstraint("plugin_id", "key", name="uq_plugin_configs_plugin_key"),
        Index("ix_plugin_configs_plugin_id", "plugin_id"),
        Index("ix_plugin_configs_client_id", "client_id"),
        Index("ix_plugin_configs_feed_source_id", "feed_source_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plugin_id: Mapped[int] = mapped_column(ForeignKey("plugins.id", ondelete="RESTRICT"), nullable=False)
    scope: Mapped[str] = mapped_column(String(50), nullable=False)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"))
    feed_source_id: Mapped[int | None] = mapped_column(ForeignKey("feed_sources.id", ondelete="RESTRICT"))
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class PluginData(Base):
    __tablename__ = "plugin_data"
    __table_args__ = (
        Index("ix_plugin_data_plugin_id", "plugin_id"),
        Index("ix_plugin_data_client_id", "client_id"),
        Index("ix_plugin_data_feed_source_id", "feed_source_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plugin_id: Mapped[int] = mapped_column(ForeignKey("plugins.id", ondelete="RESTRICT"), nullable=False)
    scope: Mapped[str] = mapped_column(String(50), nullable=False)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"))
    feed_source_id: Mapped[int | None] = mapped_column(ForeignKey("feed_sources.id", ondelete="RESTRICT"))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
