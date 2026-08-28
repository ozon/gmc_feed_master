from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.client import Client
from ..models.export import ExportRun, ExportVersion
from ..models.feed_source import FeedSource
from ..models.ingestion import IngestionRun
from ..models.pipeline import ModuleInstance, ModulePipeline
from ..models.plugin import PluginConfig, PluginData
from ..models.quality import QualityFinding
from ..models.staging import StagingProduct


async def delete_feed_source_cascade(session: AsyncSession, feed_source_id: int) -> None:
    await session.execute(delete(QualityFinding).where(QualityFinding.feed_source_id == feed_source_id))
    await session.execute(delete(ExportVersion).where(ExportVersion.feed_source_id == feed_source_id))
    await session.execute(delete(ExportRun).where(ExportRun.feed_source_id == feed_source_id))
    await session.execute(delete(StagingProduct).where(StagingProduct.feed_source_id == feed_source_id))
    pipeline_ids = select(ModulePipeline.id).where(ModulePipeline.feed_source_id == feed_source_id)
    await session.execute(delete(ModuleInstance).where(ModuleInstance.pipeline_id.in_(pipeline_ids)))
    await session.execute(
        update(FeedSource).where(FeedSource.id == feed_source_id)
        .values(active_pipeline_id=None)
    )
    await session.execute(delete(ModulePipeline).where(ModulePipeline.feed_source_id == feed_source_id))
    await session.execute(delete(IngestionRun).where(IngestionRun.feed_source_id == feed_source_id))
    await session.execute(delete(PluginConfig).where(PluginConfig.feed_source_id == feed_source_id))
    await session.execute(delete(PluginData).where(PluginData.feed_source_id == feed_source_id))
    await session.execute(delete(FeedSource).where(FeedSource.id == feed_source_id))


async def delete_client_cascade(session: AsyncSession, client_id: int) -> list[int]:
    feed_ids = list((await session.execute(
        select(FeedSource.id).where(FeedSource.client_id == client_id)
    )).scalars())
    for feed_source_id in feed_ids:
        await delete_feed_source_cascade(session, feed_source_id)
    await session.execute(delete(PluginConfig).where(PluginConfig.client_id == client_id))
    await session.execute(delete(PluginData).where(PluginData.client_id == client_id))
    await session.execute(delete(Client).where(Client.id == client_id))
    return feed_ids
