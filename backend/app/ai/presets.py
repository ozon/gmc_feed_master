"""Provider presets for the AI Provider Configuration wizard.

Each preset drives the 3-step frontend flow (Anbieter -> API-Key -> Modell) by
supplying the metadata needed to prefill and validate an `AiProviderCreate`
payload without the caller having to know the underlying LiteLLM
`provider_type` / model-prefix scheme.

See: itsaplan GFM-12 "AI Provider Configuration 2.0: Preset-Wizard + Model-Katalog"
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    vendor_key: str
    label: str
    litellm_provider: str  # matches `litellm_provider` in the model-prices catalog
    model_prefix: str  # LiteLLM vendor prefix, e.g. "openai", "anthropic"
    default_base_url: str = ""
    requires_base_url: bool = False
    requires_api_version: bool = False
    api_key_docs_url: str = ""
    description: str = ""
    is_custom: bool = False


PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        vendor_key="openai",
        label="OpenAI",
        litellm_provider="openai",
        model_prefix="openai",
        api_key_docs_url="https://platform.openai.com/api-keys",
        description="GPT-4o, GPT-4.1, o-series models.",
    ),
    ProviderPreset(
        vendor_key="anthropic",
        label="Anthropic",
        litellm_provider="anthropic",
        model_prefix="anthropic",
        api_key_docs_url="https://console.anthropic.com/settings/keys",
        description="Claude 3.5/4 family.",
    ),
    ProviderPreset(
        vendor_key="gemini",
        label="Google Gemini",
        litellm_provider="gemini",
        model_prefix="gemini",
        api_key_docs_url="https://aistudio.google.com/app/apikey",
        description="Gemini 1.5/2.0 family via Google AI Studio.",
    ),
    ProviderPreset(
        vendor_key="azure",
        label="Azure OpenAI",
        litellm_provider="azure",
        model_prefix="azure",
        requires_base_url=True,
        requires_api_version=True,
        api_key_docs_url="https://learn.microsoft.com/azure/ai-services/openai/quickstart",
        description="Deployment-based OpenAI models hosted on Azure.",
    ),
    ProviderPreset(
        vendor_key="mistral",
        label="Mistral AI",
        litellm_provider="mistral",
        model_prefix="mistral",
        api_key_docs_url="https://console.mistral.ai/api-keys",
        description="Mistral Large / Small / Codestral.",
    ),
    ProviderPreset(
        vendor_key="groq",
        label="Groq",
        litellm_provider="groq",
        model_prefix="groq",
        api_key_docs_url="https://console.groq.com/keys",
        description="Low-latency inference for open models (Llama, Mixtral).",
    ),
    ProviderPreset(
        vendor_key="openai_compatible_custom",
        label="OpenAI-kompatibel (custom)",
        litellm_provider="openai",
        model_prefix="openai",
        requires_base_url=True,
        description="Selbst-gehostete Endpunkte: vLLM, Ollama, LM Studio, OpenRouter u.a.",
        is_custom=True,
    ),
)

_PRESETS_BY_KEY: dict[str, ProviderPreset] = {p.vendor_key: p for p in PROVIDER_PRESETS}


def get_preset(vendor_key: str) -> ProviderPreset | None:
    return _PRESETS_BY_KEY.get(vendor_key)


def list_presets() -> list[ProviderPreset]:
    return list(PROVIDER_PRESETS)
