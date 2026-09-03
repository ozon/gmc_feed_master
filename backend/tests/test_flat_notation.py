import pytest

from app.ingest.flat_notation import (
    HeaderError,
    HeaderPlan,
    ColumnSpec,
    RowError,
    parse_header,
    split_row,
)
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
                arity=2,
            ),
        ]


class TestParseHeaderNonAdjacentRepeatError:
    def test_non_adjacent_repeated_structured_raises(self) -> None:
        reg = _registry({
            "shipping": _structured("shipping", (
                SubField("country", "String", RequirementStatus.REQUIRED),
                SubField("price", "Price", RequirementStatus.OPTIONAL),
            )),
            "title": _scalar("title"),
        })
        with pytest.raises(HeaderError, match="shipping"):
            parse_header(
                ["shipping(country:price)", "title", "shipping(country:price)"], reg
            )


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


class TestParseHeaderBareStructured:
    def test_bare_structured_becomes_generic(self) -> None:
        reg = _registry({
            "shipping": _structured("shipping", (
                SubField("country", "String", RequirementStatus.REQUIRED),
                SubField("price", "Price", RequirementStatus.OPTIONAL),
            )),
        })
        plan = parse_header(["shipping"], reg)
        assert plan.columns == [
            ColumnSpec(name="shipping", kind="generic", sub_fields=[]),
        ]


class TestParseHeaderBareRepeatedScalar:
    def test_bare_repeated_scalar_attribute_kind(self) -> None:
        reg = _registry({
            "additional_image_link": RegistryAttribute(
                name="additional_image_link",
                kind=AttributeKind.REPEATED_SCALAR,
                type="URL",
                required=RequirementStatus.OPTIONAL,
                domain=FeedDomain.PRIMARY,
                export_status=ExportStatus.EXPORTABLE,
            ),
        })
        plan = parse_header(["additional_image_link"], reg)
        assert plan.columns == [
            ColumnSpec(name="additional_image_link", kind="repeated_scalar", sub_fields=[]),
        ]


class TestParseHeaderLenientSubFields:
    def test_unknown_sub_field_is_kept_positionally(self) -> None:
        reg = _registry({
            "shipping": _structured("shipping", (
                SubField("country", "String", RequirementStatus.REQUIRED),
                SubField("price", "Price", RequirementStatus.OPTIONAL),
            )),
        })
        plan = parse_header(["shipping(country:unknown_thing:price)"], reg)
        assert plan.columns == [
            ColumnSpec(
                name="shipping",
                kind="structured",
                sub_fields=["country", "unknown_thing", "price"],
            ),
        ]

    def test_unknown_sub_field_value_alignment_preserved(self) -> None:
        reg = _registry({
            "shipping": _structured("shipping", (
                SubField("country", "String", RequirementStatus.REQUIRED),
                SubField("price", "Price", RequirementStatus.OPTIONAL),
            )),
        })
        plan = parse_header(["shipping(country:unknown_thing:price)"], reg)
        result, err = split_row(["US:middle:6.49 USD"], plan)
        assert err is None
        assert result == {"shipping": {"country": "US", "unknown_thing": "middle", "price": "6.49 USD"}}

    def test_registry_known_attribute_with_unknown_subfields_repeats_ok(self) -> None:
        reg = _registry({
            "tax": _structured("tax", (
                SubField("country", "String", RequirementStatus.REQUIRED),
                SubField("rate", "String", RequirementStatus.OPTIONAL),
                SubField("tax_ship", "Boolean", RequirementStatus.OPTIONAL),
            )),
        })
        plan = parse_header(
            ["tax(country:location_group_name:rate:tax_ship)", "tax(country:location_group_name:rate:tax_ship)"],
            reg,
        )
        assert plan.columns == [
            ColumnSpec(
                name="tax",
                kind="repeated_structured",
                sub_fields=["country", "location_group_name", "rate", "tax_ship"],
                arity=2,
            ),
        ]


class TestParseHeaderDuplicateScalarError:
    def test_duplicate_scalar_raises(self) -> None:
        reg = _registry({
            "title": _scalar("title"),
        })
        with pytest.raises(HeaderError, match="title"):
            parse_header(["title", "title"], reg)


