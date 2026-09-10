import dataclasses

import pytest

from app.ingest import IngestReport
from app.ingest.delimited import parse_delimited
from app.ingest.report import SourceField
from app.ingest.xml_reader import parse_xml
from app.pipeline import RunState
from registry.model import (
    AttributeKind,
    ExportStatus,
    FeedDomain,
    RegistryAttribute,
    RegistryDocument,
    RequirementStatus,
    SubField,
)


class TestSourceField:
    def test_frozen_with_defaults(self):
        sf = SourceField(name="shipping", kind="group", sub_fields=("country", "price"))
        assert sf.name == "shipping"
        assert sf.kind == "group"
        assert sf.sub_fields == ("country", "price")
        assert SourceField(name="id", kind="scalar").sub_fields == ()

    def test_is_frozen(self):
        sf = SourceField(name="id", kind="scalar")
        with pytest.raises(dataclasses.FrozenInstanceError):
            sf.name = "other"


class TestIngestReportSourceFields:
    def test_defaults_to_empty_list(self):
        assert IngestReport().source_fields == []

    def test_instances_do_not_share_list(self):
        a = IngestReport()
        b = IngestReport()
        a.source_fields.append(SourceField(name="id", kind="scalar"))
        assert b.source_fields == []


class TestRunStateSourceFields:
    def test_defaults_to_empty_list(self):
        assert RunState().source_fields == []

    def test_instances_do_not_share_list(self):
        a = RunState()
        b = RunState()
        a.source_fields.append(SourceField(name="id", kind="scalar"))
        assert b.source_fields == []


def _scalar_attr(name: str) -> RegistryAttribute:
    return RegistryAttribute(
        name=name,
        kind=AttributeKind.SCALAR,
        type="String",
        required=RequirementStatus.OPTIONAL,
        domain=FeedDomain.PRIMARY,
        export_status=ExportStatus.EXPORTABLE,
    )


def _repeated_structured_attr(
    name: str, fields: tuple[SubField, ...]
) -> RegistryAttribute:
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


class TestDelimitedSourceFields:
    def test_tsv_header_maps_generic_to_scalar(self) -> None:
        reg = _registry({"title": _scalar_attr("title")})
        data = b"sku\ttitle\tshipping(country:price)\n1\tShirt\tUS:5\n"
        report = parse_delimited(data, "tsv", reg)

        assert report.source_fields == [
            SourceField("sku", "scalar", ()),
            SourceField("title", "scalar", ()),
            SourceField("shipping", "structured", ("country", "price")),
        ]

    def test_wide_tsv_repeated_structured_collapsed(self) -> None:
        reg = _registry({
            "id": _scalar_attr("id"),
            "title": _scalar_attr("title"),
            "shipping": _repeated_structured_attr(
                "shipping",
                (
                    SubField("country", "String", RequirementStatus.REQUIRED),
                    SubField("price", "Price", RequirementStatus.OPTIONAL),
                ),
            ),
        })
        data = (
            b"id\ttitle\tshipping(country:price)\tshipping(country:price)\n"
            b"1\tShirt\tUS:6.49 USD\tUK:5.99 GBP\n"
        )
        report = parse_delimited(data, "wide_tsv", reg)

        assert report.source_fields == [
            SourceField("id", "scalar", ()),
            SourceField("title", "scalar", ()),
            SourceField("shipping", "repeated_structured", ("country", "price"), 2),
        ]

    def test_empty_input_has_no_source_fields(self) -> None:
        reg = _registry({"id": _scalar_attr("id")})
        report = parse_delimited(b"", "tsv", reg)
        assert report.source_fields == []

    def test_wide_tsv_max_repeats_from_column_arity(self) -> None:
        reg = _registry({
            "id": _scalar_attr("id"),
            "shipping": _repeated_structured_attr(
                "shipping",
                (
                    SubField("country", "String", RequirementStatus.REQUIRED),
                    SubField("price", "Price", RequirementStatus.OPTIONAL),
                ),
            ),
        })
        data = (
            b"id\tshipping(country:price)\tshipping(country:price)\tshipping(country:price)\n"
            b"1\tUS:6.49\tUK:5.99\tDE:5.49\n"
        )
        report = parse_delimited(data, "wide_tsv", reg)
        by_name = {sf.name: sf for sf in report.source_fields}
        assert by_name["shipping"].kind == "repeated_structured"
        assert by_name["shipping"].max_repeats == 3


