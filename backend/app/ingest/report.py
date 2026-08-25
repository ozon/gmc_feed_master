from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RowError:
    line: int
    message: str


@dataclass
class IngestReport:
    products: list[dict[str, Any]] = field(default_factory=list)
    row_errors: list[RowError] = field(default_factory=list)
