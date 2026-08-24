from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

from .clock import Clock, SystemClock
from .config import Settings, get_settings

if TYPE_CHECKING:
    from .session_store import SessionStore


def create_app(
    settings: Settings | None = None,
    session_store: SessionStore | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings if settings is not None else get_settings()
    app.state.session_store = session_store
    app.state.clock = clock if clock is not None else SystemClock()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
