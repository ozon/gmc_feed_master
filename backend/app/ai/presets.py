from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    vendor_key: str
    label: str
    model_prefix: str
    default_base_url: str
    requires_base_url: bool
    api_key_env_hint: str
    docs_url: str
    supports_catalog: bool


PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        vendor_key="openai",
        label="OpenAI",
        model_prefix="openai",
        default_base_url="",
        requires_base_url=False,
        api_key_env_hint="OPENAI_API_KEY",
        docs_url="https://platform.openai.com/api-keys",
        supports_catalog=True,
    ),
    ProviderPreset(
        vendor_key="anthropic",
        label="Anthropic",
        model_prefix="anthropic",
        default_base_url="",
        requires_base_url=False,
        api_key_env_hint="ANTHROPIC_API_KEY",
        docs_url="https://console.anthropic.com/settings/keys",
        supports_catalog=True,
    ),
    ProviderPreset(
        vendor_key="google",
        label="Google Gemini",
        model_prefix="gemini",
        default_base_url="",
        requires_base_url=False,
        api_key_env_hint="GEMINI_API_KEY",
        docs_url="https://aistudio.google.com/app/apikey",
        supports_catalog=True,
    ),
    ProviderPreset(
        vendor_key="openrouter",
        label="OpenRouter",
        model_prefix="openrouter",
        default_base_url="",
        requires_base_url=False,
        api_key_env_hint="OPENROUTER_API_KEY",
        docs_url="https://openrouter.ai/keys",
        supports_catalog=True,
    ),
    ProviderPreset(
        vendor_key="mistral",
        label="Mistral",
        model_prefix="mistral",
        default_base_url="",
        requires_base_url=False,
        api_key_env_hint="MISTRAL_API_KEY",
        docs_url="https://console.mistral.ai/api-keys",
        supports_catalog=True,
    ),
    ProviderPreset(
        vendor_key="groq",
        label="Groq",
        model_prefix="groq",
        default_base_url="",
        requires_base_url=False,
        api_key_env_hint="GROQ_API_KEY",
        docs_url="https://console.groq.com/keys",
        supports_catalog=True,
    ),
    ProviderPreset(
        vendor_key="custom",
        label="OpenAI-kompatibel (custom)",
        model_prefix="openai",
        default_base_url="",
        requires_base_url=True,
        api_key_env_hint="",
        docs_url="",
        supports_catalog=False,
    ),
)

_PRESETS_BY_KEY = {preset.vendor_key: preset for preset in PROVIDER_PRESETS}


def get_preset(vendor_key: str) -> ProviderPreset | None:
    return _PRESETS_BY_KEY.get(vendor_key)


def normalize_provider_input(model: str, provider_type: str) -> tuple[str, str]:
    if provider_type == "openai_compatible" and "/" not in model:
        return "litellm", f"openai/{model}"
    return "litellm", model
