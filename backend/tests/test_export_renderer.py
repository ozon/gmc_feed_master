from app.export.renderer import ChannelMetadata, render_feed
from registry.loader import load_registry
from registry.model import (
    AttributeKind,
    ExportStatus,
    FeedDomain,
    RegistryAttribute,
    RegistryDocument,
    RequirementStatus,
    SubField,
)

CHANNEL = ChannelMetadata(title="Feed", link="https://shop.example", description="Desc")


def _attr(name, kind, fields=(), export_status=ExportStatus.EXPORTABLE):
    return RegistryAttribute(
        name=name,
        kind=kind,
        type="string",
        required=RequirementStatus.OPTIONAL,
        domain=FeedDomain.PRIMARY,
        export_status=export_status,
        fields=tuple(fields),
    )


def _sub(name):
    return SubField(name=name, type="string", required=RequirementStatus.OPTIONAL)


def _doc(*attrs):
    return RegistryDocument(attributes={a.name: a for a in attrs})


def test_scalar_rendering_and_escaping():
    registry = _doc(_attr("id", AttributeKind.SCALAR), _attr("title", AttributeKind.SCALAR))
    xml = render_feed([{"id": "1", "title": "A & B <c>"}], registry, CHANNEL)
    text = xml.decode("utf-8")
    assert "<g:id>1</g:id>" in text
    assert "<g:title>A &amp; B &lt;c&gt;</g:title>" in text


def test_rss_envelope_and_channel_metadata():
    registry = _doc(_attr("id", AttributeKind.SCALAR))
    xml = render_feed([{"id": "1"}], registry, ChannelMetadata(title="T & Co", link="https://x", description="D")).decode("utf-8")
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert '<rss version="2.0" xmlns:g="http://base.google.com/schemas/1.0">' in xml
    assert "<title>T &amp; Co</title>" in xml
    assert "<link>https://x</link>" in xml
    assert "<description>D</description>" in xml
    assert xml.rstrip().endswith("</rss>")


def test_repeated_scalar_strips_empty_elements():
    registry = _doc(_attr("id", AttributeKind.SCALAR), _attr("additional_image_link", AttributeKind.REPEATED_SCALAR))
    product = {"id": "1", "additional_image_link": ["a", "", None, "b"]}
    text = render_feed([product], registry, CHANNEL).decode("utf-8")
    assert text.count("<g:additional_image_link>") == 2
    assert "<g:additional_image_link>a</g:additional_image_link>" in text
    assert "<g:additional_image_link>b</g:additional_image_link>" in text


def test_structured_rendering_follows_registry_subfield_order():
    registry = _doc(
        _attr("id", AttributeKind.SCALAR),
        _attr("installment", AttributeKind.STRUCTURED, fields=(_sub("months"), _sub("amount"))),
    )
    product = {"id": "1", "installment": {"amount": "49.99 EUR", "months": "12"}}
    text = render_feed([product], registry, CHANNEL).decode("utf-8")
    assert "<g:installment><g:months>12</g:months><g:amount>49.99 EUR</g:amount></g:installment>" in text


def test_repeated_structured_pass_through_fidelity():
    registry = _doc(
        _attr("id", AttributeKind.SCALAR),
        _attr("shipping", AttributeKind.REPEATED_STRUCTURED, fields=(_sub("country"), _sub("price"))),
    )
    shipping = [{"country": "US", "price": "6.49 USD"}, {"country": "UK", "price": "5.99 GBP"}]
    text = render_feed([{"id": "1", "shipping": shipping}], registry, CHANNEL).decode("utf-8")
    assert text.count("<g:shipping>") == 2
    assert "<g:shipping><g:country>US</g:country><g:price>6.49 USD</g:price></g:shipping>" in text
    assert "<g:shipping><g:country>UK</g:country><g:price>5.99 GBP</g:price></g:shipping>" in text


def test_element_order_follows_registry_not_product():
    registry = _doc(
        _attr("id", AttributeKind.SCALAR),
        _attr("title", AttributeKind.SCALAR),
        _attr("price", AttributeKind.SCALAR),
    )
    text = render_feed([{"price": "1 USD", "id": "1", "title": "T"}], registry, CHANNEL).decode("utf-8")
    assert text.index("<g:id>") < text.index("<g:title>") < text.index("<g:price>")


def test_unknown_and_non_exportable_attributes_are_skipped():
    registry = _doc(
        _attr("id", AttributeKind.SCALAR),
        _attr("secret", AttributeKind.SCALAR, export_status=ExportStatus.NON_EXPORTABLE),
    )
    product = {"id": "1", "secret": "x", "_category_provenance": "auto"}
    text = render_feed([product], registry, CHANNEL).decode("utf-8")
    assert "secret" not in text
    assert "_category_provenance" not in text


def test_empty_values_skipped_entirely():
    registry = _doc(
        _attr("id", AttributeKind.SCALAR),
        _attr("title", AttributeKind.SCALAR),
        _attr("additional_image_link", AttributeKind.REPEATED_SCALAR),
        _attr("installment", AttributeKind.STRUCTURED, fields=(_sub("months"),)),
    )
    product = {"id": "1", "title": "", "additional_image_link": [], "installment": {}}
    text = render_feed([product], registry, CHANNEL).decode("utf-8")
    assert "<g:title>" not in text
    assert "<g:additional_image_link>" not in text
    assert "<g:installment>" not in text


def test_items_sorted_by_id():
    registry = _doc(_attr("id", AttributeKind.SCALAR))
    text = render_feed([{"id": "b"}, {"id": "a"}], registry, CHANNEL).decode("utf-8")
    assert text.index("<g:id>a</g:id>") < text.index("<g:id>b</g:id>")


def test_render_is_deterministic():
    registry = load_registry()
    product = {
        "id": "1",
        "title": "Shirt",
        "shipping": [{"country": "US", "price": "6.49 USD"}],
    }
    assert render_feed([product], registry, CHANNEL) == render_feed([product], registry, CHANNEL)


def test_empty_product_list_yields_valid_channel():
    registry = _doc(_attr("id", AttributeKind.SCALAR))
    text = render_feed([], registry, CHANNEL).decode("utf-8")
    assert "<item>" not in text
    assert "<channel>" in text and "</channel>" in text


def test_full_registry_round_trip_through_parse_xml():
    from app.ingest.xml_reader import parse_xml

    registry = load_registry()
    product = {
        "id": "SKU-1",
        "title": "Red Shirt",
        "additional_image_link": ["http://a/1.jpg", "http://a/2.jpg"],
        "installment": {"months": "12", "amount": "49.99 EUR"},
        "shipping": [{"country": "US", "price": "6.49 USD"}, {"country": "UK", "price": "5.99 GBP"}],
    }
    data = render_feed([product], registry, CHANNEL)
    report = parse_xml(data, registry)
    assert report.row_errors == []
    assert report.products == [product]
