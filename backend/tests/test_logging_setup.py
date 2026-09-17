import io
import json
import logging

import structlog

from app.config import Settings
from app.logging_setup import redact_sensitive


def _test_settings() -> Settings:
    return Settings(
        _env_file=None,
        session_secret="s",
        initial_username="u",
        initial_password="p",
        log_format="json",
        log_level="INFO",
    )


def test_redact_sensitive_keys_and_nesting():
    event = {
        "event": "login",
        "password": "hunter2",
        "nested": {"access_token": "abc", "keep": "value"},
        "items": [{"api_key": "k"}],
    }
    out = redact_sensitive(None, "info", event)
    assert out["password"] == "[REDACTED]"
    assert out["nested"]["access_token"] == "[REDACTED]"
    assert out["nested"]["keep"] == "value"
    assert out["items"][0]["api_key"] == "[REDACTED]"


def test_redact_sensitive_truncates_long_strings():
    long_value = "x" * 5000
    out = redact_sensitive(None, "info", {"event": "e", "body": long_value})
    assert out["body"].startswith("x" * 2048)
    assert out["body"].endswith("…[truncated]")
    assert len(out["body"]) < 5000


def test_stdlib_records_render_json_with_contextvars(monkeypatch):
    from app import logging_setup

    monkeypatch.setattr(logging_setup, "_configured", False)
    stream = io.StringIO()
    monkeypatch.setattr(logging_setup.sys, "stdout", stream)
    logging_setup.configure_logging(_test_settings())

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="req-123")
    logging.getLogger("app.demo").info("hello %s", "world")

    payload = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert payload["event"] == "hello world"
    assert payload["request_id"] == "req-123"
    assert payload["logger"] == "app.demo"
    assert payload["level"] == "info"
    structlog.contextvars.clear_contextvars()
