"""ORM model for the AI model catalog (GFM-12).

Populated by `app.ai.model_catalog.refresh_model_catalog` from LiteLLM's
model-prices registry; read by the AI Provider Configuration wizard's
model-selection step.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AiModelCatalog(Base):
    __tablename__ = "ai_model_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    vendor: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_price_per_mtok: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_price_per_mtok: Mapped[float | None] = mapped_column(Float, nullable=True)
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_function_calling: Mapped[bool] = mapped_column(Boolean, default=False)
    is_recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(512))
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
