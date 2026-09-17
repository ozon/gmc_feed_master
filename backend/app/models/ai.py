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
    Text,
    UniqueConstraint,
    func,
    text,
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
    tier: Mapped[str] = mapped_column(String(20), nullable=False, default="bulk", server_default="bulk")
    input_price_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    output_price_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


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
    provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        Index(
            "uq_prompt_templates_global_version", "task_type", "version",
            unique=True, postgresql_where=text("client_id IS NULL"),
        ),
        Index(
            "uq_prompt_templates_client_version", "task_type", "client_id", "version",
            unique=True, postgresql_where=text("client_id IS NOT NULL"),
        ),
        Index(
            "uq_prompt_templates_global_active", "task_type",
            unique=True, postgresql_where=text("is_active AND client_id IS NULL"),
        ),
        Index(
            "uq_prompt_templates_client_active", "task_type", "client_id",
            unique=True, postgresql_where=text("is_active AND client_id IS NOT NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AiModelCatalog(Base):
    __tablename__ = "ai_model_catalog"
    __table_args__ = (
        UniqueConstraint("model_id", name="uq_ai_model_catalog_model_id"),
        Index("ix_ai_model_catalog_vendor_mode", "vendor", "mode"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor: Mapped[str] = mapped_column(String(50), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="chat", server_default="chat")
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_price_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    output_price_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    supports_vision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    supports_function_calling: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))


class AiModelCatalogSync(Base):
    __tablename__ = "ai_model_catalog_sync"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
