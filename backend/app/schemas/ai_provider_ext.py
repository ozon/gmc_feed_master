"""Extensions to the provider schemas for the wizard flow (GFM-12).

Kept in a separate module rather than editing `app.schemas.ai_admin` directly,
since the exact current byte-for-byte content of that file (all Pydantic
schemas: AiProviderCreate/Update/Out, AiSettingsOut/Update, PromptTemplate*,
CacheClearRequest, ...) was not available for a safe full-file rewrite in
this session. Wire-in step for a maintainer with repo access:

    # in app/schemas/ai_admin.py, AiProviderCreate / AiProviderUpdate / AiProviderOut:
    azure_deployment_name: str | None = Field(default=None, max_length=255)
    azure_api_version: str | None = Field(default=None, max_length=32)

    # add a validator/normalizer so provider_type="openai_compatible" writes
    # are stored as "litellm" with `model` rewritten to f"openai/{model}"
    # (mirrors the read-side mapping already in app/ai/router.py::_litellm_model,
    # collapsing the two provider_type values into one going forward).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AiProviderAzureFields(BaseModel):
    """Mixin-style schema documenting the Azure-specific fields to add to
    `AiProviderCreate` / `AiProviderUpdate` / `AiProviderOut` once that file
    can be safely edited with full original content in hand."""

    azure_deployment_name: str | None = Field(default=None, max_length=255)
    azure_api_version: str | None = Field(default=None, max_length=32)


def normalize_provider_type(provider_type: str, model: str) -> tuple[str, str]:
    """Collapse the legacy `openai_compatible` provider_type into `litellm`
    at write time, matching the read-side mapping in
    `app/ai/router.py::_litellm_model`.

    Returns (normalized_provider_type, normalized_model).
    """
    if provider_type == "openai_compatible" and "/" not in model:
        return "litellm", f"openai/{model}"
    return provider_type, model
