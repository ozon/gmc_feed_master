from pathlib import Path

from app.ingest.delimited import parse_delimited
from app.ingest.report import IngestReport, RowError
from registry.model import (
    AttributeKind,
    ExportStatus,
    FeedDomain,
    RegistryAttribute,
    RegistryDocument,
    RequirementStatus,
    SubField,
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


def _structured(name: str, fields: tuple[SubField, ...]) -> RegistryAttribute:
    return RegistryAttribute(
        name=name,
        kind=AttributeKind.STRUCTURED,
        type="Object",
        required=RequirementStatus.OPTIONAL,
        domain=FeedDomain.PRIMARY,
        export_status=ExportStatus.EXPORTABLE,
        fields=fields,
    )


def _repeated_structured(name: str, fields: tuple[SubField, ...]) -> RegistryAttribute:
    return RegistryAttribute(
        name=name,
        kind=AttributeKind.REPEATED_STRUCTURED,
        type="Object",
        required=RequirementStatus.OPTIONAL,
        domain=FeedDomain.PRIMARY,
        export_status=ExportStatus.EXPORTABLE,
        fields=fields,
    )


def _registry(attrs: dict[str, RegistryAttribute]) -> RegistryDocument:
    return RegistryDocument(attributes=attrs)


_SHIPPING_FIELDS = (
    SubField("country", "String", RequirementStatus.REQUIRED),
    SubField("price", "Price", RequirementStatus.OPTIONAL),
)


class TestTSVSimple:
    def test_three_products(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "price": _scalar("price"),
            "link": _scalar("link"),
        })
        data = (_FIXTURES / "simple.tsv").read_bytes()
        report = parse_delimited(data, "tsv", reg)

        assert isinstance(report, IngestReport)
        assert len(report.products) == 3
        assert report.row_errors == []
        assert report.products[0] == {
            "id": "1",
            "title": "Red Shirt",
            "price": "19.99",
            "link": "https://example.com/1",
        }
        assert report.products[1]["title"] == "Blue Hat"
        assert report.products[2]["title"] == "Green Pants"

    def test_empty_input(self) -> None:
        reg = _registry({"id": _scalar("id")})
        report = parse_delimited(b"", "tsv", reg)
        assert report.products == []
        assert report.row_errors == []


class TestCSV:
    def test_comma_delimited(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "price": _scalar("price"),
            "link": _scalar("link"),
        })
        data = (_FIXTURES / "simple.csv").read_bytes()
        report = parse_delimited(data, "csv", reg)

        assert len(report.products) == 2
        assert report.row_errors == []
        assert report.products[0]["title"] == "Red Shirt"


class TestWideTSV:
    def test_repeated_structured_columns(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "shipping": _repeated_structured("shipping", _SHIPPING_FIELDS),
        })
        data = (_FIXTURES / "wide.tsv").read_bytes()
        report = parse_delimited(data, "wide_tsv", reg)

        assert len(report.products) == 2
        assert report.row_errors == []
        first = report.products[0]
        assert first["shipping"] == [
            {"country": "US", "price": "6.49 USD"},
            {"country": "UK", "price": "5.99 GBP"},
        ]
        second = report.products[1]
        assert second["shipping"] == [
            {"country": "DE", "price": "7.99 EUR"},
        ]


class TestRepeatedScalar:
    def test_comma_split(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "additional_image_link": _scalar("additional_image_link"),
        })
        data = (_FIXTURES / "repeated.tsv").read_bytes()
        report = parse_delimited(data, "tsv", reg)

        assert len(report.products) == 2
        assert report.row_errors == []
        assert report.products[0]["additional_image_link"] == [
            "img1.jpg",
            "img2.jpg",
        ]
        assert report.products[1]["additional_image_link"] == "img3.jpg"


class TestMalformedRows:
    def test_bad_row_skipped_populates_errors(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "shipping": _repeated_structured("shipping", _SHIPPING_FIELDS),
        })
        data = (_FIXTURES / "malformed_rows.tsv").read_bytes()
        report = parse_delimited(data, "tsv", reg)

        assert len(report.row_errors) == 1
        err = report.row_errors[0]
        assert isinstance(err, RowError)
        assert err.line == 2
        assert "shipping" in err.message
        assert len(report.products) == 1
        assert report.products[0]["title"] == "Blue Hat"


class TestBOM:
    def test_bom_stripped(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "price": _scalar("price"),
            "link": _scalar("link"),
        })
        data = (_FIXTURES / "bom.tsv").read_bytes()
        report = parse_delimited(data, "tsv", reg)

        assert len(report.products) == 2
        assert report.row_errors == []
        assert report.products[0]["title"] == "Red Shirt"


class TestRFC4180:
    def test_quoted_multiline_cell_is_one_row(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "description": _scalar("description"),
        })
        data = b'id\tdescription\ttitle\n1\t"Line one\nLine two"\tShirt\n'
        report = parse_delimited(data, "tsv", reg)

        assert report.row_errors == []
        assert len(report.products) == 1
        assert report.products[0]["description"] == "Line one\nLine two"
        assert report.products[0]["title"] == "Shirt"

    def test_embedded_newline_row_error_line_points_at_row_end(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "shipping": _repeated_structured("shipping", _SHIPPING_FIELDS),
        })
        data = (
            b"id\tshipping(country:price)\n"
            b'1\t"US:6.49\nUSD"\n'
            b"2\tUS:6.49:extra:more\n"
        )
        report = parse_delimited(data, "tsv", reg)

        assert len(report.products) == 1
        assert len(report.row_errors) == 1
        assert report.row_errors[0].line == 4

    def test_multiline_fixture_parses(self) -> None:
        from registry.loader import load_registry

        reg = load_registry()
        data = (_FIXTURES / "multifeed.tsv").read_bytes()
        report = parse_delimited(data, "tsv", reg)

        assert len(report.products) == 14
        assert report.row_errors == []
        first = report.products[0]
        assert first["id"].startswith("shopify_US_")
        assert "\n" not in first["title"]
        assert "shipping" in first and isinstance(first["shipping"], dict)
        assert isinstance(first["additional_image_link"], list)


class TestEmptyCells:
    def test_empty_cells_omitted(self) -> None:
        data = b"id\ttitle\tprice\n1\tShirt\n"
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "price": _scalar("price"),
        })
        report = parse_delimited(data, "tsv", reg)

        assert len(report.products) == 1
        assert "price" not in report.products[0]
        assert report.products[0]["id"] == "1"
        assert report.products[0]["title"] == "Shirt"
