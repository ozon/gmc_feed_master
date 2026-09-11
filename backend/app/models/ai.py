from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AiProviderConfig(Base):
    __tablename__ = "ai_provider_configs"
    __table_args__ = (UniqueConstraint("name", name="uq_ai_provider_configs_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False, default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    api_key: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    input_price_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    output_price_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AiResultCache(Base):
    __tablename__ = "ai_result_cache"
    __table_args__ = (
        UniqueConstraint(
            "task_type", "provider_config_id", "model", "template_version", "input_hash",
            name="uq_ai_result_cache_key",
        ),
        Index("ix_ai_result_cache_input_hash", "input_hash"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_config_id: Mapped[int] = mapped_column(ForeignKey("ai_provider_configs.id", ondelete="CASCADE"), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    template_version: Mapped[str] = mapped_column(String(100), nullable=False, default="builtin")
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AiUsageLog(Base):
    __tablename__ = "ai_usage_logs"
    __table_args__ = (
        Index("ix_ai_usage_logs_client_id", "client_id"),
        Index("ix_ai_usage_logs_feed_source_id", "feed_source_id"),
        Index("ix_ai_usage_logs_created_at", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feed_source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_config_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
