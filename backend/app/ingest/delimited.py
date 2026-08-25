from __future__ import annotations

import csv
import io

from registry.model import RegistryDocument

from .flat_notation import HeaderError, parse_header, split_row
from .report import IngestReport, RowError, SourceField


def _detect_delimiter(source_format: str, sample: str) -> str:
    if source_format in ("tsv", "wide_tsv"):
        return "\t"
    if source_format == "csv":
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;")
            return dialect.delimiter
        except csv.Error:
            return ","
    raise ValueError(f"unsupported source format: {source_format!r}")


def parse_delimited(
    data: bytes, source_format: str, registry: RegistryDocument
) -> IngestReport:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]

    text = data.decode("utf-8")
    lines = text.splitlines()
    non_blank = [line for line in lines if line.strip()]
    if not non_blank:
        return IngestReport()

    header_line = non_blank[0]
    delimiter = _detect_delimiter(source_format, header_line)

    header_reader = csv.reader(io.StringIO(header_line), delimiter=delimiter)
    headers = next(header_reader)
    plan = parse_header(headers, registry)

    source_fields = [
        SourceField(
            name=spec.name,
            kind="scalar" if spec.kind == "generic" else spec.kind,
            sub_fields=tuple(spec.sub_fields),
        )
        for spec in plan.columns
    ]

    products: list[dict] = []
    row_errors: list[RowError] = []

    for line_idx, line in enumerate(non_blank[1:], start=2):
        row_reader = csv.reader(io.StringIO(line), delimiter=delimiter)
        cells = next(row_reader)
        product, error = split_row(cells, plan)
        if error is not None:
            row_errors.append(RowError(line=line_idx, message=error.message))
        else:
            products.append(product)

    return IngestReport(
        products=products, row_errors=row_errors, source_fields=source_fields
    )
