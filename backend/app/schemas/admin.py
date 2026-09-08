from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    is_active: bool
    client_ids: list[int]


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    role: Literal["admin", "user"] = "user"
    client_ids: list[int] = Field(default_factory=list)
    is_active: bool = True


class AdminUserUpdate(BaseModel):
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None
    client_ids: list[int] | None = None


class PasswordSet(BaseModel):
    new_password: str = Field(min_length=1)


class GlobalSettingsOut(BaseModel):
    staging_removal_retention_days: int = Field(ge=1)
    staging_history_retention_days: int = Field(ge=1)
    ingestion_run_retention_days: int = Field(ge=1)


class GlobalSettingsUpdate(GlobalSettingsOut):
    pass
