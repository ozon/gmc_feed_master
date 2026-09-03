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

    def has_sub_mapping(field: SourceField) -> bool:
        prefix = f"{field.name}."
        return any(key.startswith(prefix) for key in result)

    def try_claim(field: SourceField, target: str, origin: str) -> None:
        if field.name in result or target in claimed:
            return
        if any(claimed_target.startswith(f"{target}.") for claimed_target in claimed):
            return
        attribute = registry.attributes[target]
        if attribute.kind.value not in _COMPATIBLE_KINDS.get(field.kind, frozenset()):
            return
        result[field.name] = MappingEntry(target=target, origin=origin)
        claimed.add(target)

    def try_claim_sub(field: SourceField, sub: str, target: str) -> bool:
        key = f"{field.name}.{sub}"
        attr_name, _, attr_sub = target.partition(".")
        if key in result or target in claimed or attr_name in claimed:
            return False
        attribute = registry.attributes.get(attr_name)
        if attribute is None:
            return False
        effective = _SUB_EFFECTIVE_KINDS.get(field.kind, "")
        if attr_sub:
            if attribute.kind.value not in _STRUCTURED_SOURCE_KINDS:
                return False
            if attr_sub not in {f.name for f in attribute.fields}:
                return False
        elif attribute.kind.value not in _COMPATIBLE_KINDS.get(effective, frozenset()):
            return False
        result[key] = MappingEntry(target=target, origin="auto")
        claimed.add(target)
        return True

    # Two passes enforce priority: auto (exact/normalized) beats synonym,
    # and within a pass the first source field in order wins the target.
    for field in source_fields:
        if has_sub_mapping(field):
            continue
        target = by_normalized.get(_normalize(field.name))
        if target is not None:
            try_claim(field, target, "auto")

    for field in source_fields:
        if has_sub_mapping(field):
            continue
        target = SYNONYMS.get(_normalize(field.name))
        if target is not None and target in registry.attributes:
            try_claim(field, target, "synonym")

    for field in source_fields:
        if field.kind not in _STRUCTURED_SOURCE_KINDS or field.name in result:
            continue
        for sub in field.sub_fields:
            whole_target = by_normalized.get(_normalize(sub))
            if whole_target is not None and try_claim_sub(field, sub, whole_target):
                continue
            for attr_name, attribute in registry.attributes.items():
                if attribute.kind.value not in _STRUCTURED_SOURCE_KINDS:
                    continue
                for attr_sub in attribute.fields:
                    if _normalize(attr_sub.name) == _normalize(sub) and try_claim_sub(
                        field, sub, f"{attr_name}.{attr_sub.name}"
                    ):
                        break
                else:
                    continue
                break

    return result
