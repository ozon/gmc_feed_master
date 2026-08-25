from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Any

from registry.model import AttributeKind, RegistryDocument


class HeaderError(Exception):
    def __init__(self, message: str, *, column: str = "") -> None:
        self.column = column
        super().__init__(message)


@dataclass(frozen=True)
class RowError:
    message: str
    row_number: int = 0


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    kind: str
    sub_fields: list[str]
    arity: int = 1


@dataclass(frozen=True)
class HeaderPlan:
    columns: list[ColumnSpec]


_ANNOTATED_RE = re.compile(r"^(\w+)\(([^)]+)\)$")


def parse_header(
    headers: list[str], registry: RegistryDocument
) -> HeaderPlan:
    columns: list[ColumnSpec] = []
    seen: dict[str, int] = {}

    for header in headers:
        m = _ANNOTATED_RE.match(header)
        if m:
            name = m.group(1)
            raw_subfields = m.group(2)
            sub_fields = [s.strip() for s in raw_subfields.split(":") if s.strip()]

            attr = registry.attributes.get(name)
            if attr is not None:
                if attr.kind not in (
                    AttributeKind.STRUCTURED,
                    AttributeKind.REPEATED_STRUCTURED,
                ):
                    raise HeaderError(
                        f"Column '{header}' annotates a non-structured attribute",
                        column=header,
                    )

                registry_field_names = {f.name for f in attr.fields}
                for sf in sub_fields:
                    if sf not in registry_field_names:
                        raise HeaderError(
                            f"Column '{header}' references unknown sub-field '{sf}'",
                            column=header,
                        )

            prev = seen.get(name, 0)
            if prev >= 1:
                kind = "repeated_structured"
            else:
                kind = "structured"
            seen[name] = prev + 1

            if prev == 0:
                columns.append(
                    ColumnSpec(name=name, kind=kind, sub_fields=sub_fields, arity=1)
                )
            else:
                existing = columns[-1]
                columns[-1] = ColumnSpec(
                    name=existing.name,
                    kind=kind,
                    sub_fields=existing.sub_fields,
                    arity=prev + 1,
                )
        else:
            attr = registry.attributes.get(header)
            if attr is not None:
                if attr.kind in (
                    AttributeKind.STRUCTURED,
                    AttributeKind.REPEATED_STRUCTURED,
                ):
                    raise HeaderError(
                        f"Column '{header}' is a structured attribute and requires annotation "
                        f"'{header}(...)'",
                        column=header,
                    )
                kind = "scalar"
            else:
                kind = "generic"

            prev = seen.get(header, 0)
            if prev >= 1:
                raise HeaderError(
                    f"Duplicate column '{header}'",
                    column=header,
                )
            seen[header] = prev + 1

            columns.append(
                ColumnSpec(name=header, kind=kind, sub_fields=[])
            )

    return HeaderPlan(columns=columns)


def _split_csv_cell(cell: str) -> list[str] | str:
    """Split a cell by comma, respecting RFC-4180 quoting.

    Returns a list if the cell contains commas (split or quoted).
    Returns a bare string if it's a single unquoted value.
    """
    reader = csv.reader(io.StringIO(cell), delimiter=",")
    for row in reader:
        if len(row) > 1:
            return row
        # Single element: check if it was a quoted cell (RFC-4180)
        if cell.startswith('"') and cell.endswith('"'):
            return row  # single-element list
        return row[0]  # bare string
    return cell


def split_row(
    cells: list[str], plan: HeaderPlan
) -> tuple[dict[str, Any], RowError | None]:
    result: dict[str, Any] = {}
    col_idx = 0

    for spec in plan.columns:
        if spec.kind == "repeated_structured":
            n_cols = spec.arity

            structs: list[dict[str, Any]] = []
            for i in range(n_cols):
                cell = cells[col_idx + i] if col_idx + i < len(cells) else ""
                if not cell:
                    continue
                parts = cell.split(":")
                expected = len(spec.sub_fields)
                if len(parts) > expected:
                    return result, RowError(
                        message=f"Column '{spec.name}' has {len(parts)} colon-separated "
                        f"parts but expected {expected}"
                    )
                if len(parts) < expected:
                    # Pad with empty strings
                    parts.extend([""] * (expected - len(parts)))
                struct = dict(zip(spec.sub_fields, parts))
                structs.append(struct)

            if structs:
                result[spec.name] = structs
            col_idx += n_cols

        elif spec.kind == "structured":
            cell = cells[col_idx] if col_idx < len(cells) else ""
            col_idx += 1
            if not cell:
                continue
            parts = cell.split(":")
            expected = len(spec.sub_fields)
            if len(parts) > expected:
                return result, RowError(
                    message=f"Column '{spec.name}' has {len(parts)} colon-separated "
                    f"parts but expected {expected}"
                )
            if len(parts) < expected:
                parts.extend([""] * (expected - len(parts)))
            result[spec.name] = dict(zip(spec.sub_fields, parts))

        else:
            # scalar or generic
            cell = cells[col_idx] if col_idx < len(cells) else ""
            col_idx += 1
            if not cell:
                continue
            values = _split_csv_cell(cell)
            result[spec.name] = values

    return result, None
