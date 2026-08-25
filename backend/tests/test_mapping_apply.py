import pytest

from app.mapping import ApplyStats, MappingEntry, apply_mapping
from registry.loader import load_registry


@pytest.fixture(scope="module")
def registry():
    return load_registry()


def test_scalar_to_scalar(registry):
    result, stats = apply_mapping(
        {"sku": "A"}, {"sku": MappingEntry("id", "auto")}, registry
    )
    assert result == {"id": "A"}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_scalar_to_subfield(registry):
    result, stats = apply_mapping(
        {"months": "6"}, {"months": MappingEntry("installment.months", "manual")}, registry
    )
    assert result == {"installment": {"months": "6"}}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_scalar_to_repeated_scalar_wraps(registry):
    result, stats = apply_mapping(
        {"tag": "sale"},
        {"tag": MappingEntry("additional_image_link", "manual")},
        registry,
    )
    assert result == {"additional_image_link": ["sale"]}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_list_to_repeated_scalar_copies(registry):
    product = {"images": ["a.jpg", "b.jpg"]}
    result, stats = apply_mapping(
        product, {"images": MappingEntry("additional_image_link", "manual")}, registry
    )
    assert result == {"additional_image_link": ["a.jpg", "b.jpg"]}
    assert result["additional_image_link"] is not product["images"]
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dict_to_structured_copies_known_subfields(registry):
    result, stats = apply_mapping(
        {"ship": {"months": "6", "extra": "x"}},
        {"ship": MappingEntry("installment", "manual")},
        registry,
    )
    assert result == {"installment": {"months": "6"}}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dict_to_repeated_structured_wraps(registry):
    result, stats = apply_mapping(
        {"ship": {"country": "US"}},
        {"ship": MappingEntry("shipping", "manual")},
        registry,
    )
    assert result == {"shipping": [{"country": "US"}]}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_list_of_dicts_to_repeated_structured_copies(registry):
    product = {"ship": [{"country": "US"}, {"country": "CA"}]}
    result, stats = apply_mapping(
        product, {"ship": MappingEntry("shipping", "manual")}, registry
    )
    assert result == {"shipping": [{"country": "US"}, {"country": "CA"}]}
    assert result["shipping"] is not product["ship"]
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_shape_mismatch_dropped_and_counted(registry):
    result, stats = apply_mapping(
        {"images": ["a.jpg"]}, {"images": MappingEntry("title", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=1)


def test_unmapped_field_dropped_and_counted(registry):
    result, stats = apply_mapping({"margin": "10"}, {}, registry)
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=1, shape_mismatches=0)


def test_identity_passthrough(registry):
    result, stats = apply_mapping(
        {"title": "Shirt"}, {"title": MappingEntry("title", "auto")}, registry
    )
    assert result == {"title": "Shirt"}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_subfield_targets_merge_into_one_struct(registry):
    result, stats = apply_mapping(
        {"m": "6", "a": "100 USD"},
        {
            "m": MappingEntry("installment.months", "manual"),
            "a": MappingEntry("installment.amount", "manual"),
        },
        registry,
    )
    assert result == {"installment": {"months": "6", "amount": "100 USD"}}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)
