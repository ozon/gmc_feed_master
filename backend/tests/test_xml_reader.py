from pathlib import Path

import pytest

from app.ingest.xml_reader import XmlParseError, parse_xml
from app.ingest.report import IngestReport, RowError
from registry.model import (
    AttributeKind,
    ExportStatus,
    FeedDomain,
    RegistryAttribute,
    RegistryDocument,
    RequirementStatus,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "feeds"


def _scalar(name: str) -> RegistryAttribute:
    return RegistryAttribute(
        name=name,
        kind=AttributeKind.SCALAR,
        type="String",
        required=RequirementStatus.OPTIONAL,
        domain=FeedDomain.PRIMARY,
        export_status=ExportStatus.EXPORTABLE,
    )


def _registry(attrs: dict[str, RegistryAttribute]) -> RegistryDocument:
    return RegistryDocument(attributes=attrs)


class TestRSS:
    def test_three_products(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "price": _scalar("price"),
            "link": _scalar("link"),
        })
        data = (_FIXTURES / "simple_rss.xml").read_bytes()
        report = parse_xml(data, reg)

        assert isinstance(report, IngestReport)
        assert len(report.products) == 3
        assert report.row_errors == []
        assert report.products[0] == {
            "id": "1",
            "title": "Red Shirt",
            "price": "19.99 USD",
            "link": "https://example.com/1",
        }
        assert report.products[1]["title"] == "Blue Hat"
        assert report.products[2]["title"] == "Green Pants"


class TestAtom:
    def test_three_products(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "price": _scalar("price"),
            "link": _scalar("link"),
        })
        data = (_FIXTURES / "simple_atom.xml").read_bytes()
        report = parse_xml(data, reg)

        assert isinstance(report, IngestReport)
        assert len(report.products) == 3
        assert report.row_errors == []
        assert report.products[0] == {
            "id": "1",
            "title": "Red Shirt",
            "price": "19.99 USD",
            "link": "https://example.com/1",
        }
        assert report.products[1]["title"] == "Blue Hat"
        assert report.products[2]["title"] == "Green Pants"


class TestNestedShipping:
    def test_nested_becomes_dict(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "shipping": _scalar("shipping"),
        })
        data = (_FIXTURES / "nested_shipping.xml").read_bytes()
        report = parse_xml(data, reg)

        assert len(report.products) == 1
        assert report.row_errors == []
        assert report.products[0]["shipping"] == {
            "country": "US",
            "price": "6.49 USD",
        }


class TestRepeatedImages:
    def test_repeated_siblings_become_list(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "additional_image_link": _scalar("additional_image_link"),
        })
        data = (_FIXTURES / "repeated_images.xml").read_bytes()
        report = parse_xml(data, reg)

        assert len(report.products) == 2
        assert report.row_errors == []
        assert report.products[0]["additional_image_link"] == [
            "https://example.com/1a.jpg",
            "https://example.com/1b.jpg",
        ]
        assert report.products[1]["additional_image_link"] == "https://example.com/2a.jpg"


class TestMalformedXML:
    def test_raises_xml_parse_error(self) -> None:
        reg = _registry({"id": _scalar("id")})
        data = (_FIXTURES / "malformed.xml").read_bytes()
        with pytest.raises(XmlParseError):
            parse_xml(data, reg)


class TestBadItem:
    def test_bad_item_skipped_with_error(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "price": _scalar("price"),
        })
        data = (_FIXTURES / "bad_item.xml").read_bytes()
        report = parse_xml(data, reg)

        assert len(report.products) == 1
        assert len(report.row_errors) == 1
        err = report.row_errors[0]
        assert isinstance(err, RowError)
        assert err.line == 2
        assert "shipping" in err.message.lower() or "item" in err.message.lower()
        assert report.products[0]["title"] == "Red Shirt"
