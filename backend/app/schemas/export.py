from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ExportFindingCounts(BaseModel):
    critical: int
    warning: int
    info: int


class ExportVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_number: int
    product_count: int
    file_hash: str
    source: str
    source_version_id: int | None
    created_at: datetime
    findings: ExportFindingCounts | None = None
    url: str | None = None


class DiffFieldOut(BaseModel):
    field: str
    old: Any = None
    new: Any = None


class DiffProductOut(BaseModel):
    product_id: str
    fields: list[DiffFieldOut]


class DiffOut(BaseModel):
    version: int
    against: int
    added: list[str]
    removed: list[str]
    changed: list[DiffProductOut]
