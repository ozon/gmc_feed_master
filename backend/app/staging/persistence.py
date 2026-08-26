from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.staging import StagingHistory, StagingProduct
from .delta import StagingDelta, StoredRow


async def load_stored_rows(
    session_factory: Callable[[], AsyncSession],
    feed_source_id: int,
) -> dict[str, StoredRow]:
    async with session_factory() as session:
        result = await session.execute(
            select(StagingProduct).where(
                StagingProduct.feed_source_id == feed_source_id
            )
        )
        return {
            row.product_id: StoredRow(
                pk=row.id,
                product_id=row.product_id,
                content_hash=row.content_hash,
                config_hash=row.config_hash,
                status=row.status,
                snapshot=row.raw_data or {},
            )
            for row in result.scalars()
        }


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def apply_staging_delta(
    session_factory: Callable[[], AsyncSession],
    feed_source_id: int,
    ingestion_run_id: int,
    delta: StagingDelta,
    config_hash: str,
    *,
    chunk_size: int = 1000,
) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    pk_map: dict[str, int] = {}

    inserts = [u for u in delta.upserts if u.insert]
    updates = [u for u in delta.upserts if not u.insert]

    for group in _chunks(inserts, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                rows = [
                    StagingProduct(
                        feed_source_id=feed_source_id,
                        ingestion_run_id=ingestion_run_id,
                        product_id=u.product_id,
                        content_hash=u.content_hash,
                        config_hash=config_hash,
                        status="active",
                        last_seen_at=now,
                        removed_at=None,
                        raw_data=u.product,
                    )
                    for u in group
                ]
                session.add_all(rows)
                await session.flush()
                for u, row in zip(group, rows):
                    pk_map[u.product_id] = row.id

    for group in _chunks(updates, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                for u in group:
                    await session.execute(
                        update(StagingProduct)
                        .where(
                            StagingProduct.feed_source_id == feed_source_id,
                            StagingProduct.product_id == u.product_id,
                        )
                        .values(
                            raw_data=u.product,
                            content_hash=u.content_hash,
                            config_hash=config_hash,
                            status="active",
                            removed_at=None,
                            ingestion_run_id=ingestion_run_id,
                            last_seen_at=now,
                        )
                    )
                    pk_map[u.product_id] = (
                        await session.execute(
                            select(StagingProduct.id).where(
                                StagingProduct.feed_source_id == feed_source_id,
                                StagingProduct.product_id == u.product_id,
                            )
                        )
                    ).scalar_one()

    for group in _chunks(delta.reactivations, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                for pk in group:
                    await session.execute(
                        update(StagingProduct)
                        .where(StagingProduct.id == pk)
                        .values(
                            status="active",
                            removed_at=None,
                            ingestion_run_id=ingestion_run_id,
                            last_seen_at=now,
                        )
                    )

    for group in _chunks(delta.removals, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                for pk in group:
                    await session.execute(
                        update(StagingProduct)
                        .where(StagingProduct.id == pk)
                        .values(
                            status="removed",
                            removed_at=now,
                            ingestion_run_id=ingestion_run_id,
                        )
                    )

    for group in _chunks(delta.touches, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(StagingProduct)
                    .where(StagingProduct.id.in_(group))
                    .values(last_seen_at=now)
                )

    history_rows = [
        (pk_map[u.product_id], u.product) for u in delta.upserts if u.write_history
    ]
    for group in _chunks(history_rows, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                session.add_all([
                    StagingHistory(staging_product_id=pk, snapshot=snapshot)
                    for pk, snapshot in group
                ])

    return pk_map
