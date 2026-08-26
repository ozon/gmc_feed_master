### Task 5: Migration — `removed_at`, cascade FK, purge index

**Files:**
- Modify: `backend/app/models/staging.py`
- Create: `backend/alembic/versions/20260826_0001_m5_staging_delta.py`
- Test: `backend/tests/test_m5_migration.py`

**Interfaces:**
- Consumes: current head revision `20260825_0001`. The baseline created the FK unnamed, so PostgreSQL named it `staging_history_staging_product_id_fkey` (default `table_column_fkey` pattern).
- Produces: `StagingProduct.removed_at: Mapped[datetime | None]`; `staging_history.staging_product_id` with `ON DELETE CASCADE`; partial index `ix_staging_products_removed_purge ON staging_products (removed_at) WHERE status = 'removed'`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_m5_migration.py`:

```python
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio


def _alembic_config(url):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


async def _inspect_schema(url):
    engine = create_async_engine(url)

    def _run(connection):
        inspector = inspect(connection)
        return (
            {c["name"] for c in inspector.get_columns("staging_products")},
            {i["name"]: i for i in inspector.get_indexes("staging_products")},
            inspector.get_foreign_keys("staging_history"),
        )

    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_run)
    finally:
        await engine.dispose()


async def test_upgrade_adds_removed_at_cascade_and_index(isolated_database_url):
    columns, indexes, fks = await _inspect_schema(isolated_database_url)

    assert "removed_at" in columns
    assert "ix_staging_products_removed_purge" in indexes
    history_fk = [fk for fk in fks if fk["constrained_columns"] == ["staging_product_id"]]
    assert history_fk and history_fk[0].get("ondelete") == "CASCADE"


async def test_downgrade_reverses_all_three(isolated_database_url):
    command.downgrade(_alembic_config(isolated_database_url), "20260825_0001")

    columns, indexes, fks = await _inspect_schema(isolated_database_url)
    assert "removed_at" not in columns
    assert "ix_staging_products_removed_purge" not in indexes
    history_fk = [fk for fk in fks if fk["constrained_columns"] == ["staging_product_id"]]
    assert history_fk and history_fk[0].get("ondelete") == "RESTRICT"

    command.upgrade(_alembic_config(isolated_database_url), "head")


async def test_removal_deletes_history_via_cascade(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            client = (await session.execute(
                text("INSERT INTO clients (name) VALUES ('C') RETURNING id")
            )).scalar_one()
            fs = (await session.execute(
                text(
                    "INSERT INTO feed_sources (client_id, name, source_format) "
                    "VALUES (:cid, 'F', 'tsv') RETURNING id"
                ),
                {"cid": client},
            )).scalar_one()
            run = (await session.execute(
                text(
                    "INSERT INTO ingestion_runs (feed_source_id, status) "
                    "VALUES (:fid, 'running') RETURNING id"
                ),
                {"fid": fs},
            )).scalar_one()
            await session.execute(
                text(
                    "INSERT INTO staging_products "
                    "(feed_source_id, ingestion_run_id, product_id, content_hash, "
                    "config_hash, status, raw_data) "
                    "VALUES (:fid, :rid, 'p1', 'h', 'c', 'active', '{}')"
                ),
                {"fid": fs, "rid": run},
            )
            await session.execute(text(
                "INSERT INTO staging_history (staging_product_id, snapshot) "
                "SELECT id, '{}' FROM staging_products"
            ))

    async with factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM staging_products"))

    async with factory() as session:
        remaining = (await session.execute(
            text("SELECT count(*) FROM staging_history")
        )).scalar_one()
    assert remaining == 0
    await engine.dispose()
```

Note: if the `feed_sources` INSERT fails on additional NOT NULL columns, check `app/models/feed_source.py` and extend the column list accordingly.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_m5_migration.py -v`
Expected: FAIL — `removed_at` column missing on the upgraded database

- [ ] **Step 3: Update the models**

In `backend/app/models/staging.py` make exactly three changes:
1. Add after the `last_seen_at` line of `StagingProduct`:

```python
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

2. In `StagingHistory`, change the FK line from `ondelete="RESTRICT"` to:

```python
    staging_product_id: Mapped[int] = mapped_column(ForeignKey("staging_products.id", ondelete="CASCADE"), nullable=False)
```

3. Nothing else changes in the file.

- [ ] **Step 4: Write the migration**

Create `backend/alembic/versions/20260826_0001_m5_staging_delta.py`:

```python
"""M5 staging delta support

Revision ID: 20260826_0001
Revises: 20260825_0001
Create Date: 2026-08-26 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '20260826_0001'
down_revision: Union[str, Sequence[str], None] = '20260825_0001'
branch_labels: Union[str, Sequence[str], None] = None

_PURGE_INDEX = 'ix_staging_products_removed_purge'
_HISTORY_FK = 'staging_history_staging_product_id_fkey'


def upgrade() -> None:
    op.add_column(
        'staging_products',
        sa.Column('removed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        _PURGE_INDEX,
        'staging_products',
        ['removed_at'],
        unique=False,
        postgresql_where=sa.text("status = 'removed'"),
    )
    op.drop_constraint(_HISTORY_FK, 'staging_history', type_='foreignkey')
    op.create_foreign_key(
        _HISTORY_FK,
        'staging_history',
        'staging_products',
        ['staging_product_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint(_HISTORY_FK, 'staging_history', type_='foreignkey')
    op.create_foreign_key(
        _HISTORY_FK,
        'staging_history',
        'staging_products',
        ['staging_product_id'],
        ['id'],
        ondelete='RESTRICT',
    )
    op.drop_index(_PURGE_INDEX, table_name='staging_products')
    op.drop_column('staging_products', 'removed_at')
```

If `drop_constraint` reports the name does not exist, query the real name against the test database (`SELECT conname FROM pg_constraint WHERE conrelid = 'staging_history'::regclass AND contype = 'fkey';`) and use it verbatim in `_HISTORY_FK`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_m5_migration.py tests/test_migrations.py tests/test_models.py -v`
Expected: PASS — new tests green; existing migration/model suites unaffected

- [ ] **Step 6: Commit**

```bash
git add app/models/staging.py alembic/versions/20260826_0001_m5_staging_delta.py tests/test_m5_migration.py
git commit -m "feat: staging removed_at column, history cascade, purge index"
```

---

