from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class EventLog(Base):
    __tablename__ = "event_log"
    __table_args__ = (
        Index("ix_event_log_created_at", "created_at"),
        Index("ix_event_log_category_created_at", "category", "created_at"),
        Index("ix_event_log_request_id", "request_id"),
        Index("ix_event_log_feed_source_id", "feed_source_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    logger: Mapped[str | None] = mapped_column(String(120), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    client_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feed_source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
