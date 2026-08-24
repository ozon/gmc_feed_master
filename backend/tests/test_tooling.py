import os
import subprocess
import sys
from typing import Any, cast

from starlette.requests import Request
from fastapi.testclient import TestClient

from app.auth import _store
from app.clock import SystemClock
from app.config import Settings, get_settings
from app.main import create_app
from app.persistence.sessions import PostgresSessionStore


def test_python_test_runner_is_configured():
    assert True


def test_health_endpoint():
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_factory_installs_injected_dependencies():
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="test-user",
        initial_password="test-password",
    )
    store = object()
    clock = SystemClock()
    application = create_app(settings=settings, session_store=store, clock=clock)
    assert application.state.settings is settings
    assert application.state.session_store is store
    assert application.state.clock is clock


def test_factory_selects_postgres_store_when_settings_are_omitted():
    factory = object()
    application = create_app(db_session_factory=cast(Any, factory))
    request = Request({"type": "http", "app": application})
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="test-user",
        initial_password="test-password",
    )

    store = _store(request, settings)

    assert isinstance(store, PostgresSessionStore)
    assert store._session_factory is factory
    assert application.state.session_store is store


def test_factory_settings_are_used_by_health_without_credentials_environment(monkeypatch):
    for key in ("SESSION_SECRET", "INITIAL_USERNAME", "INITIAL_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(
        _env_file=None,
        session_secret="factory-secret",
        initial_username="factory-user",
        initial_password="factory-password",
    )

    response = TestClient(create_app(settings=settings)).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_asgi_import_is_safe_without_settings_environment():
    environment = os.environ.copy()
    for key in ("SESSION_SECRET", "INITIAL_USERNAME", "INITIAL_PASSWORD"):
        environment.pop(key, None)
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=".",
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_settings_dependency_override_changes_route_state():
    original = Settings(
        _env_file=None,
        session_secret="original-secret",
        initial_username="original-user",
        initial_password="original-password",
    )
    overridden = Settings(
        _env_file=None,
        session_secret="overridden-secret",
        initial_username="overridden-user",
        initial_password="overridden-password",
    )
    application = create_app(settings=original)
    calls = []

    def override_settings():
        calls.append(overridden)
        return overridden

    application.dependency_overrides[get_settings] = override_settings

    response = TestClient(application).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert calls == [overridden]
    assert application.state.settings is overridden


def test_create_app_is_public_entry_point_for_health_and_auth_flow():
    settings = Settings(
        _env_file=None,
        session_secret="integration-secret",
        initial_username="operator",
        initial_password="correct",
    )
    from app.session_store import InMemorySessionStore
    from datetime import timedelta

    client = TestClient(
        create_app(
            settings=settings,
            session_store=InMemorySessionStore(
                idle=timedelta(minutes=30),
                absolute=timedelta(hours=12),
                secret="integration-secret",
            ),
        ),
        base_url="https://testserver",
    )

    assert client.get("/health").json() == {"status": "ok"}
    login = client.post(
        "/auth/login", json={"username": "operator", "password": "correct"}
    )
    assert login.status_code == 200
    assert client.get("/auth/me").json() == {"username": "operator"}
