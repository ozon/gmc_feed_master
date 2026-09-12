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
    input_price_per_mtok: Decimal | None
    output_price_per_mtok: Decimal | None
    max_concurrency: int
    timeout_s: int
    enabled: bool
    is_default: bool


class AiProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    provider_type: Literal["openai_compatible"] = "openai_compatible"
    base_url: str = Field(min_length=1, max_length=1024)
    api_key: str = Field(default="", max_length=1024)
    model: str = Field(min_length=1, max_length=255)
    input_price_per_mtok: Decimal | None = None
    output_price_per_mtok: Decimal | None = None
    max_concurrency: int = Field(default=4, ge=1, le=64)
    timeout_s: int = Field(default=30, ge=1, le=600)
    enabled: bool = True
    is_default: bool = False


class AiProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    provider_type: Literal["openai_compatible"] | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=1024)
    api_key: str | None = Field(default=None, max_length=1024)
    model: str | None = Field(default=None, min_length=1, max_length=255)
    input_price_per_mtok: Decimal | None = None
    output_price_per_mtok: Decimal | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=64)
    timeout_s: int | None = Field(default=None, ge=1, le=600)
    enabled: bool | None = None
    is_default: bool | None = None


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
