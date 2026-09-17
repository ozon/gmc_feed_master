from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AiProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider_type: str
    base_url: str
    model: str
    tier: str
    input_price_per_mtok: Decimal | None
    output_price_per_mtok: Decimal | None
    max_concurrency: int
    timeout_s: int
    enabled: bool


class AiProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    provider_type: Literal["litellm", "openai_compatible"] = "litellm"
    base_url: str = Field(default="", max_length=1024)
    api_key: str = Field(default="", max_length=1024)
    model: str = Field(min_length=1, max_length=255)
    tier: Literal["bulk", "precision"] = "bulk"
    input_price_per_mtok: Decimal | None = None
    output_price_per_mtok: Decimal | None = None
    max_concurrency: int = Field(default=4, ge=1, le=64)
    timeout_s: int = Field(default=30, ge=1, le=600)
    enabled: bool = True


class AiProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    provider_type: Literal["litellm", "openai_compatible"] | None = None
    base_url: str | None = Field(default=None, max_length=1024)
    api_key: str | None = Field(default=None, max_length=1024)
    model: str | None = Field(default=None, min_length=1, max_length=255)
    tier: Literal["bulk", "precision"] | None = None
    input_price_per_mtok: Decimal | None = None
    output_price_per_mtok: Decimal | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=64)
    timeout_s: int | None = Field(default=None, ge=1, le=600)
    enabled: bool | None = None


class PromptTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_type: str
    client_id: int | None
    version: int
    name: str
    system_prompt: str
    user_prompt: str
    variables: list[str]
    is_active: bool
    created_at: datetime
    created_by: str | None


class PromptTemplateCreate(BaseModel):
    task_type: str = Field(min_length=1, max_length=100)
    client_id: int | None = None
    name: str = Field(min_length=1, max_length=255)
    system_prompt: str = Field(min_length=1)
    user_prompt: str = Field(min_length=1)
    variables: list[str] = Field(default_factory=list)
    activate: bool = True


class PromptTemplatePreviewRequest(BaseModel):
    task_type: str = Field(min_length=1, max_length=100)
    template_id: int | None = None
    system_prompt: str | None = None
    user_prompt: str | None = None
    variables: list[str] | None = None
    product: dict[str, Any] | None = None
    feed_source_id: int | None = None
    product_id: str | None = None


class AiSettingsOut(BaseModel):
    ai_cache_type: Literal["local", "disk"]
    ai_cache_namespace: str
    ai_cache_ttl_taxonomy_s: int
    ai_cache_ttl_content_s: int
    ai_router_timeout_s: int
    ai_router_num_retries: int
    ai_router_allowed_fails: int
    ai_router_cooldown_s: int
    ai_instructor_max_retries: int
    ai_usage_retention_days: int
    redis_from_env: bool
    effective_cache_backend: str


class AiSettingsUpdate(BaseModel):
    ai_cache_type: Literal["local", "disk"] = "local"
    ai_cache_namespace: str = Field(min_length=1, max_length=64)
    ai_cache_ttl_taxonomy_s: int = Field(ge=1)
    ai_cache_ttl_content_s: int = Field(ge=1)
    ai_router_timeout_s: int = Field(ge=1, le=600)
    ai_router_num_retries: int = Field(ge=0, le=10)
    ai_router_allowed_fails: int = Field(ge=0, le=100)
    ai_router_cooldown_s: int = Field(ge=0, le=3600)
    ai_instructor_max_retries: int = Field(ge=0, le=10)
    ai_usage_retention_days: int = Field(ge=1)


class CacheClearRequest(BaseModel):
    namespace: str | None = Field(default=None, max_length=100)


class ProviderPresetOut(BaseModel):
    vendor_key: str
    label: str
    model_prefix: str
    default_base_url: str
    requires_base_url: bool
    api_key_env_hint: str
    docs_url: str
    supports_catalog: bool


class ModelCatalogEntryOut(BaseModel):
    model_id: str
    vendor: str
    display_name: str
    context_window: int | None
    max_output_tokens: int | None
    input_price_per_mtok: Decimal | None
    output_price_per_mtok: Decimal | None
    supports_vision: bool
    supports_function_calling: bool
    is_recommended: bool


class ModelCatalogSyncOut(BaseModel):
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    source: str | None


class ModelCatalogOut(BaseModel):
    entries: list[ModelCatalogEntryOut]
    sync: ModelCatalogSyncOut
