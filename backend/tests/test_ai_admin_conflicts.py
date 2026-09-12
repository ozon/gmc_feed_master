from sqlalchemy.exc import OperationalError

from app.routes.ai_admin import _is_deadlock


def test_is_deadlock_detects_asyncpg_message():
    exc = OperationalError("stmt", {}, Exception("deadlock detected"))
    assert _is_deadlock(exc) is True


def test_is_deadlock_ignores_other_operational_errors():
    exc = OperationalError("stmt", {}, Exception("connection refused"))
    assert _is_deadlock(exc) is False
