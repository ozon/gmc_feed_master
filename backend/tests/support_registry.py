"""Minimal two-attribute GMC registry for renderer tests."""

from registry.model import (
    AttributeKind,
    ExportStatus,
    FeedDomain,
    RegistryAttribute,
    RegistryDocument,
    RequirementStatus,
)


def _scalar_attribute(name: str) -> RegistryAttribute:
    return RegistryAttribute(
        name=name,
        kind=AttributeKind.SCALAR,
        type="string",
        required=RequirementStatus.OPTIONAL,
        domain=FeedDomain.PRIMARY,
        export_status=ExportStatus.EXPORTABLE,
        fields=(),
    )


def minimal_gmc_registry() -> RegistryDocument:
    return RegistryDocument(
        attributes={
            "title": _scalar_attribute("title"),
            "google_product_category": _scalar_attribute("google_product_category"),
        }
    )
