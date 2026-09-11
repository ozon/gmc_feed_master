from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AiRequest:
    task_type: str
    messages: list[dict[str, str]]
    response_format: dict[str, Any] | None = None
    max_tokens: int = 1024
    temperature: float = 0.0


@dataclass(frozen=True)
class AiResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    latency_ms: int


@runtime_checkable
class AIProvider(Protocol):
    async def complete(self, request: AiRequest) -> AiResponse: ...
