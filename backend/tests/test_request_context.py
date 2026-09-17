import re

from app.middleware.request_context import _resolve_request_id

_UUID_RE = re.compile(r"^[0-9a-f-]{36}$")


def test_resolve_request_id_generates_when_absent():
    assert _UUID_RE.match(_resolve_request_id(None))


def test_resolve_request_id_accepts_valid():
    assert _resolve_request_id("abc12345") == "abc12345"
    assert _resolve_request_id("req-1_2.3") == "req-1_2.3"


def test_resolve_request_id_rejects_invalid():
    assert _resolve_request_id("bad id!") != "bad id!"
    assert _resolve_request_id("short") != "short"
    assert _resolve_request_id("x" * 100) != "x" * 100


def test_middleware_echoes_and_generates(client):
    generated = client.get("/health")
    assert _UUID_RE.match(generated.headers["x-request-id"])

    echoed = client.get("/health", headers={"X-Request-ID": "abc12345"})
    assert echoed.headers["x-request-id"] == "abc12345"

    replaced = client.get("/health", headers={"X-Request-ID": "bad id!"})
    assert replaced.headers["x-request-id"] != "bad id!"
