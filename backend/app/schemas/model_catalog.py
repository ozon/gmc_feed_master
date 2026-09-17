"""Pydantic schemas for the model catalog and provider preset endpoints (GFM-12)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ProviderPresetOut(BaseModel):
    vendor_key: str
    label: str
    model_prefix: str
    default_base_url: str
    requires_base_url: bool
    requires_api_version: bool
    api_key_docs_url: str
    description: str
    is_custom: bool


class ModelCatalogEntryOut(BaseModel):
    model_id: str
    vendor: str
    display_name: str
    context_window: int | None
    max_output_tokens: int | None
    input_price_per_mtok: float | None
    output_price_per_mtok: float | None
    supports_vision: bool
    supports_function_calling: bool
    is_recommended: bool

    model_config = {"from_attributes": True}


class ModelCatalogStatusOut(BaseModel):
    source: str
    last_synced_at: datetime | None


class ModelCatalogRefreshOut(BaseModel):
    synced_count: int
    skipped_count: int
    source: str
    synced_at: datetime
    error: str | None
