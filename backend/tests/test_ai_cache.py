from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.ai import cache_config


def test_effective_backend_prefers_redis_from_env() -> None:
    cfg = cache_config.CacheSettings(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=1,
        ttl_content_s=2, redis_url="redis://localhost:6379/0", disk_dir="/tmp/x",
    )
    assert cache_config.effective_backend(cfg) == "redis"


def test_effective_backend_uses_row_type_without_redis() -> None:
    cfg = cache_config.CacheSettings(
        cache_type="disk", namespace="gmc-ai", ttl_taxonomy_s=1,
        ttl_content_s=2, redis_url=None, disk_dir="/tmp/x",
    )
    assert cache_config.effective_backend(cfg) == "disk"


def test_parse_redis_url() -> None:
    parsed = cache_config.parse_redis_url("redis://:secret@redis-host:6380/2")
    assert parsed == {"host": "redis-host", "port": 6380, "password": "secret"}


def test_parse_redis_url_defaults() -> None:
    parsed = cache_config.parse_redis_url("redis://localhost:6379/0")
    assert parsed == {"host": "localhost", "port": 6379, "password": None}


def test_request_kwargs_namespace_and_ttl() -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=100,
        ttl_content_s=5, redis_url=None, disk_dir="/tmp/x",
    )
    content = cache.request_kwargs("title_optimization")
    taxonomy = cache.request_kwargs("category_classification")
    assert content["cache"]["namespace"] == "gmc-ai:title_optimization"
    assert content["cache"]["ttl"] == 5
    assert taxonomy["cache"]["namespace"] == "gmc-ai:category_classification"
    assert taxonomy["cache"]["ttl"] == 100


@pytest.mark.asyncio
async def test_lookup_is_fail_open() -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=1,
        ttl_content_s=1, redis_url=None, disk_dir="/tmp/x",
    )

    class Boom:
        async def async_get_cache(self, **kwargs):
            raise RuntimeError("backend down")

    cache._cache = Boom()  # type: ignore[assignment]
    assert await cache.lookup(model="bulk", messages=[]) is None


@pytest.mark.asyncio
async def test_store_writes_validated_payload() -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=1,
        ttl_content_s=1, redis_url=None, disk_dir="/tmp/x",
    )
    fake = MagicMock()
    calls = []

    async def async_add_cache(result, **kwargs):
        calls.append((result, kwargs))

    fake.async_add_cache = async_add_cache
    cache._cache = fake  # type: ignore[assignment]
    await cache.store({"validated": True}, model="bulk", messages=[])
    assert calls and calls[0][0] == {"validated": True}


@pytest.mark.asyncio
async def test_lookup_returns_cached_value() -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=1,
        ttl_content_s=1, redis_url=None, disk_dir="/tmp/x",
    )

    class Fake:
        async def async_get_cache(self, **kwargs):
            return {"value": "cached"}

    cache._cache = Fake()  # type: ignore[assignment]
    assert await cache.lookup(model="bulk", messages=[]) == {"value": "cached"}


def test_effective_backend_uses_discrete_redis_vars() -> None:
    cfg = cache_config.CacheSettings(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=1, ttl_content_s=1,
        redis_url=None, disk_dir="/tmp/x", redis_host="redis-host",
    )
    assert cache_config.effective_backend(cfg) == "redis"


def test_redis_params_url_takes_precedence_over_discrete_vars() -> None:
    cfg = cache_config.CacheSettings(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=1, ttl_content_s=1,
        redis_url="rediss://:pw@urlhost:6380/0", disk_dir="/tmp/x",
        redis_host="otherhost",
    )
    assert cache_config.redis_params(cfg) == {
        "host": "urlhost", "port": 6380, "password": "pw", "ssl": True,
    }


@pytest.mark.asyncio
async def test_local_round_trip_with_use_cache_flag() -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=60,
        ttl_content_s=60, redis_url=None, disk_dir="/tmp/ai-cache-test",
    )
    kwargs = cache.request_kwargs("title_optimization")
    assert kwargs["cache"]["use-cache"] is True
    request = {"model": "bulk", "messages": [{"role": "user", "content": "hi"}], **kwargs}
    await cache.store({"title": "Hello"}, **request)
    assert await cache.lookup(**request) == {"title": "Hello"}


@pytest.mark.asyncio
async def test_lookup_miss_returns_none_when_not_stored() -> None:
    cache = cache_config.NativeCache(
        cache_type="local", namespace="gmc-ai", ttl_taxonomy_s=60,
        ttl_content_s=60, redis_url=None, disk_dir="/tmp/ai-cache-test",
    )
    kwargs = cache.request_kwargs("title_optimization")
    assert await cache.lookup(
        model="bulk", messages=[{"role": "user", "content": "never"}], **kwargs
    ) is None
