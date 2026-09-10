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
    first_line = text.split("\n", 1)[0]
    delimiter = _detect_delimiter(source_format, first_line)

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    parsed: list[tuple[int, list[str]]] = []
    for cells in reader:
        if any(cell.strip() for cell in cells):
            parsed.append((reader.line_num, cells))

    if not parsed:
        return IngestReport()

    plan = parse_header(parsed[0][1], registry)

    products: list[dict] = []
    row_errors: list[RowError] = []

    for line, cells in parsed[1:]:
        product, error = split_row(cells, plan)
        if error is not None:
            row_errors.append(RowError(line=line, message=error.message))
        else:
            products.append(product)

    scalar_repeats: dict[str, int] = {}
    for spec in plan.columns:
        if spec.kind != "repeated_scalar":
            continue
        for product in products:
            value = product.get(spec.name)
            if isinstance(value, list):
                scalar_repeats[spec.name] = max(
                    scalar_repeats.get(spec.name, 0), len(value)
                )

    source_fields = [
        SourceField(
            name=spec.name,
            kind="scalar" if spec.kind == "generic" else spec.kind,
            sub_fields=tuple(spec.sub_fields),
            max_repeats=scalar_repeats.get(spec.name, spec.max_repeats),
        )
        for spec in plan.columns
    ]

    return IngestReport(
        products=products, row_errors=row_errors, source_fields=source_fields
    )
