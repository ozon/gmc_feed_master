from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.ai import AiResultCache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheEntry:
    output: dict[str, Any]


class AiResultCacheStore:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    async def lookup(
        self,
        task_type: str,
        provider_config_id: int,
        model: str,
        template_version: str,
        input_hash_value: str,
    ) -> CacheEntry | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(AiResultCache.output).where(
                    AiResultCache.task_type == task_type,
                    AiResultCache.provider_config_id == provider_config_id,
                    AiResultCache.model == model,
                    AiResultCache.template_version == template_version,
                    AiResultCache.input_hash == input_hash_value,
                )
            )
            output = result.scalar_one_or_none()
        if output is None:
            return None
        return CacheEntry(output=dict(output) if output else {})

    async def store(
        self,
        task_type: str,
        provider_config_id: int,
        model: str,
        template_version: str,
        input_hash_value: str,
        output: dict[str, Any],
    ) -> None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add(AiResultCache(
                        task_type=task_type,
                        provider_config_id=provider_config_id,
                        model=model,
                        template_version=template_version,
                        input_hash=input_hash_value,
                        output=output,
                    ))
        except IntegrityError:
            # Concurrent insert of the same cache key — the first writer won.
            logger.debug("ai cache: concurrent insert swallowed for %s", input_hash_value)
        except Exception:
            # Cache write failure must never fail the AI call.
            logger.exception("ai cache: write failed for %s", input_hash_value)
