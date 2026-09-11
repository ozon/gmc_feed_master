from __future__ import annotations

import pytest

from app.ai.tasks import (
    TASK_SPECS,
    input_hash,
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
