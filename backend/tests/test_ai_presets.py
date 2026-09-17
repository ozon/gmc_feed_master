from __future__ import annotations

import pytest

from app.ai.presets import PROVIDER_PRESETS, get_preset, normalize_provider_input


def test_preset_keys_and_order() -> None:
    keys = [p.vendor_key for p in PROVIDER_PRESETS]
    assert keys == [
        "openai", "anthropic", "google", "openrouter", "mistral", "groq", "custom",
    ]
    assert keys[-1] == "custom"


def test_custom_is_the_only_base_url_required_preset() -> None:
    assert [p.vendor_key for p in PROVIDER_PRESETS if p.requires_base_url] == ["custom"]
    assert [p.vendor_key for p in PROVIDER_PRESETS if not p.supports_catalog] == ["custom"]


def test_google_preset_uses_gemini_prefix() -> None:
    google = get_preset("google")
    assert google is not None
    assert google.model_prefix == "gemini"


def test_get_preset_unknown() -> None:
    assert get_preset("nope") is None


@pytest.mark.parametrize(
    ("model", "provider_type", "expected"),
    [
        ("gpt-4o-mini", "openai_compatible", ("litellm", "openai/gpt-4o-mini")),
        ("openai/gpt-4o-mini", "openai_compatible", ("litellm", "openai/gpt-4o-mini")),
        ("openai/gpt-4o-mini", "litellm", ("litellm", "openai/gpt-4o-mini")),
        ("gpt-4o", "litellm", ("litellm", "gpt-4o")),
        ("anthropic/claude-sonnet-4-5", "litellm", ("litellm", "anthropic/claude-sonnet-4-5")),
    ],
)
def test_normalize_provider_input(model: str, provider_type: str, expected: tuple[str, str]) -> None:
    assert normalize_provider_input(model, provider_type) == expected
