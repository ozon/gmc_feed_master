import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.global_setting import GlobalSetting
from app.persistence.users import seed_initial_user


@pytest.mark.asyncio
async def test_seed_initial_user_is_admin(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = await seed_initial_user(session, "operator", "correct")
        assert user.role == "admin"
        assert user.is_active is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_promotes_existing_users_to_admin(isolated_database_url):
    # Downgrade to the revision before m11, insert a pre-RBAC user, upgrade, verify.
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", isolated_database_url)
    await asyncio.to_thread(command.downgrade, config, "20260905_0001")
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await session.execute(text(
            "INSERT INTO users (username, password_hash, revocation_generation)"
            " VALUES ('legacy', 'x', 0)"
        ))
    await engine.dispose()
    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = (await session.execute(
            text("SELECT username, role FROM users WHERE username = 'legacy'")
        )).one()
        assert user.role == "admin"
        settings = await session.get(GlobalSetting, 1)
        assert settings is None  # row is seeded lazily, not by migration
    await engine.dispose()
