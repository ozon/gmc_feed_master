from __future__ import annotations

from app.ai import constraints


def test_title_max_length_matches_registry() -> None:
    assert constraints.max_length("title") == 150


def test_description_max_length_matches_registry() -> None:
    assert constraints.max_length("description") == 5000


def test_unknown_attribute_has_no_constraints() -> None:
    assert constraints.max_length("does_not_exist") is None
    assert constraints.enum_values("does_not_exist") == ()


def test_gender_and_age_group_enums_come_from_registry() -> None:
    assert constraints.enum_values("gender") == ("male", "female", "unisex")
    assert constraints.enum_values("age_group") == (
        "newborn", "infant", "toddler", "kids", "adult",
    )


def test_custom_label_max_length() -> None:
    assert constraints.max_length("custom_label_0") == 100