class TestParseHeaderStillStrict:
    def test_annotating_non_structured_attribute_raises(self) -> None:
        reg = _registry({
            "title": _scalar("title"),
        })
        with pytest.raises(HeaderError, match="non-structured"):
            parse_header(["title(a:b)"], reg)

    def test_duplicate_scalar_raises(self) -> None:
        reg = _registry({
            "title": _scalar("title"),
        })
        with pytest.raises(HeaderError, match="title"):
            parse_header(["title", "title"], reg)


class TestSplitRowScalar:
    def test_scalar_value(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="title", kind="scalar", sub_fields=[]),
        ])
        result, err = split_row(["Red Shirt"], plan)
        assert result == {"title": "Red Shirt"}
        assert err is None

    def test_empty_cell_omitted(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="title", kind="scalar", sub_fields=[]),
        ])
        result, err = split_row([""], plan)
        assert result == {}
        assert err is None

    def test_two_scalars(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="title", kind="scalar", sub_fields=[]),
            ColumnSpec(name="price", kind="scalar", sub_fields=[]),
        ])
        result, err = split_row(["Red Shirt", "19.99"], plan)
        assert result == {"title": "Red Shirt", "price": "19.99"}
        assert err is None


class TestSplitRowRepeatedScalar:
    def test_comma_separated(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="additional_image_link", kind="repeated_scalar", sub_fields=[]),
        ])
        result, err = split_row(["img1.jpg,img2.jpg"], plan)
        assert result == {"additional_image_link": ["img1.jpg", "img2.jpg"]}
        assert err is None

    def test_quoted_comma_preserved(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="additional_image_link", kind="repeated_scalar", sub_fields=[]),
        ])
        result, err = split_row(['"img1.jpg,img2.jpg"'], plan)
        assert result == {"additional_image_link": ["img1.jpg,img2.jpg"]}
        assert err is None

    def test_single_value_no_split(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="additional_image_link", kind="repeated_scalar", sub_fields=[]),
        ])
        result, err = split_row(["img1.jpg"], plan)
        assert result == {"additional_image_link": "img1.jpg"}
        assert err is None


class TestSplitRowScalarKeepsCommas:
    def test_scalar_cell_with_commas_stays_whole(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="description", kind="scalar", sub_fields=[]),
        ])
        result, err = split_row(["Classic, confident, crafted"], plan)
        assert result == {"description": "Classic, confident, crafted"}
        assert err is None

    def test_generic_cell_with_commas_stays_whole(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="internal_note", kind="generic", sub_fields=[]),
        ])
        result, err = split_row(["note one, note two"], plan)
        assert result == {"internal_note": "note one, note two"}
        assert err is None


class TestSplitRowStructured:
    def test_annotated_structured(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="shipping", kind="structured", sub_fields=["country", "price"]),
        ])
        result, err = split_row(["US:6.49 USD"], plan)
        assert result == {"shipping": {"country": "US", "price": "6.49 USD"}}
        assert err is None

    def test_surplus_colons_returns_error(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="shipping", kind="structured", sub_fields=["country", "price"]),
        ])
        result, err = split_row(["US:6.49:extra"], plan)
        assert err is not None
        assert "shipping" in err.message

    def test_empty_structured_cell_omitted(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="shipping", kind="structured", sub_fields=["country", "price"]),
        ])
        result, err = split_row([""], plan)
        assert result == {}
        assert err is None


class TestSplitRowRepeatedStructured:
    def test_two_columns(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="shipping", kind="repeated_structured", sub_fields=["country", "price"], arity=2),
        ])
        result, err = split_row(["US:6.49 USD", "UK:5.99 GBP"], plan)
        assert result == {
            "shipping": [
                {"country": "US", "price": "6.49 USD"},
                {"country": "UK", "price": "5.99 GBP"},
            ]
        }
        assert err is None

    def test_one_empty_one_filled(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="shipping", kind="repeated_structured", sub_fields=["country", "price"], arity=2),
        ])
        result, err = split_row(["US:6.49 USD", ""], plan)
        assert result == {
            "shipping": [
                {"country": "US", "price": "6.49 USD"},
            ]
        }
        assert err is None

    def test_surplus_colons_in_repeated_returns_error(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="shipping", kind="repeated_structured", sub_fields=["country", "price"], arity=2),
        ])
        result, err = split_row(["US:6.49:extra", "UK:5.99 GBP"], plan)
        assert err is not None
