from __future__ import annotations

from app.ai import constraints


def test_title_max_length_matches_registry() -> None:
    assert constraints.max_length("title") == 150


def test_description_max_length_matches_registry() -> None:
    assert constraints.max_length("description") == 5000


def test_unknown_attribute_has_no_constraints() -> None:
    assert constraints.max_length("does_not_exist") is None


def test_custom_label_max_length() -> None:
    assert constraints.max_length("custom_label_0") == 100