class TestXmlSourceFields:
    def test_infers_kinds_from_first_observed_shapes(self) -> None:
        reg = _registry({})
        data = (
            b"<rss><channel>"
            b"<item>"
            b"<sku>A</sku>"
            b"<images>a.jpg</images>"
            b"<images>b.jpg</images>"
            b"<shipping><country>US</country></shipping>"
            b"</item>"
            b"</channel></rss>"
        )
        report = parse_xml(data, reg)

        assert report.source_fields == [
            SourceField("sku", "scalar", ()),
            SourceField("images", "repeated_scalar", (), 2),
            SourceField("shipping", "structured", ("country",)),
        ]

    def test_shape_conflict_first_observed_wins(self) -> None:
        reg = _registry({})
        data = (
            b"<rss><channel>"
            b"<item><x>a</x></item>"
            b"<item><x>a</x><x>b</x></item>"
            b"</channel></rss>"
        )
        report = parse_xml(data, reg)

        assert report.source_fields == [SourceField("x", "repeated_scalar", (), 2)]

    def test_sub_fields_union_across_items(self) -> None:
        reg = _registry({})
        data = (
            b"<rss><channel>"
            b"<item><shipping><country>US</country></shipping></item>"
            b"<item><shipping><price>5</price></shipping></item>"
            b"</channel></rss>"
        )
        report = parse_xml(data, reg)

        assert report.source_fields == [
            SourceField("shipping", "structured", ("country", "price")),
        ]

    def test_repeated_structured_from_dict_siblings(self) -> None:
        reg = _registry({})
        data = (
            b"<rss><channel>"
            b"<item>"
            b"<shipping><country>US</country></shipping>"
            b"<shipping><country>UK</country></shipping>"
            b"</item>"
            b"</channel></rss>"
        )
        report = parse_xml(data, reg)

        assert report.source_fields == [
            SourceField("shipping", "repeated_structured", ("country",), 2),
        ]

    def test_no_items_has_no_source_fields(self) -> None:
        reg = _registry({})
        report = parse_xml(b"<rss><channel></channel></rss>", reg)
        assert report.source_fields == []

    def test_max_repeats_zero_for_scalar_and_structured(self) -> None:
        reg = _registry({})
        data = (
            b"<rss><channel>"
            b"<item><sku>A</sku><shipping><country>US</country></shipping></item>"
            b"</channel></rss>"
        )
        report = parse_xml(data, reg)
        assert report.source_fields == [
            SourceField("sku", "scalar", (), 0),
            SourceField("shipping", "structured", ("country",), 0),
        ]

    def test_max_repeats_largest_observed_list_length(self) -> None:
        reg = _registry({})
        data = (
            b"<rss><channel>"
            b"<item>"
            b"<images>a.jpg</images>"
            b"<shipping><country>US</country><price>1</price></shipping>"
            b"<shipping><country>UK</country><price>2</price></shipping>"
            b"<shipping><country>DE</country><price>3</price></shipping>"
            b"</item>"
            b"<item><images>a.jpg</images><images>b.jpg</images><images>c.jpg</images></item>"
            b"</channel></rss>"
        )
        report = parse_xml(data, reg)
        by_name = {sf.name: sf for sf in report.source_fields}
        assert by_name["shipping"].max_repeats == 3
        assert by_name["images"].max_repeats == 3

    def test_max_repeats_union_regression_first_item_missing_keys(self) -> None:
        """Spec §2.1: union sub-fields — first item lacks keys later items have."""
        reg = _registry({})
        data = (
            b"<rss><channel>"
            b"<item><product_detail><section_name>General</section_name></product_detail></item>"
            b"<item>"
            b"<product_detail><section_name>General</section_name></product_detail>"
            b"<product_detail>"
            b"<section_name>General</section_name>"
            b"<attribute_name>Battery</attribute_name>"
            b"<attribute_value>5000 mAh</attribute_value>"
            b"</product_detail>"
            b"</item>"
            b"</channel></rss>"
        )
        report = parse_xml(data, reg)
        pd = next(sf for sf in report.source_fields if sf.name == "product_detail")
        assert pd.kind == "repeated_structured"
        assert list(pd.sub_fields) == ["section_name", "attribute_name", "attribute_value"]
        assert pd.max_repeats == 2
