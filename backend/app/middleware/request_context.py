from __future__ import annotations

import logging
import re
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger(__name__)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def _resolve_request_id(raw: str | None) -> str:
    if raw is not None and _REQUEST_ID_RE.match(raw):
        return raw
    return str(uuid.uuid4())


async def _persist_server_error(scope: Scope, exc: Exception, request_id: str) -> None:
    app = scope.get("app")
    factory = getattr(getattr(app, "state", None), "db_session_factory", None)
    if factory is None:
        return
    try:
        from ..event_log import record_server_error

        async with factory() as session, session.begin():
            await record_server_error(
                session,
                message=str(exc)[:4000],
                request_id=request_id,
                logger="app.middleware",
            )
    except Exception:
        logging.getLogger("app.middleware").warning(
            "failed to persist server error event", exc_info=True
        )


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = _resolve_request_id(headers.get("x-request-id"))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=scope["method"],
            path=scope["path"],
        )

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            logger.exception("unhandled error")
            await _persist_server_error(scope, exc, request_id)
            raise
        finally:
            structlog.contextvars.clear_contextvars()
