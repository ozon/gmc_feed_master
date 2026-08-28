from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    contact_details: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="active", min_length=1, max_length=50)


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, max_length=50)
    contact_details: dict[str, Any] | None = None


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    contact_details: dict[str, Any]
    status: str
    created_at: datetime


class FeedSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_format: Literal["xml", "tsv", "csv", "wide_tsv"]
    cron_expression: str | None = Field(default=None, max_length=100)
    target_country: str | None = Field(default=None, max_length=10)
    target_language: str | None = Field(default=None, max_length=10)
    currency: str | None = Field(default=None, max_length=3)
    source_url: str | None = Field(default=None, max_length=2048)


class FeedSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    source_format: Literal["xml", "tsv", "csv", "wide_tsv"] | None = None
    cron_expression: str | None = Field(default=None, max_length=100)
    target_country: str | None = Field(default=None, max_length=10)
    target_language: str | None = Field(default=None, max_length=10)
    currency: str | None = Field(default=None, max_length=3)
    source_url: str | None = Field(default=None, max_length=2048)
    history_retention_count: int | None = Field(default=None, ge=1)
    volume_drop_threshold_pct: int | None = Field(default=None, ge=0, le=100)
    configuration: dict[str, Any] | None = None


class FeedSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    name: str
    source_format: str
    cron_expression: str | None
    target_country: str | None
    target_language: str | None
    currency: str | None
    source_url: str | None
    feed_type: str
    history_retention_count: int
    volume_drop_threshold_pct: int
    configuration: dict[str, Any]
    export_url: str = ""
    created_at: datetime
    updated_at: datetime


class IngestionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    started_at: datetime
    completed_at: datetime | None
    processed_count: int
    failed_count: int
    error_message: str | None
    statistics: dict[str, Any]
