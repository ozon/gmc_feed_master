import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.clock import TestClock
from app.config import Settings
from app.main import create_app
from app.session_store import InMemorySessionStore


os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("INITIAL_USERNAME", "test-user")
os.environ.setdefault("INITIAL_PASSWORD", "test-password")


@pytest.fixture
def clock():
    return TestClock(datetime(2026, 1, 1, tzinfo=timezone.utc))


@pytest.fixture
def store():
    from datetime import timedelta

    return InMemorySessionStore(
        idle=timedelta(minutes=30), absolute=timedelta(hours=12), secret="test-secret"
    )


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="correct",
    )


@pytest.fixture
def client(settings, store, clock):
    return TestClient(
        create_app(settings=settings, session_store=store, clock=clock),
        base_url="https://testserver",
    )
