from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
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
        {"id": instance.id,
         "position": instance.position,
         "plugin_id": (plugin.manifest or {}).get("id") or plugin.name,
         "name": instance.name,
         "configuration": instance.configuration,
         "enabled": instance.enabled}
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

        existing_rows = (await session.execute(
            select(ModuleInstance).where(ModuleInstance.pipeline_id == pipeline.id)
        )).scalars().all()
        existing_by_id = {row.id: row for row in existing_rows}

        # Reject ids that do not belong to this pipeline.
        for index, item in enumerate(payload.instances):
            if item.id is not None and item.id not in existing_by_id:
                errors.append(f"instance {index}: unknown instance id {item.id}")
        if errors:
            return _validation_error(errors)

        kept_ids = {item.id for item in payload.instances if item.id is not None}
        for row in existing_rows:
            if row.id not in kept_ids:
                await session.delete(row)
        await session.flush()  # apply deletes before repositioning

        # Pass 1: move every kept row to a temporary position outside the
        # unique range so no UPDATE collides with an old position.
        temp_base = len(payload.instances) + len(existing_rows) + 1
        for temp_pos, item in enumerate(payload.instances):
            if item.id is not None:
                row = existing_by_id[item.id]
                row.position = temp_base + temp_pos
        await session.flush()

        instances_out = []
        definition = []
        for position, item in enumerate(payload.instances):
            plugin = plugins[item.plugin_id]
            name = item.name or (plugin.manifest or {}).get("name") or plugin.name
            if item.id is not None:
                row = existing_by_id[item.id]
                row.position = position
                row.name = name
                row.configuration = item.configuration
                row.enabled = item.enabled
                instance_id = row.id
            else:
                row = ModuleInstance(
                    pipeline_id=pipeline.id, plugin_id=plugin.id, position=position,
                    name=name, configuration=item.configuration, enabled=item.enabled,
                )
                session.add(row)
                await session.flush()
                instance_id = row.id
            instances_out.append({"id": instance_id, "position": position,
                                  "plugin_id": item.plugin_id, "name": name,
                                  "configuration": item.configuration,
                                  "enabled": item.enabled})
            definition.append({"plugin_id": item.plugin_id, "name": name,
                               "configuration": item.configuration,
                               "enabled": item.enabled})
        pipeline.definition = {"instances": definition}

    return {"instances": instances_out}
