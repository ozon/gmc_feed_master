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


@pytest.mark.parametrize("fixture, expected", [
    ("malformed.md", "line 3: malformed table row"),
    ("duplicate.md", "line 4: duplicate attribute title (first occurrence line 3, field title)"),
    ("unsupported.md", "line 3: unsupported type Blob"),
    ("ambiguous.md", "line 3: ambiguous structured attribute order"),
])
def test_rejects_invalid_fixtures_with_exact_line_diagnostics(fixture, expected):
    with pytest.raises(RegistryParseError) as error:
        parse_gmc_markdown(FIXTURES / fixture)
    assert str(error.value) == expected


def test_marks_deprecated_and_vehicle_attributes_explicitly():
    deprecated = parse_gmc_markdown(FIXTURES / "deprecated.md").attributes["old_field"]
    vehicle = parse_gmc_markdown(FIXTURES / "vehicle.md").attributes["vin"]

    assert deprecated.export_status is ExportStatus.NON_EXPORTABLE
    assert deprecated.domain is FeedDomain.PRIMARY
    assert vehicle.domain is FeedDomain.VEHICLE_LISTINGS
    assert vehicle.export_status is ExportStatus.EXPORTABLE


def test_full_source_preserves_domains_statuses_and_structured_metadata():
    document = parse_gmc_markdown(Path(__file__).parents[2] / "gmc_def.md")

    for name in ("display_ads_id", "link_template", "expected_lifetime"):
        assert document.attributes[name].export_status is ExportStatus.NON_EXPORTABLE
        assert document.attributes[name].source_line > 0
    assert document.attributes["link_template"].domain is FeedDomain.PRIMARY
    assert FeedDomain.VEHICLE_LISTINGS in document.attributes["link_template"].applicability
    for name in ("vin", "vehicle_msrp", "vehicle_fulfillment"):
        assert document.attributes[name].domain is FeedDomain.VEHICLE_LISTINGS

    installment = document.attributes["installment"]
    credit_type = next(field for field in installment.fields if field.name == "credit_type")
    assert credit_type.enum_values == ("finance", "lease")
    notice = document.attributes["consumer_notice"]
    assert next(field for field in notice.fields if field.name == "notice_type").enum_values == (
        "legal_disclaimer", "safety_warning", "prop_65"
    )
    assert next(field for field in notice.fields if field.name == "notice_message").constraints.max_length == 1000
    shipping = document.attributes["shipping"]
    assert shipping.cardinality.max_items == 100
    assert next(field for field in shipping.fields if field.name == "price").type == "Price"
    assert document.attributes["adult"].enum_values == ("yes", "no")
    assert document.attributes["identifier_exists"].enum_values == ("yes", "no")
    assert "big and tall" in document.attributes["size_type"].enum_values
    assert document.attributes["body_style"].enum_values[:3] == ("sedan", "suv", "coupe")
    assert len(shipping.fields) == 11
    assert tuple(field.name for field in document.attributes["minimum_order_value"].fields) == ("country", "service", "surface", "price")
    assert tuple(field.name for field in document.attributes["pickup_cost"].fields) == ("pickup_cost_flat_rate", "pickup_cost_free_threshold")
    assert tuple(field.name for field in document.attributes["returns"].fields) == ("country", "item_condition", "window_type", "window_days", "method", "outcome", "shipping_fee", "shipping_fee_type", "restocking_fee", "restocking_percentage_fee", "policy_url")
    assert tuple(field.name for field in document.attributes["loyalty_program"].fields) == ("program_label", "tier_label", "price", "cashback_for_future_use", "loyalty_points", "member_price_effective_date", "shipping_label")
    assert next(field for field in document.attributes["returns"].fields if field.name == "policy_url").type == "URL"
    assert next(field for field in document.attributes["minimum_order_value"].fields if field.name == "price").type == "Price"


def test_full_source_normalizes_enum_values_without_defaults_or_truncation():
    document = parse_gmc_markdown(Path(__file__).parents[2] / "gmc_def.md")

    assert document.attributes["minimum_order_value"].fields[2].enum_values == (
        "online", "local", "online_local"
    )
    assert next(field for field in document.attributes["returns"].fields if field.name == "window_type").enum_values == (
        "FINITE_RETURN_WINDOW", "NO_RETURNS", "LIFETIME"
    )
    assert document.attributes["body_style"].enum_values[-2:] == ("station wagon", "full size van")
    for name in ("adult", "identifier_exists"):
        assert document.attributes[name].enum_values == ("yes", "no")
    assert all("default" not in value.lower() and "…" not in value for value in document.attributes["body_style"].enum_values)


def test_nested_format_qualifiers_are_preserved():
    document = parse_gmc_markdown(Path(__file__).parents[2] / "gmc_def.md")
    minimum = document.attributes["minimum_order_value"]
    assert next(field for field in minimum.fields if field.name == "country").constraints.format == "ISO 3166-1"
    returns = document.attributes["returns"]
    assert next(field for field in returns.fields if field.name == "restocking_percentage_fee").constraints.format == "percent"
    cutoff = document.attributes["handling_cutoff_time"]
    assert next(field for field in cutoff.fields if field.name == "cutoff_timezone").constraints.format == "IANA"


def test_full_source_preserves_ranges_structured_plus_order_and_requirement_notes():
    document = parse_gmc_markdown(Path(__file__).parents[2] / "gmc_def.md")

    for name in ("energy_efficiency_class", "min_energy_efficiency_class", "max_energy_efficiency_class"):
        assert document.attributes[name].enum_values == ("range:A+++..G",)
        assert "…" not in document.attributes[name].enum_values[0]

    for name, max_length in (("structured_title", 150), ("structured_description", 5000)):
        fields = document.attributes[name].fields
        assert tuple(field.name for field in fields) == ("digital_source_type", "content")
        assert fields[0].enum_values == ("default", "trained_algorithmic_media")
        assert fields[0].required == "optional"
        assert fields[1].required == "required"
        assert fields[1].constraints.max_length == max_length

    for name in ("minimum_order_value", "pickup_cost"):
        attribute = document.attributes[name]
        assert attribute.required == "optional"
        assert "required_from:2026-09-30" in attribute.qualifiers
    window_days = next(field for field in document.attributes["returns"].fields if field.name == "window_days")
    assert window_days.required == "conditional"
