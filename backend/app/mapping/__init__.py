from __future__ import annotations

from app.ingest.report import SourceField

from .document import MappingDocument, MappingDocumentError, MappingEntry
from .matcher import auto_match

__all__ = [
    "MappingDocument",
    "MappingDocumentError",
    "MappingEntry",
    "SourceField",
    "auto_match",
]
