from __future__ import annotations

import time

import httpx

from .provider import AiRequest, AiResponse


class OpenAICompatibleProvider:
    """Chat-completions client for OpenAI-compatible APIs.

    Covers OpenAI itself and self-hosted servers exposing the same
    protocol (vLLM, Ollama, LM Studio) via `base_url`.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: int = 30,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s
        self._client = client
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def complete(self, request: AiRequest) -> AiResponse:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
            self._owns_client = True
        payload: dict[str, object] = {
            "model": self._model,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.response_format is not None:
            payload["response_format"] = request.response_format
        if request.tools is not None:
            payload["tools"] = request.tools
            payload["tool_choice"] = request.tool_choice or "auto"
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        started = time.monotonic()
        response = await self._client.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        latency_ms = int((time.monotonic() - started) * 1000)
        choice = data["choices"][0]
        message = choice.get("message") or {}
        return AiResponse(
            content=message.get("content") or "",
            prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
            completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
            model=data.get("model", self._model),
            latency_ms=latency_ms,
            tool_calls=message.get("tool_calls"),
            finish_reason=choice.get("finish_reason", "stop"),
        )
