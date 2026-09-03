from __future__ import annotations

from app.ingest.report import SourceField
from registry.model import RegistryDocument

from .document import MappingEntry

_SEPARATORS = str.maketrans("", "", "_-. ")

SYNONYMS: dict[str, str] = {
    "ean": "gtin",
    "upc": "gtin",
    "barcode": "gtin",
    "isbn": "gtin",
    "sku": "id",
    "itemid": "id",
    "itemnumber": "id",
    "producttitle": "title",
    "producturl": "link",
    "imageurl": "image_link",
    "additionalimages": "additional_image_link",
}

_COMPATIBLE_KINDS: dict[str, frozenset[str]] = {
    "scalar": frozenset({"scalar", "repeated_scalar"}),
    "repeated_scalar": frozenset({"repeated_scalar"}),
    "structured": frozenset({"structured", "repeated_structured"}),
    "repeated_structured": frozenset({"repeated_structured"}),
}

_STRUCTURED_SOURCE_KINDS = frozenset({"structured", "repeated_structured"})

_SUB_EFFECTIVE_KINDS: dict[str, str] = {
    "structured": "scalar",
    "repeated_structured": "repeated_scalar",
}


def _normalize(name: str) -> str:
    return name.lower().translate(_SEPARATORS)


def auto_match(
    source_fields: list[SourceField],
    registry: RegistryDocument,
    existing: dict[str, MappingEntry] | None = None,
) -> dict[str, MappingEntry]:
    result: dict[str, MappingEntry] = dict(existing or {})
    claimed = {entry.target for entry in result.values()}
    by_normalized = {_normalize(name): name for name in registry.attributes}

    def try_claim(field: SourceField, target: str, origin: str) -> None:
        if field.name in result or target in claimed:
            return
        attribute = registry.attributes[target]
        if attribute.kind.value not in _COMPATIBLE_KINDS.get(field.kind, frozenset()):
            return
        result[field.name] = MappingEntry(target=target, origin=origin)
        claimed.add(target)

    # Two passes enforce priority: auto (exact/normalized) beats synonym,
    # and within a pass the first source field in order wins the target.
    for field in source_fields:
        target = by_normalized.get(_normalize(field.name))
        if target is not None:
            try_claim(field, target, "auto")

    for field in source_fields:
        target = SYNONYMS.get(_normalize(field.name))
        if target is not None and target in registry.attributes:
            try_claim(field, target, "synonym")

    return result
