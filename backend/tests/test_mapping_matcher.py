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
