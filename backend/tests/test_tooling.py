from fastapi.testclient import TestClient

from app.clock import SystemClock
from app.config import Settings
from app.main import create_app


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
