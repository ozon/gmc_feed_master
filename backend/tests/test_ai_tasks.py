from __future__ import annotations

from app.ai import schemas
from app.ai.tasks import CANONICAL_VARIABLES, TASK_SPECS


def test_canonical_variables_cover_all_task_specs() -> None:
    assert set(CANONICAL_VARIABLES) == set(TASK_SPECS)


def test_description_optimization_registered() -> None:
    assert CANONICAL_VARIABLES["description_optimization"] == ["title", "description"]
    assert (
        TASK_SPECS["description_optimization"].response_model
        is schemas.OptimizedDescription
    )


def test_category_prompt_requests_numeric_id() -> None:
    spec = TASK_SPECS["category_classification"]
    assert "taxonomy id" in spec.system.lower()
    assert "path" not in spec.system.lower()


def test_attribute_prompt_requests_new_fields() -> None:
    prompt = TASK_SPECS["attribute_enrichment"].system.lower()
    for field in ("gender", "age_group", "custom_label"):
        assert field in prompt
