from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AiResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    latency_ms: int
    tool_calls: list[dict[str, Any]] | None = None
    finish_reason: str = "stop"
