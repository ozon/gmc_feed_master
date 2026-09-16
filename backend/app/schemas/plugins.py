from __future__ import annotations

from pydantic import BaseModel


class EnabledPut(BaseModel):
    enabled: bool
