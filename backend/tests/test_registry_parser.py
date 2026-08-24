from pathlib import Path

import pytest

from registry.model import AttributeKind, ExportStatus, FeedDomain
from registry.parser import RegistryParseError, parse_gmc_markdown


FIXTURES = Path(__file__).parent / "fixtures" / "registry"


def test_parses_scalar_repeated_structured_enum_metadata():
    document = parse_gmc_markdown(FIXTURES / "valid.md")

    assert sorted(document.attributes) == ["additional_image_link", "availability", "installment", "title"]
    assert document.attributes["title"].kind is AttributeKind.SCALAR
    assert document.attributes["title"].required == "required"
    assert document.attributes["title"].constraints.max_length == 150
    assert document.attributes["additional_image_link"].kind is AttributeKind.REPEATED_SCALAR
    assert document.attributes["additional_image_link"].cardinality.max_items == 10
    installment = document.attributes["installment"]
    assert installment.kind is AttributeKind.STRUCTURED
    assert [field.name for field in installment.fields] == ["months", "amount"]
    assert installment.fields[0].required == "required"
    assert document.attributes["availability"].enum_values == ("in_stock", "out_of_stock")


@pytest.mark.parametrize("fixture, message", [
    ("malformed.md", "malformed table row"),
    ("duplicate.md", "duplicate attribute"),
    ("unsupported.md", "unsupported type"),
    ("ambiguous.md", "ambiguous structured attribute order"),
])
def test_rejects_invalid_fixtures_with_line_diagnostics(fixture, message):
    with pytest.raises(RegistryParseError, match=message):
        parse_gmc_markdown(FIXTURES / fixture)


def test_marks_deprecated_and_vehicle_attributes_explicitly():
    deprecated = parse_gmc_markdown(FIXTURES / "deprecated.md").attributes["old_field"]
    vehicle = parse_gmc_markdown(FIXTURES / "vehicle.md").attributes["vin"]

    assert deprecated.export_status is ExportStatus.NON_EXPORTABLE
    assert deprecated.domain is FeedDomain.PRIMARY
    assert vehicle.domain is FeedDomain.VEHICLE_LISTINGS
    assert vehicle.export_status is ExportStatus.EXPORTABLE
