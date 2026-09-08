from contextlib import asynccontextmanager

from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_client import UserClient
from app.security.passwords import hash_password, verify_password


@asynccontextmanager
async def _repository_transaction(session: AsyncSession):
    """Use a savepoint when the caller already owns the surrounding transaction."""
    if session.in_transaction():
        async with session.begin_nested():
            yield
    else:
        async with session.begin():
            yield


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def seed_initial_user(
    session: AsyncSession, username: str, password: str
) -> User:
    async with _repository_transaction(session):
        await session.execute(text("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
        existing = await session.execute(select(User).limit(1))
        existing_user = existing.scalar_one_or_none()
        if existing_user is not None:
            return existing_user
        await session.execute(
            insert(User)
            .values(username=username, password_hash=hash_password(password),
                    role="admin", is_active=True)
        )
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one()


async def authenticate_user(
    session: AsyncSession, username: str, password: str
) -> User | None:
    user = await get_user_by_username(session, username)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def verify_user_password(
    session: AsyncSession, username: str, password: str
) -> bool:
    user = await get_user_by_username(session, username)
    return user is not None and verify_password(password, user.password_hash)


async def change_password(
    session: AsyncSession,
    username: str,
    current_password: str,
    new_password: str,
) -> bool:
    async with _repository_transaction(session):
        result = await session.execute(
            select(User).where(User.username == username).with_for_update()
        )
        user = result.scalar_one_or_none()
        if user is None or not verify_password(current_password, user.password_hash):
            return False

        user.password_hash = hash_password(new_password)
        user.revocation_generation += 1
        return True


async def list_users(session: AsyncSession) -> list[tuple[User, list[int]]]:
    users = list((await session.execute(select(User).order_by(User.id))).scalars())
    assignments = list((await session.execute(select(UserClient))).all())
    by_user: dict[int, list[int]] = {}
    for user_id, client_id in assignments:
        by_user.setdefault(user_id, []).append(client_id)
    return [(user, sorted(by_user.get(user.id, []))) for user in users]


async def create_user(
    session: AsyncSession,
    username: str,
    password: str,
    role: str,
    client_ids: list[int],
    is_active: bool = True,
) -> User:
    async with _repository_transaction(session):
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        session.add(user)
        await session.flush()
        for client_id in client_ids:
            session.add(UserClient(user_id=user.id, client_id=client_id))
        await session.flush()
        return user


async def update_user(
    session: AsyncSession,
    user_id: int,
    role: str | None = None,
    is_active: bool | None = None,
    client_ids: list[int] | None = None,
) -> User | None:
    async with _repository_transaction(session):
        user = await session.get(User, user_id)
        if user is None:
            return None
        if role is not None:
            user.role = role
        if is_active is not None:
            user.is_active = is_active
        if client_ids is not None:
            await session.execute(
                delete(UserClient).where(UserClient.user_id == user_id)
            )
            for client_id in client_ids:
                session.add(UserClient(user_id=user_id, client_id=client_id))
        await session.flush()
        return user


async def set_user_password(
    session: AsyncSession, user_id: int, new_password: str
) -> bool:
    async with _repository_transaction(session):
        user = await session.get(User, user_id)
        if user is None:
            return False
        user.password_hash = hash_password(new_password)
        user.revocation_generation += 1
        return True
