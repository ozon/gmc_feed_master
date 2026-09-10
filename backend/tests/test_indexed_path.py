import pytest

from app.mapping.indexed_path import IndexedPath, parse_indexed_path


@pytest.mark.parametrize("path,expected", [
    ("title", IndexedPath("title", None, None)),
    ("shipping.price", IndexedPath("shipping", None, "price")),
    ("additional_image_link.3", IndexedPath("additional_image_link", 3, None)),
    ("product_detail.2.attribute_value",
     IndexedPath("product_detail", 2, "attribute_value")),
])
def test_parse(path, expected):
    assert parse_indexed_path(path) == expected


def test_zero_index_rejected():
    with pytest.raises(ValueError, match="1-based"):
        parse_indexed_path("product_detail.0.attribute_name")


def test_negative_index_rejected():
    with pytest.raises(ValueError):
        parse_indexed_path("additional_image_link.-2")


def test_too_many_segments_rejected():
    with pytest.raises(ValueError):
        parse_indexed_path("a.b.c.d")


def test_empty_attr_rejected():
    with pytest.raises(ValueError):
        parse_indexed_path(".price")
    with pytest.raises(ValueError):
        parse_indexed_path("")


def test_index_is_1_based_in_storage_grammar():
    p = parse_indexed_path("product_detail.1.section_name")
    assert p.index == 1
