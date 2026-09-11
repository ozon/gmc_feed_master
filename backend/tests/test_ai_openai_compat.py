from __future__ import annotations

import json

import httpx
import pytest

from app.ai.openai_compat import OpenAICompatibleProvider
from app.ai.provider import AiRequest


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_complete_posts_chat_completions_and_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openai.com"
        assert request.headers["authorization"] == "Bearer sk-test"
        payload = json.loads(request.read())
        assert payload["model"] == "gpt-4o-mini"
        assert payload["messages"][0]["role"] == "system"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "Optimized Title"}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 7},
        })

    provider = OpenAICompatibleProvider(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o-mini",
        client=_mock_client(handler),
    )
    request = AiRequest(
        task_type="title_optimization",
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
    )
    response = await provider.complete(request)
    assert response.content == "Optimized Title"
    assert response.prompt_tokens == 42
    assert response.completion_tokens == 7
    assert response.model == "gpt-4o-mini"
    assert response.latency_ms >= 0


@pytest.mark.asyncio
async def test_complete_passes_response_format_when_set():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })

    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1",
        api_key="",
        model="llama3.3",
        client=_mock_client(handler),
    )
    request = AiRequest(
        task_type="attribute_enrichment",
        messages=[{"role": "user", "content": "u"}],
        response_format={"type": "json_object"},
    )
    response = await provider.complete(request)
    assert response.content == "{}"


@pytest.mark.asyncio
async def test_complete_rate_limit_raises_http_status_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    provider = OpenAICompatibleProvider(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o-mini",
        client=_mock_client(handler),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await provider.complete(AiRequest(
            task_type="title_optimization",
            messages=[{"role": "user", "content": "u"}],
        ))
