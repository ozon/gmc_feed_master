from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current timezone-aware UTC time."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class TestClock:
    def __init__(self, current: datetime):
        self._current = _utc(current)

    def now(self) -> datetime:
        return self._current

    def set(self, current: datetime) -> None:
        self._current = _utc(current)

    def advance(self, **kwargs: float) -> None:
        self._current += timedelta(**kwargs)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
