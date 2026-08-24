from pathlib import Path
import re

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
    with pytest.raises(RegistryParseError, match=message) as error:
        parse_gmc_markdown(FIXTURES / fixture)
    assert re.search(r"line \d+", str(error.value))
    if fixture == "duplicate.md":
        assert str(error.value) == "line 4: duplicate attribute title (first occurrence line 3, field title)"


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
