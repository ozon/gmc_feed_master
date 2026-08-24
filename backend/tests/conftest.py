import os
from datetime import datetime, timezone

import pytest

from app.clock import TestClock
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
