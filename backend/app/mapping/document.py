from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ingest.report import SourceField

ALLOWED_ORIGINS = ("auto", "synonym", "manual")


class MappingDocumentError(Exception):
    pass


@dataclass
class MappingEntry:
    target: str
    origin: str


@dataclass
class MappingDocument:
    version: int = 1
    auto_mapped: bool = False
    source_fields: list[SourceField] = field(default_factory=list)
    mappings: dict[str, MappingEntry] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> MappingDocument:
        return cls()

    @classmethod
    def from_json(cls, raw: Any) -> MappingDocument:
        if raw is None:
            return cls.empty()
        if not isinstance(raw, dict):
            raise MappingDocumentError(
                f"mapping document must be an object, got {type(raw).__name__}"
            )
        version = raw.get("version", 1)
        if not isinstance(version, int) or isinstance(version, bool):
            raise MappingDocumentError(
                f"'version' must be an int, got {type(version).__name__}"
            )
        auto_mapped = raw.get("auto_mapped", False)
        if not isinstance(auto_mapped, bool):
            raise MappingDocumentError(
                f"'auto_mapped' must be a bool, got {type(auto_mapped).__name__}"
            )
        return cls(
            version=version,
            auto_mapped=auto_mapped,
            source_fields=_parse_source_fields(raw.get("source_fields", [])),
            mappings=_parse_mappings(raw.get("mappings", {})),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "auto_mapped": self.auto_mapped,
            "source_fields": [
                {
                    "name": sf.name,
                    "kind": sf.kind,
                    "sub_fields": list(sf.sub_fields),
                }
                for sf in self.source_fields
            ],
            "mappings": {
                source: {"target": entry.target, "origin": entry.origin}
                for source, entry in self.mappings.items()
            },
        }


def _parse_source_fields(raw: Any) -> list[SourceField]:
    if not isinstance(raw, list):
        raise MappingDocumentError(
            f"'source_fields' must be a list, got {type(raw).__name__}"
        )
    result: list[SourceField] = []
    for item in raw:
        if not isinstance(item, dict):
            raise MappingDocumentError(
                f"source field entry must be an object, got {type(item).__name__}"
            )
        name = item.get("name")
        kind = item.get("kind")
        if not isinstance(name, str):
            raise MappingDocumentError(
                f"source field 'name' must be a string, got {type(name).__name__}"
            )
        if not isinstance(kind, str):
            raise MappingDocumentError(
                f"source field 'kind' must be a string, got {type(kind).__name__}"
            )
        sub_fields = item.get("sub_fields", [])
        if not isinstance(sub_fields, list) or not all(
            isinstance(sub, str) for sub in sub_fields
        ):
            raise MappingDocumentError(
                f"source field 'sub_fields' must be a list of strings for {name!r}"
            )
        result.append(SourceField(name=name, kind=kind, sub_fields=tuple(sub_fields)))
    return result


def _parse_mappings(raw: Any) -> dict[str, MappingEntry]:
    if not isinstance(raw, dict):
        raise MappingDocumentError(
            f"'mappings' must be an object, got {type(raw).__name__}"
        )
    result: dict[str, MappingEntry] = {}
    for source, item in raw.items():
        if not isinstance(item, dict):
            raise MappingDocumentError(
                f"mapping entry for {source!r} must be an object, "
                f"got {type(item).__name__}"
            )
        target = item.get("target")
        origin = item.get("origin")
        if not isinstance(target, str):
            raise MappingDocumentError(
                f"mapping entry for {source!r}: 'target' must be a string, "
                f"got {type(target).__name__}"
            )
        if origin not in ALLOWED_ORIGINS:
            raise MappingDocumentError(
                f"mapping entry for {source!r}: 'origin' must be one of "
                f"{ALLOWED_ORIGINS}, got {origin!r}"
            )
        result[source] = MappingEntry(target=target, origin=origin)
    return result
