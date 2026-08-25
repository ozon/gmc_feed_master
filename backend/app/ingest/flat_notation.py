from __future__ import annotations

import re
from dataclasses import dataclass

from registry.model import AttributeKind, RegistryDocument


class HeaderError(Exception):
    def __init__(self, message: str, *, column: str = "") -> None:
        self.column = column
        super().__init__(message)


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    kind: str
    sub_fields: list[str]


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
                    ColumnSpec(name=name, kind=kind, sub_fields=sub_fields)
                )
            else:
                existing = columns[-1]
                columns[-1] = ColumnSpec(
                    name=existing.name, kind=kind, sub_fields=existing.sub_fields
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
