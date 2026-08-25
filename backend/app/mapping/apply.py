from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from registry.model import AttributeKind, RegistryDocument

from .document import MappingEntry


@dataclass
class ApplyStats:
    dropped_unmapped: int = 0
    shape_mismatches: int = 0


def apply_mapping(
    product: dict[str, Any],
    mappings: dict[str, MappingEntry],
    registry: RegistryDocument,
) -> tuple[dict[str, Any], ApplyStats]:
    stats = ApplyStats()
    result: dict[str, Any] = {}

    for source, value in product.items():
        entry = mappings.get(source)
        if entry is None:
            stats.dropped_unmapped += 1
            continue

        attr_name, _, subfield = entry.target.partition(".")
        attribute = registry.attributes.get(attr_name)
        if attribute is None:
            stats.shape_mismatches += 1
            continue

        if subfield:
            if isinstance(value, str):
                result.setdefault(attr_name, {})[subfield] = value
            else:
                stats.shape_mismatches += 1
            continue

        kind = attribute.kind
        if kind is AttributeKind.SCALAR:
            if isinstance(value, str):
                result[attr_name] = value
            else:
                stats.shape_mismatches += 1
        elif kind is AttributeKind.REPEATED_SCALAR:
            if isinstance(value, str):
                result[attr_name] = [value]
            elif isinstance(value, list) and all(isinstance(item, str) for item in value):
                result[attr_name] = list(value)
            else:
                stats.shape_mismatches += 1
        elif kind is AttributeKind.STRUCTURED:
            if isinstance(value, dict):
                known = {field.name for field in attribute.fields}
                result[attr_name] = {k: v for k, v in value.items() if k in known}
            else:
                stats.shape_mismatches += 1
        elif kind is AttributeKind.REPEATED_STRUCTURED:
            if isinstance(value, dict):
                result[attr_name] = [dict(value)]
            elif isinstance(value, list) and all(isinstance(item, dict) for item in value):
                result[attr_name] = [dict(item) for item in value]
            else:
                stats.shape_mismatches += 1

    return result, stats
