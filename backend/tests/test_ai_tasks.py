from __future__ import annotations

import pytest

from app.ai.tasks import (
    TASK_SPECS,
    input_hash,
    render_task,
    validate_task,
)
from app.ai.templates import TaskSpecError

EXPECTED_TASK_TYPES = {
    "title_optimization",
    "category_classification",
    "policy_check",
    "attribute_enrichment",
    "image_quality",
}


def test_registry_has_all_task_types():
    assert set(TASK_SPECS) == EXPECTED_TASK_TYPES


def test_render_task_builds_messages():
    messages = render_task("title_optimization", {"title": "Running Shoe", "brand": "Acme"})
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user"]
    assert '<data key="title">Running Shoe</data>' in messages[1]["content"]
    assert '<data key="brand">Acme</data>' in messages[1]["content"]


def test_render_task_unknown_type_raises():
    with pytest.raises(TaskSpecError):
        render_task("nonexistent_task", {})


def test_validate_task_parses_json():
    value = validate_task("attribute_enrichment", '{"color": "blue"}')
    assert value == {"color": "blue"}


def test_validate_task_invalid_json_raises():
    with pytest.raises(TaskSpecError):
        validate_task("attribute_enrichment", "not json at all")


def test_input_hash_stable_and_content_sensitive():
    a = input_hash("attribute_enrichment", {"title": "Blue Shirt"})
    b = input_hash("attribute_enrichment", {"title": "Blue Shirt"})
    c = input_hash("attribute_enrichment", {"title": "Red Shirt"})
    assert a == b
    assert a != c


def test_input_hash_key_order_insensitive():
    a = input_hash("policy_check", {"title": "T", "description": "D"})
    b = input_hash("policy_check", {"description": "D", "title": "T"})
    assert a == b
