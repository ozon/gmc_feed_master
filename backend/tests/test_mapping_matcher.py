import pytest

from app.mapping import MappingEntry, SourceField, auto_match
from registry.loader import load_registry


@pytest.fixture(scope="module")
def registry():
    return load_registry()


def test_exact_match(registry):
    result = auto_match([SourceField("title", "scalar")], registry)
    assert result == {"title": MappingEntry("title", "auto")}


def test_normalized_match(registry):
    result = auto_match([SourceField("Sale_Price", "scalar")], registry)
    assert result == {"Sale_Price": MappingEntry("sale_price", "auto")}


def test_synonym_match(registry):
    result = auto_match([SourceField("ean", "scalar")], registry)
    assert result == {"ean": MappingEntry("gtin", "synonym")}


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("ean", "gtin"),
        ("upc", "gtin"),
        ("barcode", "gtin"),
        ("isbn", "gtin"),
        ("sku", "id"),
        ("item_id", "id"),
        ("item_number", "id"),
        ("product_title", "title"),
        ("product_url", "link"),
        ("image_url", "image_link"),
        ("additional_images", "additional_image_link"),
    ],
)
def test_each_synonym_maps_to_target(registry, source, target):
    result = auto_match([SourceField(source, "scalar")], registry)
    assert result == {source: MappingEntry(target, "synonym")}


def test_kind_incompatible_no_match(registry):
    result = auto_match([SourceField("ean", "repeated_structured")], registry)
    assert result == {}


def test_conflict_first_source_wins(registry):
    fields = [SourceField("Sale_Price", "scalar"), SourceField("sale price", "scalar")]
    result = auto_match(fields, registry)
    assert result == {"Sale_Price": MappingEntry("sale_price", "auto")}


def test_auto_beats_synonym_on_target_conflict(registry):
    fields = [SourceField("ean", "scalar"), SourceField("gtin", "scalar")]
    result = auto_match(fields, registry)
    assert result == {"gtin": MappingEntry("gtin", "auto")}


def test_existing_manual_preserved(registry):
    fields = [SourceField("sku", "scalar"), SourceField("title", "scalar")]
    existing = {"sku": MappingEntry("id", "manual")}
    result = auto_match(fields, registry, existing)
    assert result == {
        "sku": MappingEntry("id", "manual"),
        "title": MappingEntry("title", "auto"),
    }


def test_manual_beats_auto_on_target_conflict(registry):
    fields = [SourceField("sku", "scalar"), SourceField("title", "scalar")]
    existing = {"sku": MappingEntry("title", "manual")}
    result = auto_match(fields, registry, existing)
    assert result == {"sku": MappingEntry("title", "manual")}


def test_unknown_field_unmapped(registry):
    result = auto_match([SourceField("margin", "scalar")], registry)
    assert result == {}


def test_sub_field_prefers_whole_attribute_match(registry):
    fields = [SourceField("ship", "structured", ("price",))]
    result = auto_match(fields, registry)
    assert result == {"ship.price": MappingEntry("price", "auto")}


def test_sub_field_matches_unique_subfield_path(registry):
    fields = [SourceField("fin", "structured", ("months",))]
    result = auto_match(fields, registry)
    assert result == {"fin.months": MappingEntry("installment.months", "auto")}


def test_sub_field_normalized_match(registry):
    fields = [SourceField("ship", "structured", ("Sale_Price",))]
    result = auto_match(fields, registry)
    assert result == {"ship.Sale_Price": MappingEntry("sale_price", "auto")}


def test_sub_field_of_repeated_structured_uses_repeated_scalar_kind(registry):
    fields = [SourceField("imgs", "repeated_structured", ("additional_image_link",))]
    result = auto_match(fields, registry)
    assert result == {
        "imgs.additional_image_link": MappingEntry("additional_image_link", "auto")
    }


def test_sub_field_kind_incompatible_no_match(registry):
    fields = [SourceField("box", "structured", ("shipping",))]
    result = auto_match(fields, registry)
    assert result == {}


def test_sub_field_no_synonyms(registry):
    fields = [SourceField("box", "structured", ("ean",))]
    result = auto_match(fields, registry)
    assert result == {}


def test_whole_field_mapping_suppresses_sub_pass(registry):
    fields = [SourceField("ship", "structured", ("country",))]
    existing = {"ship": MappingEntry("shipping", "manual")}
    result = auto_match(fields, registry, existing)
    assert result == {"ship": MappingEntry("shipping", "manual")}


def test_existing_sub_mapping_blocks_whole_field_auto(registry):
    fields = [SourceField("ship", "structured", ("country",))]
    existing = {"ship.country": MappingEntry("shipping.country", "manual")}
    result = auto_match(fields, registry, existing)
    assert result == {"ship.country": MappingEntry("shipping.country", "manual")}
