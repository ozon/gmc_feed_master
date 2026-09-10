from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from registry.model import AttributeKind, RegistryDocument

from .document import MappingEntry
from .indexed_path import IndexedPath, parse_indexed_path


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


def _entry_is_indexed(entry: MappingEntry) -> bool:
    try:
        return parse_indexed_path(entry.target).index is not None
    except ValueError:
        return False


def _set_indexed(
    result: dict[str, Any],
    parsed: IndexedPath,
    value: str,
) -> bool:
    """Write value into attr[N-1][sub] (N is 1-based); True on success."""
    assert parsed.index is not None
    idx0 = parsed.index - 1
    if parsed.sub is None:
        bucket = result.get(parsed.attr)
        if not isinstance(bucket, list):
            bucket = []
            result[parsed.attr] = bucket
        while len(bucket) <= idx0:
            bucket.append("")
        if not isinstance(value, str):
            return False
        bucket[idx0] = value
        return True
    bucket = result.get(parsed.attr)
    if not isinstance(bucket, list):
        bucket = []
        result[parsed.attr] = bucket
    while len(bucket) <= idx0:
        bucket.append({})
    if not isinstance(bucket[idx0], dict):
        return False
    bucket[idx0][parsed.sub] = value
    return True


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
            try:
                if parse_indexed_path(entry.target).index is not None:
                    continue  # deferred to the indexed pass (precedence)
            except ValueError:
                pass
            _apply_entry(result, source, value, entry, registry, stats)
        elif source not in parent_has_sub_mapping:
            stats.dropped_unmapped += 1

    # Pass 1: non-indexed sub-path source mappings in dict order.
    for key, entry in mappings.items():
        if key in product or "." not in key:
            continue
        if _entry_is_indexed(entry):
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

    # Pass 2: indexed target assignments, sorted by target path — override
    # broadcast values in their exact slot (operator directive 5).
    indexed = sorted(
        (
            (key, entry)
            for key, entry in mappings.items()
            if _entry_is_indexed(entry)
        ),
        key=lambda pair: pair[1].target,
    )
    for key, entry in indexed:
        if key in product:
            value = product[key]
            if isinstance(value, list):
                value = value[0] if len(value) == 1 else value
            _apply_entry(result, key, value, entry, registry, stats)
            continue
        parent, dot, sub = key.partition(".")
        if not dot or not sub or "." in sub or parent not in product:
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
    try:
        parsed = parse_indexed_path(entry.target)
    except ValueError:
        stats.shape_mismatches += 1
        return
    attribute = registry.attributes.get(parsed.attr)
    if attribute is None:
        stats.shape_mismatches += 1
        return
    kind = attribute.kind

    if parsed.index is not None:
        if kind not in (AttributeKind.REPEATED_SCALAR, AttributeKind.REPEATED_STRUCTURED):
            stats.shape_mismatches += 1
            return
        if parsed.sub is not None and kind is not AttributeKind.REPEATED_STRUCTURED:
            stats.shape_mismatches += 1
            return
        if not isinstance(value, str):
            stats.shape_mismatches += 1
            return
        if not _set_indexed(result, parsed, value):
            stats.shape_mismatches += 1
        return

    attr_name, subfield = parsed.attr, parsed.sub
    if subfield:
        if kind.value not in ("structured", "repeated_structured"):
            stats.shape_mismatches += 1
            return
        if isinstance(value, str):
            if kind is AttributeKind.STRUCTURED:
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
            if kind is AttributeKind.STRUCTURED:
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

    if kind is AttributeKind.SCALAR:
        if isinstance(value, str):
            result[attr_name] = value
        else:
            stats.shape_mismatches += 1
    elif kind is AttributeKind.REPEATED_SCALAR:
        if isinstance(value, str):
            result[attr_name] = [value]
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            result[attr_name] = [item for item in value if item != ""]
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
