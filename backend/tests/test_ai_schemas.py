from __future__ import annotations

import typing

import pytest
from pydantic import ValidationError

from app.ai import schemas
from app.ai.constraints import enum_values


def _literal_values(annotation: object) -> tuple[str, ...]:
    for arg in typing.get_args(annotation):
        if typing.get_origin(arg) is typing.Literal:
            return typing.get_args(arg)
    raise AssertionError("no Literal in annotation")


def test_gender_and_age_group_literals_match_registry() -> None:
    gender = _literal_values(schemas.EnrichedAttributes.model_fields["gender"].annotation)
    age_group = _literal_values(
        schemas.EnrichedAttributes.model_fields["age_group"].annotation
    )
    assert tuple(gender) == enum_values("gender")
    assert tuple(age_group) == enum_values("age_group")


def test_optimized_title_accepts_valid() -> None:
    assert schemas.OptimizedTitle(title="Acme Wool Socks").title == "Acme Wool Socks"


def test_optimized_title_rejects_over_150_chars() -> None:
    with pytest.raises(ValidationError):
        schemas.OptimizedTitle(title="x" * 151)


def test_optimized_title_rejects_promotional_text() -> None:
    with pytest.raises(ValidationError):
        schemas.OptimizedTitle(title="Acme Socks (free shipping)")


def test_optimized_title_allows_word_containing_sale() -> None:
    assert schemas.OptimizedTitle(title="Wholesale Acme Socks").title == "Wholesale Acme Socks"


def test_optimized_title_rejects_all_caps() -> None:
    with pytest.raises(ValidationError):
        schemas.OptimizedTitle(title="ACME WOOL SOCKS")


def test_optimized_description_max_5000() -> None:
    assert len(schemas.OptimizedDescription(description="d" * 5000).description) == 5000
    with pytest.raises(ValidationError):
        schemas.OptimizedDescription(description="d" * 5001)


def test_category_assignment_accepts_known_id() -> None:
    assert schemas.CategoryAssignment(
        google_product_category=2271
    ).google_product_category == 2271


def test_category_assignment_rejects_unknown_id() -> None:
    with pytest.raises(ValidationError):
        schemas.CategoryAssignment(google_product_category=999999999)


def test_enriched_attributes_enums_and_optional_fields() -> None:
    model = schemas.EnrichedAttributes(color="red", gender="unisex", age_group="adult")
    assert model.color == "red"
    assert model.size is None
    with pytest.raises(ValidationError):
        schemas.EnrichedAttributes(gender="robot")


def test_enriched_attributes_custom_label_max_length() -> None:
    schemas.EnrichedAttributes(custom_label_0="x" * 100)
    with pytest.raises(ValidationError):
        schemas.EnrichedAttributes(custom_label_0="x" * 101)


def test_policy_check_result_shape() -> None:
    result = schemas.PolicyCheckResult(
        violations=[schemas.Violation(rule="misleading", reason="unverified claim")],
        confidence=0.8,
    )
    assert result.violations[0].rule == "misleading"


def test_policy_check_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        schemas.PolicyCheckResult(violations=[], confidence=1.5)


def test_image_quality_requires_core_fields() -> None:
    result = schemas.ImageQualityResult(
        watermark=False, text_overlay=True, background="white", confidence=0.9,
    )
    assert result.text_overlay is True


def test_response_models_registry_covers_all_tasks() -> None:
    assert set(schemas.RESPONSE_MODELS) == {
        "title_optimization",
        "description_optimization",
        "category_classification",
        "policy_check",
        "attribute_enrichment",
        "image_quality",
    }
