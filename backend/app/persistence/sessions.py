import hashlib
import hmac
from datetime import datetime, timedelta
import base64
import secrets

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.session import Session
from app.models.user import User
from app.session_store import SessionStore, _utc


class PostgresSessionStore(SessionStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], idle: timedelta,
                 absolute: timedelta, secret: str):
        self._session_factory = session_factory
        self._idle = idle
        self._absolute = absolute
        self._secret = secret.encode("utf-8")

    async def create(self, user_id: str, now: datetime) -> str:
        now = _utc(now)
        nonce = secrets.token_urlsafe(32)
        token = f"{nonce}.{self._signature(nonce)}"
        absolute = now + self._absolute
        async with self._session_factory() as session:
            async with session.begin():
                user = (await session.execute(select(User).where(User.username == user_id).with_for_update())).scalar_one()
                session.add(Session(user_id=user.id, token_hash=_token_hash(token),
                                    created_at=now, last_interaction_at=now,
                                    idle_expires_at=min(now + self._idle, absolute),
                                    absolute_expires_at=absolute,
                                    revocation_generation=user.revocation_generation))
        return token

    async def validate(self, session_id: str, now: datetime, renew_idle: bool) -> str | None:
        parsed = self._parse(session_id)
        if parsed is None or not hmac.compare_digest(parsed[1], self._signature(parsed[0])):
            return None
        now = _utc(now)
        async with self._session_factory() as session:
            async with session.begin():
                row = (await session.execute(
                    select(Session, User).join(User, User.id == Session.user_id)
                    .where(Session.token_hash == _token_hash(session_id)).with_for_update()
                )).one_or_none()
                if row is None:
                    return None
                record, user = row
                if (record.revoked_at is not None or record.revocation_generation != user.revocation_generation
                        or now >= record.idle_expires_at or now >= record.absolute_expires_at):
                    await session.execute(delete(Session).where(Session.id == record.id))
                    return None
                if renew_idle:
                    record.last_interaction_at = now
                    record.idle_expires_at = min(now + self._idle, record.absolute_expires_at)
                return user.username

    async def invalidate(self, session_id: str) -> None:
        parsed = self._parse(session_id)
        if parsed is None or not hmac.compare_digest(parsed[1], self._signature(parsed[0])):
            return
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(delete(Session).where(Session.token_hash == _token_hash(session_id)))

    def _signature(self, nonce: str) -> str:
        digest = hmac.new(self._secret, nonce.encode("ascii"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    @staticmethod
    def _parse(session_id: str) -> tuple[str, str] | None:
        if not isinstance(session_id, str) or session_id.count(".") != 1:
            return None
        nonce, signature = session_id.split(".")
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        if not nonce or not signature or any(c not in allowed for c in nonce) or len(signature) != 43 or any(c not in allowed for c in signature):
            return None
        return nonce, signature


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
