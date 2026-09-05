from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PipelineInstanceIn(BaseModel):
    id: int | None = Field(default=None, ge=1)
    plugin_id: str = Field(min_length=1, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    configuration: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class PipelinePut(BaseModel):
    instances: list[PipelineInstanceIn] = Field(default_factory=list)


class InstancePatch(BaseModel):
    enabled: bool


class PipelineInstanceOut(BaseModel):
    id: int
    position: int
    plugin_id: str
    name: str
    configuration: dict[str, Any]
    enabled: bool


class PipelineOut(BaseModel):
    instances: list[PipelineInstanceOut]
