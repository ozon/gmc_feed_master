from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.service import AiChatUnavailable
from app.config import Settings
from app.main import create_app
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user


class FakeChatResponse:
    def __init__(self, content: str, tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls


class FakeAiService:
    """Scripted complete_chat recording every call's messages."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[list[dict]] = []

    async def complete_chat(self, messages, tools=None, *, client_id=None, feed_source_id=None):
        self.calls.append([dict(m) for m in messages])
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest_asyncio.fixture
async def app_with_fake_ai(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "admin-pass")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="admin-pass",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)

    def install(script):
        fake = FakeAiService(script)
        app.state.ai_service = fake
        return fake

    yield app, install
    await engine.dispose()


@pytest_asyncio.fixture
async def chat_http(app_with_fake_ai):
    app, _ = app_with_fake_ai
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.post(
        "/auth/login", json={"username": "operator", "password": "admin-pass"}
    )).status_code == 200
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_direct_answer(app_with_fake_ai, chat_http):
    _app, install = app_with_fake_ai
    fake = install([FakeChatResponse("Hello there")])
    response = await chat_http.post("/chat", json={
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert response.status_code == 200
    assert response.json() == {"content": "Hello there"}
    assert fake.calls[0][0]["role"] == "system"


@pytest.mark.asyncio
async def test_one_tool_round(app_with_fake_ai, chat_http):
    _app, install = app_with_fake_ai
    fake = install([
        FakeChatResponse("", tool_calls=[{
            "id": "call-1", "type": "function",
            "function": {"name": "list_feed_sources", "arguments": "{}"},
        }]),
        FakeChatResponse("You have feed sources."),
    ])
    response = await chat_http.post("/chat", json={
        "messages": [{"role": "user", "content": "what feed sources do I have?"}],
    })
    assert response.status_code == 200
    assert response.json() == {"content": "You have feed sources."}
    second_call = fake.calls[1]
    tool_messages = [m for m in second_call if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call-1"
    assert "feed_sources" in tool_messages[0]["content"]


@pytest.mark.asyncio
async def test_tool_loop_exhausted(app_with_fake_ai, chat_http):
    _app, install = app_with_fake_ai

    def tool_round():
        return FakeChatResponse("", tool_calls=[{
            "id": "c", "type": "function",
            "function": {"name": "list_feed_sources", "arguments": "{}"},
        }])

    install([tool_round() for _ in range(6)])
    response = await chat_http.post("/chat", json={
        "messages": [{"role": "user", "content": "loop forever"}],
    })
    assert response.status_code == 502
    assert response.json()["detail"] == "tool_loop_exhausted"


@pytest.mark.asyncio
async def test_ai_unavailable_503(app_with_fake_ai, chat_http):
    _app, install = app_with_fake_ai
    install([AiChatUnavailable("no_provider")])
    response = await chat_http.post("/chat", json={
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert response.status_code == 503
    assert "no_provider" in response.json()["detail"]


@pytest.mark.asyncio
async def test_payload_validation(chat_http):
    last_assistant = await chat_http.post("/chat", json={
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    })
    assert last_assistant.status_code == 422

    empty = await chat_http.post("/chat", json={"messages": []})
    assert empty.status_code == 422


@pytest.mark.asyncio
async def test_unknown_tool_continues(app_with_fake_ai, chat_http):
    _app, install = app_with_fake_ai
    fake = install([
        FakeChatResponse("", tool_calls=[{
            "id": "call-x", "type": "function",
            "function": {"name": "bogus_tool", "arguments": "{}"},
        }]),
        FakeChatResponse("I could not run that tool."),
    ])
    response = await chat_http.post("/chat", json={
        "messages": [{"role": "user", "content": "run a bogus tool"}],
    })
    assert response.status_code == 200
    assert response.json() == {"content": "I could not run that tool."}
    tool_messages = [m for m in fake.calls[1] if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert "unknown tool" in tool_messages[0]["content"]
