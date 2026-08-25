from __future__ import annotations

from registry.model import RegistryDocument

from .delimited import parse_delimited
from .fetch import FetchError, HttpFetcher
from .report import IngestReport, RowError
from .xml_reader import XmlParseError, parse_xml

__all__ = [
    "FetchError",
    "HttpFetcher",
    "IngestReport",
    "RowError",
    "XmlParseError",
    "read_feed",
]


def read_feed(
    data: bytes, source_format: str, registry: RegistryDocument
) -> IngestReport:
    if source_format in ("tsv", "csv", "wide_tsv"):
        return parse_delimited(data, source_format, registry)
    if source_format == "xml":
        return parse_xml(data, registry)
    raise ValueError(f"unsupported source format: {source_format!r}")
