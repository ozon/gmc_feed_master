from __future__ import annotations

from app.ingest.report import SourceField

from .apply import ApplyStats, apply_mapping
from .document import MappingDocument, MappingDocumentError, MappingEntry
from .indexed_path import IndexedPath, parse_indexed_path
from .matcher import auto_match

__all__ = [
    "ApplyStats",
    "IndexedPath",
    "MappingDocument",
    "MappingDocumentError",
    "MappingEntry",
    "SourceField",
    "apply_mapping",
    "auto_match",
    "parse_indexed_path",
]
