from __future__ import annotations

from decimal import Decimal

from app.ai.model_catalog import (
    is_recommended,
    load_bundled,
    parse_catalog,
)

RAW = {
    "gpt-4o": {
        "litellm_provider": "openai",
        "mode": "chat",
        "input_cost_per_token": 2.5e-06,
        "output_cost_per_token": 1e-05,
        "max_input_tokens": 128000,
        "max_output_tokens": 16384,
        "supports_vision": True,
        "supports_function_calling": True,
    },
    "gpt-4o-no-prices": {
        "litellm_provider": "openai",
        "mode": "chat",
    },
    "text-embedding-3-small": {
        "litellm_provider": "openai",
        "mode": "embedding",
        "input_cost_per_token": 2e-08,
    },
    "gpt-4o-deprecated": {
        "litellm_provider": "openai",
        "mode": "chat",
        "deprecated": True,
    },
    "mistral/mistral-large-latest": {
        "litellm_provider": "mistral",
        "mode": "chat",
        "input_cost_per_token": 5e-07,
        "output_cost_per_token": 1.5e-06,
        "max_input_tokens": 262144,
    },
    "some-random-model": {
        "litellm_provider": "fireworks_ai",
        "mode": "chat",
    },
    "not-a-dict": 42,
}


def test_parse_catalog_keeps_supported_chat_models() -> None:
    entries = {entry.model_id: entry for entry in parse_catalog(RAW)}
    assert set(entries) == {
        "openai/gpt-4o",
        "openai/gpt-4o-no-prices",
        "mistral/mistral-large-latest",
    }


def test_parse_catalog_canonicalizes_bare_and_prefixed_keys() -> None:
    entries = {entry.model_id: entry for entry in parse_catalog(RAW)}
    assert entries["openai/gpt-4o"].vendor == "openai"
    assert entries["openai/gpt-4o"].display_name == "gpt-4o"
    assert entries["mistral/mistral-large-latest"].vendor == "mistral"


def test_parse_catalog_converts_costs_to_per_mtok() -> None:
    entry = {e.model_id: e for e in parse_catalog(RAW)}["openai/gpt-4o"]
    assert entry.input_price_per_mtok == Decimal("2.500000")
    assert entry.output_price_per_mtok == Decimal("10.000000")
    assert entry.context_window == 128000
    assert entry.max_output_tokens == 16384
    assert entry.supports_vision is True
    assert entry.supports_function_calling is True
    assert entry.mode == "chat"


def test_parse_catalog_allows_missing_prices() -> None:
    entry = {e.model_id: e for e in parse_catalog(RAW)}["openai/gpt-4o-no-prices"]
    assert entry.input_price_per_mtok is None
    assert entry.output_price_per_mtok is None


def test_parse_catalog_dedupes_model_ids() -> None:
    duped = dict(RAW)
    duped["openai/gpt-4o"] = duped["gpt-4o"]
    ids = [e.model_id for e in parse_catalog(duped)]
    assert ids.count("openai/gpt-4o") == 1


def test_load_bundled_returns_supported_entries() -> None:
    entries = load_bundled()
    assert len(entries) > 50
    assert all(entry.vendor in {"openai", "anthropic", "google", "openrouter", "mistral", "groq"} for entry in entries)
    assert any(entry.model_id == "openai/gpt-4o" for entry in entries)


def test_is_recommended() -> None:
    assert is_recommended("openai", "openai/gpt-4o") is True
    assert is_recommended("openai", "openai/never-heard-of-it") is False
    assert is_recommended("custom", "openai/anything") is False
