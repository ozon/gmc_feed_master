from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import (
    AttributeKind,
    Cardinality,
    Constraints,
    ExportStatus,
    FeedDomain,
    RegistryAttribute,
    RegistryDocument,
    RequirementStatus,
    SubField,
)

_SUPPORTED_VERSIONS = {1}
_DEFAULT_PATH = Path(__file__).resolve().parent / "attributes.json"


class RegistryLoadError(Exception):
    def __init__(self, path: Path, message: str) -> None:
        self.path = path
        super().__init__(f"{message}: {path}")


def _coerce_str(value: Any, field: str, path: Path) -> str:
    if not isinstance(value, str):
        raise RegistryLoadError(path, f"invalid {field!r} type")
    return value


def _parse_sub_fields(raw: list[dict[str, Any]], path: Path) -> tuple[SubField, ...]:
    result: list[SubField] = []
    for item in raw:
        constraints_raw = item.get("constraints") or {}
        result.append(SubField(
            name=_coerce_str(item.get("name"), "field.name", path),
            type=_coerce_str(item.get("type"), "field.type", path),
            required=RequirementStatus(_coerce_str(item.get("required"), "field.required", path)),
            enum_values=tuple(item.get("enum_values", [])),
            constraints=Constraints(
                max_length=constraints_raw.get("max_length"),
                min_length=constraints_raw.get("min_length"),
                format=constraints_raw.get("format"),
            ),
        ))
    return tuple(result)


def _parse_attributes(raw: dict[str, Any], path: Path) -> dict[str, RegistryAttribute]:
    attributes: dict[str, RegistryAttribute] = {}
    for name, item in raw.items():
        constraints_raw = item.get("constraints") or {}
        cardinality_raw = item.get("cardinality") or {}
        attributes[name] = RegistryAttribute(
            name=name,
            kind=AttributeKind(_coerce_str(item.get("kind"), "kind", path)),
            type=_coerce_str(item.get("type"), "type", path),
            required=RequirementStatus(_coerce_str(item.get("required"), "required", path)),
            domain=FeedDomain(_coerce_str(item.get("domain"), "domain", path)),
            export_status=ExportStatus(_coerce_str(item.get("export_status"), "export_status", path)),
            fields=_parse_sub_fields(item.get("fields", []), path),
            enum_values=tuple(item.get("enum_values", [])),
            cardinality=Cardinality(
                max_items=cardinality_raw.get("max_items"),
                min_items=cardinality_raw.get("min_items"),
                item_max_length=cardinality_raw.get("item_max_length"),
            ),
            constraints=Constraints(
                max_length=constraints_raw.get("max_length"),
                min_length=constraints_raw.get("min_length"),
                format=constraints_raw.get("format"),
            ),
            source_line=item.get("source_line", 0),
            source_lines=tuple(item.get("source_lines", [])),
            applicability=tuple(FeedDomain(d) for d in item.get("applicability", [])),
            qualifiers=tuple(item.get("qualifiers", [])),
            metadata=tuple(item.get("metadata", {}).items()),
        )
    return attributes


def load_registry(path: Path | None = None) -> RegistryDocument:
    path = Path(path) if path is not None else _DEFAULT_PATH

    if not path.exists():
        raise RegistryLoadError(path, "artifact missing")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RegistryLoadError(path, "invalid JSON") from exc

    if not isinstance(data, dict):
        raise RegistryLoadError(path, "invalid JSON structure")

    version = data.get("version")
    if version not in _SUPPORTED_VERSIONS:
        raise RegistryLoadError(path, f"unsupported version {version!r}")

    raw_attrs = data.get("attributes")
    if not isinstance(raw_attrs, dict):
        raise RegistryLoadError(path, "missing or invalid attributes")

    return RegistryDocument(
        attributes=_parse_attributes(raw_attrs, path),
        source=data.get("source_fingerprint", ""),
        version=version,
    )
