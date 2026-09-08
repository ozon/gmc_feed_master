from datetime import datetime
from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class GlobalSetting(Base):
    __tablename__ = "global_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    staging_removal_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    staging_history_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    ingestion_run_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
