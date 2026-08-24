from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import secrets
from typing import Protocol


class SessionStore(Protocol):
    def create(self, user_id: str, now: datetime) -> str:
        ...

    def validate(self, session_id: str, now: datetime, renew_idle: bool) -> str | None:
        ...

    def invalidate(self, session_id: str) -> None:
        ...


@dataclass
class _SessionRecord:
    user_id: str
    created_at: datetime
    last_interaction: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime


class InMemorySessionStore:
    def __init__(self, idle: timedelta, absolute: timedelta, secret: str):
        self._idle = idle
        self._absolute = absolute
        self._secret = secret.encode("utf-8")
        self._records: dict[str, _SessionRecord] = {}

    def create(self, user_id: str, now: datetime) -> str:
        now = _utc(now)
        nonce = secrets.token_urlsafe(32)
        absolute_expires_at = now + self._absolute
        self._records[nonce] = _SessionRecord(
            user_id=user_id,
            created_at=now,
            last_interaction=now,
            idle_expires_at=min(now + self._idle, absolute_expires_at),
            absolute_expires_at=absolute_expires_at,
        )
        return f"{nonce}.{self._signature(nonce)}"

    def validate(self, session_id: str, now: datetime, renew_idle: bool) -> str | None:
        parsed = self._parse(session_id)
        if parsed is None:
            return None
        nonce, signature = parsed
        expected = self._signature(nonce)
        if not hmac.compare_digest(signature, expected):
            return None
        record = self._records.get(nonce)
        if record is None:
            return None
        now = _utc(now)
        if now >= record.idle_expires_at or now >= record.absolute_expires_at:
            del self._records[nonce]
            return None
        if renew_idle:
            record.last_interaction = now
            record.idle_expires_at = min(now + self._idle, record.absolute_expires_at)
        return record.user_id

    def invalidate(self, session_id: str) -> None:
        parsed = self._parse(session_id)
        if parsed is not None:
            nonce, signature = parsed
            if hmac.compare_digest(signature, self._signature(nonce)):
                self._records.pop(nonce, None)

    def _signature(self, nonce: str) -> str:
        digest = hmac.new(self._secret, nonce.encode("ascii"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    @staticmethod
    def _parse(session_id: str) -> tuple[str, str] | None:
        if not isinstance(session_id, str) or session_id.count(".") != 1:
            return None
        nonce, signature = session_id.split(".")
        if not nonce or not signature or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in nonce):
            return None
        if len(signature) != 43 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in signature):
            return None
        return nonce, signature


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("session timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
