from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GlobalSetting(Base):
    __tablename__ = "global_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    staging_removal_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    staging_history_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    ingestion_run_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    ai_usage_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    ai_cache_type: Mapped[str] = mapped_column(String(20), nullable=False, default="local", server_default="local")
    ai_cache_namespace: Mapped[str] = mapped_column(String(100), nullable=False, default="gmc-ai", server_default="gmc-ai")
    ai_cache_ttl_taxonomy_s: Mapped[int] = mapped_column(Integer, nullable=False, default=2592000, server_default="2592000")
    ai_cache_ttl_content_s: Mapped[int] = mapped_column(Integer, nullable=False, default=604800, server_default="604800")
    ai_router_timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    ai_router_num_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    ai_router_allowed_fails: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    ai_router_cooldown_s: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    ai_instructor_max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
