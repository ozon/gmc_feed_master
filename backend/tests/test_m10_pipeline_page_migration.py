"""module_instances.enabled column migration test (pipeline page master-detail)."""

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_module_instances_enabled_column(isolated_database_url):
    # Migrations run per test-database by conftest's alembic load; verify shape.
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(isolated_database_url)
    async with engine.connect() as conn:
        col = (await conn.execute(text(
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = 'module_instances' AND column_name = 'enabled'"
        ))).first()
    await engine.dispose()
    assert col is not None, "module_instances.enabled column must exist"
    assert col[0] == "NO"
    assert col[1] == "true"
