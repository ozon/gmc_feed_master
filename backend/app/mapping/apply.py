from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from registry.model import AttributeKind, RegistryDocument

from .document import MappingEntry


@dataclass
class ApplyStats:
    dropped_unmapped: int = 0
    shape_mismatches: int = 0


def _sub_values(value: Any, sub: str) -> tuple[list[str] | None, bool]:
    if isinstance(value, dict):
        item = value.get(sub)
        if item is None:
            return None, False
        if not isinstance(item, str):
            return None, True
        return [item], False
    if isinstance(value, list):
        if not all(isinstance(elem, dict) for elem in value):
            return None, True
        result: list[str] = []
        for elem in value:
            item = elem.get(sub)
            if item is None:
                result.append("")
                continue
            if not isinstance(item, str):
                return None, True
            result.append(item)
        if not any(result):
            return None, False
        return result, False
    return None, False


def _merge_elementwise(
    result: dict[str, Any], attr_name: str, subfield: str, values: list[str]
) -> None:
    bucket = result.get(attr_name)
    if not isinstance(bucket, list):
        bucket = []
        result[attr_name] = bucket
    while len(bucket) < len(values):
        bucket.append({})
    for index, item in enumerate(values):
        if item == "":
            continue
        bucket[index][subfield] = item


def apply_mapping(
    product: dict[str, Any],
    mappings: dict[str, MappingEntry],
    registry: RegistryDocument,
) -> tuple[dict[str, Any], ApplyStats]:
    stats = ApplyStats()
    result: dict[str, Any] = {}
    parent_has_sub_mapping = {
        key.partition(".")[0]
        for key in mappings
        if "." in key and key not in product
    }

    for source, value in product.items():
        entry = mappings.get(source)
        if entry is not None:
            _apply_entry(result, source, value, entry, registry, stats)
        elif source not in parent_has_sub_mapping:
            stats.dropped_unmapped += 1

    for key, entry in mappings.items():
        if key in product or "." not in key:
            continue
        parent, _, sub = key.partition(".")
        if not sub or "." in sub or parent not in product:
            continue
        values, mismatch = _sub_values(product[parent], sub)
        if mismatch:
            stats.shape_mismatches += 1
            continue
        if values is not None:
            value = values[0] if len(values) == 1 else values
            _apply_entry(result, key, value, entry, registry, stats)

    return result, stats


def _apply_entry(
    result: dict[str, Any],
    source: str,
    value: Any,
    entry: MappingEntry,
    registry: RegistryDocument,
    stats: ApplyStats,
) -> None:
    attr_name, _, subfield = entry.target.partition(".")
    attribute = registry.attributes.get(attr_name)
    if attribute is None:
        stats.shape_mismatches += 1
        return

    if subfield:
        if attribute.kind.value not in ("structured", "repeated_structured"):
            stats.shape_mismatches += 1
            return
        if isinstance(value, str):
            if attribute.kind is AttributeKind.STRUCTURED:
                bucket = result.setdefault(attr_name, {})
                if isinstance(bucket, dict):
                    bucket[subfield] = value
                return
            bucket = result.get(attr_name)
            if not isinstance(bucket, list):
                bucket = []
                result[attr_name] = bucket
            if not bucket:
                bucket.append({})
            bucket[0][subfield] = value
            return
        if isinstance(value, list):
            if attribute.kind is AttributeKind.STRUCTURED:
                if len(value) == 1:
                    bucket = result.setdefault(attr_name, {})
                    if isinstance(bucket, dict):
                        bucket[subfield] = value[0]
                    return
                stats.shape_mismatches += 1
                return
            _merge_elementwise(result, attr_name, subfield, value)
            return
        stats.shape_mismatches += 1
        return

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
