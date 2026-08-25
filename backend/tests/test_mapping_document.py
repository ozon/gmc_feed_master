import pytest

from app.mapping import (
    MappingDocument,
    MappingDocumentError,
    MappingEntry,
    SourceField,
)


def test_empty_document():
    doc = MappingDocument.empty()
    assert doc.version == 1
    assert doc.auto_mapped is False
    assert doc.source_fields == []
    assert doc.mappings == {}


def test_empty_returns_independent_instances():
    a = MappingDocument.empty()
    b = MappingDocument.empty()
    a.source_fields.append(SourceField(name="sku", kind="scalar"))
    a.mappings["sku"] = MappingEntry(target="id", origin="manual")
    assert b.source_fields == []
    assert b.mappings == {}


def test_mapping_entry_fields():
    entry = MappingEntry(target="id", origin="manual")
    assert entry.target == "id"
    assert entry.origin == "manual"


def test_round_trip_preserves_content():
    raw = {
        "version": 1,
        "auto_mapped": True,
        "source_fields": [
            {"name": "sku", "kind": "scalar", "sub_fields": []},
            {
                "name": "shipping",
                "kind": "repeated_structured",
                "sub_fields": ["country", "price"],
            },
        ],
        "mappings": {
            "sku": {"target": "id", "origin": "synonym"},
            "title": {"target": "title", "origin": "auto"},
        },
    }
    doc = MappingDocument.from_json(raw)
    assert doc.version == 1
    assert doc.auto_mapped is True
    assert doc.source_fields == [
        SourceField(name="sku", kind="scalar", sub_fields=()),
        SourceField(
            name="shipping",
            kind="repeated_structured",
            sub_fields=("country", "price"),
        ),
    ]
    assert doc.mappings == {
        "sku": MappingEntry(target="id", origin="synonym"),
        "title": MappingEntry(target="title", origin="auto"),
    }
    assert doc.to_json() == raw
    assert MappingDocument.from_json(doc.to_json()) == doc


def test_to_json_shape():
    doc = MappingDocument(
        source_fields=[SourceField(name="sku", kind="scalar")],
        mappings={"sku": MappingEntry(target="id", origin="manual")},
    )
    assert doc.to_json() == {
        "version": 1,
        "auto_mapped": False,
        "source_fields": [
            {"name": "sku", "kind": "scalar", "sub_fields": []},
        ],
        "mappings": {"sku": {"target": "id", "origin": "manual"}},
    }


def test_from_json_empty_dict():
    assert MappingDocument.from_json({}) == MappingDocument.empty()


def test_from_json_none():
    assert MappingDocument.from_json(None) == MappingDocument.empty()


def test_from_json_missing_keys_defaulted():
    doc = MappingDocument.from_json({"auto_mapped": True})
    assert doc.version == 1
    assert doc.auto_mapped is True
    assert doc.source_fields == []
    assert doc.mappings == {}


def test_from_json_unknown_keys_ignored():
    doc = MappingDocument.from_json({"unexpected": 42, "mappings": {}})
    assert doc == MappingDocument.empty()


def test_from_json_source_field_missing_sub_fields_defaults_empty():
    doc = MappingDocument.from_json(
        {"source_fields": [{"name": "sku", "kind": "scalar"}]}
    )
    assert doc.source_fields == [SourceField(name="sku", kind="scalar")]


@pytest.mark.parametrize(
    "raw",
    [
        {"mappings": "not-a-dict"},
        {"mappings": ["sku"]},
        {"source_fields": "sku"},
        {"source_fields": [42]},
        {"source_fields": [{"name": 5, "kind": "scalar"}]},
        {"source_fields": [{"name": "sku", "kind": "scalar", "sub_fields": "x"}]},
        {"mappings": {"sku": "id"}},
        {"mappings": {"sku": {"target": 7, "origin": "auto"}}},
        {"mappings": {"sku": {"target": "id", "origin": "guessed"}}},
        {"version": "1"},
        {"auto_mapped": "yes"},
        "not-a-dict",
        42,
    ],
)
def test_from_json_corrupt_input_raises(raw):
    with pytest.raises(MappingDocumentError):
        MappingDocument.from_json(raw)
