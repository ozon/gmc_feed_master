from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MappingEntryIn(BaseModel):
    target: str = Field(min_length=1)


class FieldMappingPut(BaseModel):
    mappings: dict[str, MappingEntryIn]
    custom_fields: list[str] = Field(default_factory=list)


class SourceFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    kind: str
    sub_fields: list[str]
    max_repeats: int = 0


class MappingEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target: str
    origin: str


class FieldMappingOut(BaseModel):
    version: int
    auto_mapped: bool
    source_fields: list[SourceFieldOut]
    mappings: dict[str, MappingEntryOut]
    custom_fields: list[str] = Field(default_factory=list)


class RegistrySubFieldOut(BaseModel):
    name: str
    type: str
    required: str
    kind: str | None = None


class RegistryAttributeOut(BaseModel):
    name: str
    kind: str
    required: str
    baseline_required: bool
    sub_fields: list[RegistrySubFieldOut]
    enum_values: list[str]
    max_repeats: int = 0
