from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from .config import Settings

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "token",
        "secret",
        "cookie",
        "authorization",
        "api_key",
        "apikey",
        "session",
        "credential",
        "private_key",
        "access_key",
        "refresh_token",
    }
)
_REDACTED = "[REDACTED]"
MAX_VALUE_LEN = 2048
_MAX_DEPTH = 3

_configured = False


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_KEYS)


def _truncate(value: str) -> str:
    if len(value) <= MAX_VALUE_LEN:
        return value
    return value[:MAX_VALUE_LEN] + "…[truncated]"


def _redact(value: Any, depth: int) -> Any:
    if depth >= _MAX_DEPTH:
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive(str(key)):
                out[key] = _REDACTED
            else:
                out[key] = _redact(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(item, depth + 1) for item in value]
    if isinstance(value, str):
        return _truncate(value)
    return value


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Return a redacted/truncated copy of ``data``; never mutates the input."""
    # ponytail: depth-3 recursion cap, raise if nested payloads appear.
    return _redact(data, 0)


def redact_sensitive(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> dict[str, Any]:
    return redact_mapping(dict(event_dict))


def configure_logging(settings: Settings | None) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    level = (getattr(settings, "log_level", None) or "INFO").upper()
    log_format = (getattr(settings, "log_format", None) or "json").lower()
    renderer: Any = (
        structlog.dev.ConsoleRenderer()
        if log_format == "console"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_sensitive,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_sensitive,
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
