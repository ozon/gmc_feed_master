from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

LITELLM_CATALOG_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "litellm/model_prices_and_context_window.json"
)
MIN_CATALOG_ENTRIES = 50

SUPPORTED_VENDORS: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "google",
    "openrouter": "openrouter",
    "mistral": "mistral",
    "groq": "groq",
}

RECOMMENDED_MODELS: dict[str, set[str]] = {
    "openai": {"openai/gpt-4o", "openai/gpt-4o-mini"},
    "anthropic": {"anthropic/claude-sonnet-4-5", "anthropic/claude-haiku-4-5"},
    "google": {"gemini/gemini-2.5-flash", "gemini/gemini-2.0-flash"},
    "openrouter": {"openrouter/anthropic/claude-sonnet-4"},
    "mistral": {"mistral/mistral-large-latest"},
    "groq": {"groq/llama-3.3-70b-versatile"},
}


@dataclass(frozen=True)
class CatalogEntry:
    vendor: str
    model_id: str
    display_name: str
    mode: str
    context_window: int | None
    max_output_tokens: int | None
    input_price_per_mtok: Decimal | None
    output_price_per_mtok: Decimal | None
    supports_vision: bool
    supports_function_calling: bool


def _per_mtok(cost: Any) -> Decimal | None:
    if cost is None:
        return None
    return (Decimal(str(cost)) * Decimal(1_000_000)).quantize(Decimal("0.000001"))


def parse_catalog(raw: dict[str, Any]) -> list[CatalogEntry]:
    entries: dict[str, CatalogEntry] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        provider = value.get("litellm_provider")
        if not isinstance(provider, str):
            continue
        vendor = SUPPORTED_VENDORS.get(provider)
        if vendor is None:
            continue
        mode = value.get("mode") or "chat"
        if mode not in ("chat", "completion"):
            continue
        if value.get("deprecated"):
            continue
        model_id = key if "/" in key else f"{provider}/{key}"
        if model_id in entries:
            continue
        max_tokens = value.get("max_tokens")
        entries[model_id] = CatalogEntry(
            vendor=vendor,
            model_id=model_id,
            display_name=model_id.rsplit("/", 1)[-1],
            mode="chat",
            context_window=value.get("max_input_tokens") or max_tokens,
            max_output_tokens=value.get("max_output_tokens") or max_tokens,
            input_price_per_mtok=_per_mtok(value.get("input_cost_per_token")),
            output_price_per_mtok=_per_mtok(value.get("output_cost_per_token")),
            supports_vision=bool(value.get("supports_vision")),
            supports_function_calling=bool(value.get("supports_function_calling")),
        )
    return list(entries.values())


def load_bundled() -> list[CatalogEntry]:
    import litellm

    return parse_catalog(litellm.model_cost)


def is_recommended(vendor: str, model_id: str) -> bool:
    return model_id in RECOMMENDED_MODELS.get(vendor, set())
