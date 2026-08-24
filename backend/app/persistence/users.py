from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.security.passwords import hash_password, verify_password


async def _begin_repository_transaction(session: AsyncSession):
    """Close SQLAlchemy's autobegun read transaction before repository work."""
    if session.in_transaction():
        await session.rollback()
    return session.begin()


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def seed_initial_user(
    session: AsyncSession, username: str, password: str
) -> User:
    async with await _begin_repository_transaction(session):
        await session.execute(text("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
        existing = await session.execute(select(User).limit(1))
        existing_user = existing.scalar_one_or_none()
        if existing_user is not None:
            return existing_user
        await session.execute(
            insert(User)
            .values(username=username, password_hash=hash_password(password))
        )
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one()


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
    async with await _begin_repository_transaction(session):
        result = await session.execute(
            select(User).where(User.username == username).with_for_update()
        )
        user = result.scalar_one_or_none()
        if user is None or not verify_password(current_password, user.password_hash):
            return False

        user.password_hash = hash_password(new_password)
        user.revocation_generation += 1
        return True
