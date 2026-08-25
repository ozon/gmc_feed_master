import pytest

from app.ingest.flat_notation import HeaderError, HeaderPlan, ColumnSpec, parse_header
from registry.model import (
    AttributeKind,
    ExportStatus,
    FeedDomain,
    RegistryAttribute,
    RegistryDocument,
    RequirementStatus,
    SubField,
)


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


def _registry(attrs: dict[str, RegistryAttribute]) -> RegistryDocument:
    return RegistryDocument(attributes=attrs)


class TestParseHeaderBareScalar:
    def test_two_bare_scalars(self) -> None:
        reg = _registry({
            "title": _scalar("title"),
            "price": _scalar("price"),
        })
        plan = parse_header(["title", "price"], reg)
        assert plan.columns == [
            ColumnSpec(name="title", kind="scalar", sub_fields=[]),
            ColumnSpec(name="price", kind="scalar", sub_fields=[]),
        ]


class TestParseHeaderAnnotatedStructured:
    def test_annotated_structured(self) -> None:
        reg = _registry({
            "shipping": _structured("shipping", (
                SubField("country", "String", RequirementStatus.REQUIRED),
                SubField("price", "Price", RequirementStatus.OPTIONAL),
            )),
        })
        plan = parse_header(["shipping(country:price)"], reg)
        assert plan.columns == [
            ColumnSpec(name="shipping", kind="structured", sub_fields=["country", "price"]),
        ]


class TestParseHeaderRepeatedStructured:
    def test_repeated_structured(self) -> None:
        reg = _registry({
            "shipping": _structured("shipping", (
                SubField("country", "String", RequirementStatus.REQUIRED),
                SubField("price", "Price", RequirementStatus.OPTIONAL),
            )),
        })
        plan = parse_header(
            ["shipping(country:price)", "shipping(country:price)"], reg
        )
        assert plan.columns == [
            ColumnSpec(
                name="shipping",
                kind="repeated_structured",
                sub_fields=["country", "price"],
            ),
        ]


class TestParseHeaderGeneric:
    def test_unknown_attribute_is_generic(self) -> None:
        reg = _registry({
            "title": _scalar("title"),
        })
        plan = parse_header(["title", "internal_sku"], reg)
        assert plan.columns == [
            ColumnSpec(name="title", kind="scalar", sub_fields=[]),
            ColumnSpec(name="internal_sku", kind="generic", sub_fields=[]),
        ]


class TestParseHeaderBareStructuredError:
    def test_bare_structured_column_raises(self) -> None:
        reg = _registry({
            "shipping": _structured("shipping", (
                SubField("country", "String", RequirementStatus.REQUIRED),
                SubField("price", "Price", RequirementStatus.OPTIONAL),
            )),
        })
        with pytest.raises(HeaderError, match="shipping"):
            parse_header(["shipping"], reg)


class TestParseHeaderUnknownSubFieldError:
    def test_unknown_sub_field_raises(self) -> None:
        reg = _registry({
            "shipping": _structured("shipping", (
                SubField("country", "String", RequirementStatus.REQUIRED),
                SubField("price", "Price", RequirementStatus.OPTIONAL),
            )),
        })
        with pytest.raises(HeaderError, match="contry"):
            parse_header(["shipping(contry:price)"], reg)


class TestParseHeaderDuplicateScalarError:
    def test_duplicate_scalar_raises(self) -> None:
        reg = _registry({
            "title": _scalar("title"),
        })
        with pytest.raises(HeaderError, match="title"):
            parse_header(["title", "title"], reg)
