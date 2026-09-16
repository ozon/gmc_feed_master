from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai.tasks import CANONICAL_VARIABLES
from ..models.plugin import Plugin, PluginData

logger = logging.getLogger(__name__)

PLUGIN_NAME = "enrichment"
DEFAULT_KEY = "default"

# Which response-model fields (see app/ai/schemas.py) become suggestion fields.
TASK_FIELDS: dict[str, tuple[str, ...]] = {
    "title_optimization": ("title",),
    "description_optimization": ("description",),
    "category_classification": ("google_product_category",),
    "attribute_enrichment": (
        "color", "size", "material", "gtin", "gender", "age_group",
        "custom_label_0", "custom_label_1", "custom_label_2",
        "custom_label_3", "custom_label_4",
    ),
}

DEFAULT_TASKS: tuple[str, ...] = ("attribute_enrichment",)


@dataclass(frozen=True)
class EnrichmentOutcome:
    suggestions: dict[str, dict[str, str]]
    generated: int
    failed: int
    spent: int


async def generate_suggestions(
    *,
    ai_service: Any,
    products: Sequence[dict[str, Any]],
    tasks: Iterable[str],
    limit: int,
    budget: int,
    client_id: int | None,
    feed_source_id: int | None,
) -> EnrichmentOutcome:
    if ai_service is None:
        return EnrichmentOutcome({}, 0, 0, 0)

    task_list = tuple(tasks)
    suggestions: dict[str, dict[str, str]] = {}
    generated = failed = spent = 0

    for product in list(products)[:limit]:
        if spent >= budget:
            break
        product_id = str(product.get("id", ""))
        if not product_id:
            continue
        collected: dict[str, str] = {}
        for task_type in task_list:
            if spent >= budget:
                break
            variables = {
                name: product.get(name)
                for name in CANONICAL_VARIABLES.get(task_type, [])
            }
            try:
                result = await ai_service.run_task(
                    task_type, variables,
                    client_id=client_id, feed_source_id=feed_source_id,
                )
            except Exception:
                logger.warning(
                    "enrichment: task %s failed for product %s", task_type, product_id,
                    exc_info=True,
                )
                failed += 1
                continue
            if result.status == "fallback":
                failed += 1
                continue
            if result.status == "ok":
                spent += 1
            value = result.value
            if value is None:
                continue
            dumped = value.model_dump() if hasattr(value, "model_dump") else {}
            for field in TASK_FIELDS.get(task_type, ()):
                raw = dumped.get(field)
                if raw not in (None, ""):
                    collected[field] = str(raw)
        if collected:
            suggestions[product_id] = collected
            generated += 1

    return EnrichmentOutcome(
        suggestions=suggestions, generated=generated, failed=failed, spent=spent
    )


async def _enrichment_plugin(session: AsyncSession) -> Plugin | None:
    result = await session.execute(
        select(Plugin).where(Plugin.name == PLUGIN_NAME).order_by(Plugin.id)
    )
    return result.scalars().first()


async def load_enrichment_data(
    session_factory: Callable[[], AsyncSession], feed_source_id: int
) -> tuple[int | None, dict[str, Any]]:
    async with session_factory() as session:
        plugin = await _enrichment_plugin(session)
        if plugin is None:
            return None, {}
        row = (await session.execute(
            select(PluginData).where(
                PluginData.plugin_id == plugin.id,
                PluginData.scope == "feed_source",
                PluginData.feed_source_id == feed_source_id,
                PluginData.key == DEFAULT_KEY,
            )
        )).scalar_one_or_none()
        return plugin.id, (dict(row.data) if row is not None else {})


async def store_suggestions(
    session_factory: Callable[[], AsyncSession],
    feed_source_id: int,
    suggestions: dict[str, dict[str, str]],
) -> bool:
    async with session_factory() as session, session.begin():
        plugin = await _enrichment_plugin(session)
        if plugin is None:
            logger.warning("enrichment: plugin row missing; suggestions not stored")
            return False
        row = (await session.execute(
            select(PluginData).where(
                PluginData.plugin_id == plugin.id,
                PluginData.scope == "feed_source",
                PluginData.feed_source_id == feed_source_id,
                PluginData.key == DEFAULT_KEY,
            )
        )).scalar_one_or_none()
        existing = dict(row.data) if row is not None else {}
        merged: dict[str, dict[str, str]] = {
            str(pid): dict(fields)
            for pid, fields in (existing.get("suggestions") or {}).items()
        }
        for product_id, fields in suggestions.items():
            bucket = merged.setdefault(product_id, {})
            bucket.update(fields)
        data = {"suggestions": merged, "pinned": existing.get("pinned") or {}}
        if row is None:
            session.add(PluginData(
                plugin_id=plugin.id, scope="feed_source",
                feed_source_id=feed_source_id, key=DEFAULT_KEY, data=data,
            ))
        else:
            row.data = data
        return True
