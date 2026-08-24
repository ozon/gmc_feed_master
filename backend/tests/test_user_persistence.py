import os

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.user import User
from app.persistence.users import (
    change_password,
    get_user_by_username,
    seed_initial_user,
    verify_user_password,
)


@pytest_asyncio.fixture
async def user_session(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(delete(User))
        await session.commit()
        yield session
        await session.execute(delete(User))
        await session.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_first_user_seeding_is_idempotent_and_does_not_overwrite_environment_credentials(
    user_session,
):
    first = await seed_initial_user(user_session, "operator", "first-password")
    second = await seed_initial_user(user_session, "operator", "environment-password")

    assert first.id == second.id
    assert await verify_user_password(user_session, "operator", "first-password")
    assert not await verify_user_password(user_session, "operator", "environment-password")


@pytest.mark.asyncio
async def test_seeding_does_not_add_environment_user_when_any_user_exists(user_session):
    first = await seed_initial_user(user_session, "existing", "existing-password")
    seeded = await seed_initial_user(user_session, "operator", "environment-password")

    assert seeded.id == first.id
    assert await get_user_by_username(user_session, "operator") is None
    assert await verify_user_password(user_session, "existing", "existing-password")


@pytest.mark.asyncio
async def test_password_change_requires_current_password_and_increments_generation(
    user_session,
):
    await seed_initial_user(user_session, "operator", "current-password")

    assert await verify_user_password(user_session, "operator", "current-password")
    assert await change_password(user_session, "operator", "current-password", "new-password")
    changed = await get_user_by_username(user_session, "operator")
    assert changed.revocation_generation == 1
    assert not await verify_user_password(user_session, "operator", "current-password")
    assert await verify_user_password(user_session, "operator", "new-password")


@pytest.mark.asyncio
async def test_password_change_rejects_wrong_password_without_mutation(user_session):
    await seed_initial_user(user_session, "operator", "current-password")

    assert not await change_password(user_session, "operator", "wrong", "new-password")
    unchanged = await get_user_by_username(user_session, "operator")
    assert unchanged.revocation_generation == 0


@pytest.mark.asyncio
async def test_missing_user_lookup_and_verification_are_safe(user_session):
    assert await get_user_by_username(user_session, "missing") is None
    assert not await verify_user_password(user_session, "missing", "password")
