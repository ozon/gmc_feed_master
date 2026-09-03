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


def test_dotted_key_sub_of_dict_to_repeated_structured_subfield_wraps(registry):
    product = {"ship": {"country": "US", "service": "X"}}
    result, stats = apply_mapping(
        product, {"ship.country": MappingEntry("shipping.country", "manual")}, registry
    )
    assert result == {"shipping": [{"country": "US"}]}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_sub_of_dict_to_structured_subfield(registry):
    result, stats = apply_mapping(
        {"fin": {"m": "6"}},
        {"fin.m": MappingEntry("installment.months", "manual")},
        registry,
    )
    assert result == {"installment": {"months": "6"}}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_absent_sub_value_skipped(registry):
    result, stats = apply_mapping(
        {"ship": {}}, {"ship.country": MappingEntry("shipping.country", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_exact_product_key_wins(registry):
    product = {"a.b": "kept", "a": {"b": "dropped"}}
    result, stats = apply_mapping(
        product, {"a.b": MappingEntry("title", "manual")}, registry
    )
    assert result == {"title": "kept"}
    assert stats == ApplyStats(dropped_unmapped=1, shape_mismatches=0)


def test_dotted_key_parent_with_sub_mapping_not_counted_unmapped(registry):
    _result, stats = apply_mapping(
        {"ship": {"country": "US"}},
        {"ship.country": MappingEntry("shipping.country", "manual")},
        registry,
    )
    assert stats.dropped_unmapped == 0


def test_dotted_key_repeated_source_broadcasts(registry):
    product = {"ship": [{"country": "US"}, {"country": "CA"}]}
    result, stats = apply_mapping(
        product, {"ship.country": MappingEntry("shipping.country", "manual")}, registry
    )
    assert result == {"shipping": [{"country": "US"}, {"country": "CA"}]}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_repeated_source_element_wise_merge_multiple_subs(registry):
    product = {"ship": [{"country": "US", "price": "5"}, {"country": "CA", "price": "7"}]}
    result, stats = apply_mapping(
        product,
        {
            "ship.country": MappingEntry("shipping.country", "manual"),
            "ship.price": MappingEntry("shipping.price", "manual"),
        },
        registry,
    )
    assert result == {
        "shipping": [
            {"country": "US", "price": "5"},
            {"country": "CA", "price": "7"},
        ]
    }
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_repeated_source_auto_extends_target_list(registry):
    product = {"ship": [{"country": "US", "price": "5"}, {"country": "CA", "price": "7"}]}
    result, _stats = apply_mapping(
        product,
        {
            "ship.country": MappingEntry("shipping.country", "manual"),
            "ship.price": MappingEntry("shipping.price", "manual"),
        },
        registry,
    )
    assert result["shipping"][0] == {"country": "US", "price": "5"}
    assert result["shipping"][1] == {"country": "CA", "price": "7"}


def test_dotted_key_repeated_source_sparse_sub_values_merge_by_index(registry):
    product = {"ship": [{"country": "US"}, {"price": "7"}]}
    result, stats = apply_mapping(
        product,
        {
            "ship.country": MappingEntry("shipping.country", "manual"),
            "ship.price": MappingEntry("shipping.price", "manual"),
        },
        registry,
    )
    assert result == {
        "shipping": [{"country": "US"}, {"price": "7"}],
    }
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_sub_to_scalar_attr(registry):
    result, stats = apply_mapping(
        {"detail": {"name": "Shirt"}},
        {"detail.name": MappingEntry("title", "manual")},
        registry,
    )
    assert result == {"title": "Shirt"}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_sub_of_repeated_source_to_repeated_scalar_attr(registry):
    product = {"ship": [{"country": "US"}, {"country": "CA"}]}
    result, stats = apply_mapping(
        product, {"ship.country": MappingEntry("additional_image_link", "manual")}, registry
    )
    assert result == {"additional_image_link": ["US", "CA"]}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_list_into_structured_subfield_single_element_collapses(registry):
    product = {"ship": [{"months": "6"}]}
    result, stats = apply_mapping(
        product, {"ship.months": MappingEntry("installment.months", "manual")}, registry
    )
    assert result == {"installment": {"months": "6"}}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_list_into_structured_subfield_multi_element_mismatches(registry):
    product = {"ship": [{"months": "6"}, {"months": "12"}]}
    result, stats = apply_mapping(
        product, {"ship.months": MappingEntry("installment.months", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=1)


def test_dotted_key_non_dict_parent_list_element_shape_mismatch(registry):
    product = {"ship": [{"country": "US"}, "oops"]}
    result, stats = apply_mapping(
        product, {"ship.country": MappingEntry("shipping.country", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=1)


def test_dotted_key_non_str_sub_value_shape_mismatch(registry):
    product = {"ship": {"country": 42}}
    result, stats = apply_mapping(
        product, {"ship.country": MappingEntry("shipping.country", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=1)


def test_dotted_key_non_str_sub_value_in_list_shape_mismatch(registry):
    product = {"ship": [{"country": 42}]}
    result, stats = apply_mapping(
        product, {"ship.country": MappingEntry("shipping.country", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=1)


def test_dotted_key_scalar_parent_value_skipped_not_mismatch(registry):
    result, stats = apply_mapping(
        {"detail": "plain"}, {"detail.name": MappingEntry("title", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_three_segments_unresolvable_skipped(registry):
    product = {"a": {"b": {"c": "deep"}}}
    result, stats = apply_mapping(
        product, {"a.b.c": MappingEntry("title", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)
