from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EventLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    category: str
    level: str
    source: str
    logger: str | None
    actor: str | None
    actor_role: str | None
    client_id: int | None
    feed_source_id: int | None
    request_id: str | None
    run_id: int | None
    message: str
    context: dict[str, Any]


class EventLogPage(BaseModel):
    items: list[EventLogOut]
    next_cursor: int | None


class ClientLogEntry(BaseModel):
    level: Literal["warning", "error", "critical"] = "error"
    message: str = Field(min_length=1, max_length=2000)
    stack: str | None = Field(default=None, max_length=8000)
    route: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=500)
    request_id: str | None = Field(default=None, max_length=64)
    context: dict[str, Any] = Field(default_factory=dict)


class ClientLogBatch(BaseModel):
    entries: list[ClientLogEntry] = Field(min_length=1, max_length=20)
