from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import litellm
from litellm.caching.caching import Cache, CacheMode
from litellm.types.caching import LiteLLMCacheType
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..models.global_setting import GlobalSetting

logger = logging.getLogger(__name__)

TAXONOMY_TASKS = frozenset({"category_classification"})


@dataclass(frozen=True)
class CacheSettings:
    cache_type: str
    namespace: str
    ttl_taxonomy_s: int
    ttl_content_s: int
    redis_url: str | None
    disk_dir: str
    redis_host: str | None = None
    redis_port: int = 6379
    redis_password: str | None = None
    redis_ssl: bool = False


def effective_backend(cfg: CacheSettings) -> str:
    if cfg.redis_url or cfg.redis_host:
        return "redis"
    return cfg.cache_type if cfg.cache_type in ("local", "disk") else "local"


def parse_redis_url(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 6379,
        "password": parsed.password,
    }


def redis_params(cfg: CacheSettings) -> dict[str, Any]:
    if cfg.redis_url:
        params = parse_redis_url(cfg.redis_url)
        params["ssl"] = cfg.redis_url.startswith("rediss://")
        return params
    return {
        "host": cfg.redis_host or "localhost",
        "port": cfg.redis_port,
        "password": cfg.redis_password,
        "ssl": cfg.redis_ssl,
    }


async def load_cache_settings(
    session_factory: Callable[[], AsyncSession], settings: Settings
) -> CacheSettings:
    async with session_factory() as session:
        row = await session.get(GlobalSetting, 1)
    if row is None:
        return CacheSettings(
            "local", "gmc-ai", 2592000, 604800, settings.redis_url, settings.ai_cache_dir,
            redis_host=settings.redis_host,
            redis_port=settings.redis_port,
            redis_password=settings.redis_password,
            redis_ssl=settings.redis_ssl,
        )
    return CacheSettings(
        cache_type=row.ai_cache_type,
        namespace=row.ai_cache_namespace,
        ttl_taxonomy_s=row.ai_cache_ttl_taxonomy_s,
        ttl_content_s=row.ai_cache_ttl_content_s,
        redis_url=settings.redis_url,
        disk_dir=settings.ai_cache_dir,
        redis_host=settings.redis_host,
        redis_port=settings.redis_port,
        redis_password=settings.redis_password,
        redis_ssl=settings.redis_ssl,
    )


class NativeCache:
    def __init__(
        self,
        *,
        cache_type: str,
        namespace: str,
        ttl_taxonomy_s: int,
        ttl_content_s: int,
        redis_url: str | None,
        disk_dir: str,
        redis_host: str | None = None,
        redis_port: int = 6379,
        redis_password: str | None = None,
        redis_ssl: bool = False,
    ) -> None:
        self._cfg = CacheSettings(
            cache_type, namespace, ttl_taxonomy_s, ttl_content_s, redis_url, disk_dir,
            redis_host=redis_host,
            redis_port=redis_port,
            redis_password=redis_password,
            redis_ssl=redis_ssl,
        )
        self._cache: Any = self._build()
        self.enabled = self._cache is not None

    def _build(self) -> Any:
        try:
            backend = effective_backend(self._cfg)
            if backend == "redis":
                params = redis_params(self._cfg)
                built = Cache(
                    type=LiteLLMCacheType.REDIS,
                    mode=CacheMode.default_off,
                    host=params["host"],
                    port=params["port"],
                    password=params["password"],
                    ssl=params["ssl"],
                )
            elif backend == "disk":
                built = Cache(
                    type=LiteLLMCacheType.DISK,
                    mode=CacheMode.default_off,
                    disk_cache_dir=self._cfg.disk_dir,
                )
            else:
                built = Cache(type=LiteLLMCacheType.LOCAL, mode=CacheMode.default_off)
            litellm.cache = built
            return built
        except Exception:
            logger.warning(
                "ai cache: failed to build backend; continuing without cache",
                exc_info=True,
            )
            return None

    def request_kwargs(self, task_type: str) -> dict[str, Any]:
        ttl = (
            self._cfg.ttl_taxonomy_s
            if task_type in TAXONOMY_TASKS
            else self._cfg.ttl_content_s
        )
        return {
            "cache": {
                "use-cache": True,
                "namespace": f"{self._cfg.namespace}:{task_type}",
                "ttl": ttl,
            }
        }

    async def lookup(self, **kwargs: Any) -> Any | None:
        if self._cache is None:
            return None
        try:
            return await self._cache.async_get_cache(**kwargs)
        except Exception:
            logger.warning("ai cache: lookup failed; treating as miss", exc_info=True)
            return None

    async def store(self, result: Any, **kwargs: Any) -> None:
        if self._cache is None:
            return
        try:
            await self._cache.async_add_cache(result, **kwargs)
        except Exception:
            logger.warning("ai cache: store failed; continuing", exc_info=True)
