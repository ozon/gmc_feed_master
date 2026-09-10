"""Tests for _product_field_candidates indexed path support (Task 6)."""

from app.routes.products import _product_field_candidates


def test_candidates_indexed_repeated_scalar():
    raw = {"additional_image_link": ["a.jpg", "b.jpg"]}
    assert _product_field_candidates(raw, "additional_image_link.2") == ["b.jpg"]
    assert _product_field_candidates(raw, "additional_image_link.5") == []


def test_candidates_indexed_structured_sub():
    raw = {"product_detail": [
        {"attribute_name": "Battery"},
        {"attribute_name": "Color"},
    ]}
    assert _product_field_candidates(
        raw, "product_detail.2.attribute_name"
    ) == ["Color"]


def test_candidates_non_indexed_unchanged():
    raw = {"title": "T", "images": ["x", "y"]}
    assert _product_field_candidates(raw, "title") == ["T"]
    assert _product_field_candidates(raw, "images") == ["x", "y"]
