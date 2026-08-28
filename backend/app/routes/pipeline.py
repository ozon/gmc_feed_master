from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..db.engine import get_db_session
from ..models.feed_source import FeedSource
from ..models.pipeline import ModuleInstance, ModulePipeline
from ..models.plugin import Plugin
from ..schemas.pipeline import PipelineOut, PipelinePut

router = APIRouter()


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _validation_error(errors: list[str]) -> JSONResponse:
    return JSONResponse(status_code=422, content={"errors": errors})


@router.get("/feed-sources/{feed_source_id}/pipeline", response_model=PipelineOut)
async def get_pipeline(
    feed_source_id: int,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    async with session.begin():
        feed_source = await session.get(FeedSource, feed_source_id)
        if feed_source is None:
            raise HTTPException(status_code=404, detail="feed source not found")
        if feed_source.active_pipeline_id is None:
            return {"instances": []}
        rows = list((await session.execute(
            select(ModuleInstance, Plugin)
            .join(Plugin, ModuleInstance.plugin_id == Plugin.id)
            .where(ModuleInstance.pipeline_id == feed_source.active_pipeline_id)
            .order_by(ModuleInstance.position)
        )).all())
    return {"instances": [
        {"position": instance.position,
         "plugin_id": (plugin.manifest or {}).get("id") or plugin.name,
         "name": instance.name,
         "configuration": instance.configuration}
        for instance, plugin in rows
    ]}


@router.put("/feed-sources/{feed_source_id}/pipeline", response_model=PipelineOut)
async def put_pipeline(
    feed_source_id: int,
    payload: PipelinePut,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    plugin_registry = getattr(request.app.state, "plugin_registry", {})

    async with session.begin():
        feed_source = await session.get(FeedSource, feed_source_id)
        if feed_source is None:
            raise HTTPException(status_code=404, detail="feed source not found")

        plugins: dict[str, Plugin] = {}
        errors: list[str] = []
        for index, item in enumerate(payload.instances):
            plugin = (await session.execute(
                select(Plugin).where(Plugin.name == item.plugin_id)
            )).scalar_one_or_none()
            if plugin is None:
                errors.append(f"instance {index}: unknown plugin {item.plugin_id!r}")
                continue
            if not plugin.enabled:
                errors.append(f"instance {index}: plugin {item.plugin_id!r} is disabled")
                continue
            if (plugin.manifest or {}).get("extension_point") != "pipeline_module":
                errors.append(f"instance {index}: plugin {item.plugin_id!r} is not a pipeline_module")
                continue
            plugins[item.plugin_id] = plugin
            plugin_obj = plugin_registry.get(item.plugin_id)
            if plugin_obj is not None and hasattr(plugin_obj, "validate_config"):
                try:
                    plugin_obj.validate_config(item.configuration)
                except Exception as exc:
                    errors.append(f"instance {index}: invalid configuration: {exc}")
        if errors:
            return _validation_error(errors)

        pipeline = None
        if feed_source.active_pipeline_id is not None:
            pipeline = await session.get(ModulePipeline, feed_source.active_pipeline_id)
        if pipeline is None:
            pipeline = ModulePipeline(feed_source_id=feed_source_id,
                                      name=f"{feed_source.name} #{feed_source_id}",
                                      version="1", definition={})
            session.add(pipeline)
            await session.flush()
            feed_source.active_pipeline_id = pipeline.id

        await session.execute(
            delete(ModuleInstance).where(ModuleInstance.pipeline_id == pipeline.id)
        )
        instances_out = []
        definition = []
        for position, item in enumerate(payload.instances):
            plugin = plugins[item.plugin_id]
            name = item.name or (plugin.manifest or {}).get("name") or plugin.name
            session.add(ModuleInstance(
                pipeline_id=pipeline.id, plugin_id=plugin.id, position=position,
                name=name, configuration=item.configuration,
            ))
            instances_out.append({"position": position, "plugin_id": item.plugin_id,
                                  "name": name, "configuration": item.configuration})
            definition.append({"plugin_id": item.plugin_id, "name": name,
                               "configuration": item.configuration})
        pipeline.definition = {"instances": definition}

    return {"instances": instances_out}
