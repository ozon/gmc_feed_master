from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RowError:
    line: int
    message: str


@dataclass(frozen=True)
class SourceField:
    name: str
    kind: str
    sub_fields: tuple[str, ...] = ()


@dataclass
class IngestReport:
    products: list[dict[str, Any]] = field(default_factory=list)
    row_errors: list[RowError] = field(default_factory=list)
    source_fields: list[SourceField] = field(default_factory=list)
