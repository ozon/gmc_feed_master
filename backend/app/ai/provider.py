from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AiRequest:
    task_type: str
    messages: list[dict[str, Any]]
    response_format: dict[str, Any] | None = None
    max_tokens: int = 1024
    temperature: float = 0.0
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | None = None


@dataclass(frozen=True)
class AiResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    latency_ms: int
    tool_calls: list[dict[str, Any]] | None = None
    finish_reason: str = "stop"


@runtime_checkable
class AIProvider(Protocol):
    async def complete(self, request: AiRequest) -> AiResponse: ...
