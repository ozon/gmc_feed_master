from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PipelineInstanceIn(BaseModel):
    plugin_id: str = Field(min_length=1, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    configuration: dict[str, Any] = Field(default_factory=dict)


class PipelinePut(BaseModel):
    instances: list[PipelineInstanceIn] = Field(default_factory=list)


class PipelineInstanceOut(BaseModel):
    position: int
    plugin_id: str
    name: str
    configuration: dict[str, Any]


class PipelineOut(BaseModel):
    instances: list[PipelineInstanceOut]
