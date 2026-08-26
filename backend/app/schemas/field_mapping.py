from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MappingEntryIn(BaseModel):
    target: str = Field(min_length=1)


class FieldMappingPut(BaseModel):
    mappings: dict[str, MappingEntryIn]


class SourceFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    kind: str
    sub_fields: list[str]


class MappingEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target: str
    origin: str


class FieldMappingOut(BaseModel):
    version: int
    auto_mapped: bool
    source_fields: list[SourceFieldOut]
    mappings: dict[str, MappingEntryOut]
