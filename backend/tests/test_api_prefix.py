from fastapi.testclient import TestClient

from app.main import create_app


def test_api_only_under_prefix(settings, store, clock):
    root = TestClient(
        create_app(settings=settings, session_store=store, clock=clock),
        base_url="https://testserver",
    )
    assert root.get("/clients").status_code == 404
    assert root.get("/health").status_code == 200

    prefixed = TestClient(
        create_app(settings=settings, session_store=store, clock=clock),
        base_url="https://testserver/api",
    )
    assert prefixed.get("/clients").status_code == 401
