from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..clock import Clock
from ..config import Settings, get_settings
from ..models.ai import AiProviderConfig, PromptTemplate
from ..models.global_setting import GlobalSetting
from .cache_config import NativeCache, load_cache_settings
from .provider import AiResponse
from .router import RouterSettings, build_instructor, build_router, load_router_settings
from .schemas import RuleValueResult
from .tasks import TASK_SPECS, TaskSpec
from .templates import TaskSpecError, render_messages
from .usage import UsageLogWriter, UsageRecord

logger = logging.getLogger(__name__)

TEMPLATE_VERSION_BUILTIN = "builtin"
TIER_BULK = "bulk"
GENERIC_AI_TASK = "rule_value"


def builtin_template_version(spec: TaskSpec) -> str:
    """Content-hash the builtin prompts so any code change auto-invalidates cache rows."""
    digest = hashlib.sha256(
        (spec.system + "\x00" + spec.user).encode("utf-8")
    ).hexdigest()[:12]
    return f"{TEMPLATE_VERSION_BUILTIN}:{digest}"


@dataclass(frozen=True)
class AiResult:
    value: Any
    status: str  # "ok" | "cache_hit" | "fallback"
    error_code: str | None
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class ResolvedTemplate:
    system: str
    user: str
    version: str


async def resolve_active_template(
    session_factory: Callable[[], AsyncSession],
    task_type: str,
    client_id: int | None,
) -> ResolvedTemplate | None:
    """Find the active DB template (client scope first, then global).

    Any DB failure is logged and returns None so callers fall back to the
    builtin registry — template resolution must never fail a run.
    """
    try:
        async with session_factory() as session:
            row = None
            if client_id is not None:
                row = (await session.execute(
                    select(PromptTemplate).where(
                        PromptTemplate.task_type == task_type,
                        PromptTemplate.client_id == client_id,
                        PromptTemplate.is_active.is_(True),
                    ).limit(1)
                )).scalar_one_or_none()
            if row is None:
                row = (await session.execute(
                    select(PromptTemplate).where(
                        PromptTemplate.task_type == task_type,
                        PromptTemplate.client_id.is_(None),
                        PromptTemplate.is_active.is_(True),
                    ).limit(1)
                )).scalar_one_or_none()
    except Exception:
        logger.exception("ai template resolution failed; using builtin")
        return None
    if row is None:
        return None
    return ResolvedTemplate(
        system=row.system_prompt,
        user=row.user_prompt,
        version=f"tmpl:{row.id}:v{row.version}",
    )


async def resolve_template_by_id(
    session_factory: Callable[[], AsyncSession],
    template_id: int,
    client_id: int | None,
) -> ResolvedTemplate | None:
    """Load one pinned template, scoped to global or the given client.

    Returns None (caller falls back to active/builtin) on any miss or DB error.
    """
    try:
        async with session_factory() as session:
            row = await session.get(PromptTemplate, template_id)
    except Exception:
        logger.exception("ai pinned template lookup failed; using active/builtin")
        return None
    if row is None or not row.is_active:
        return None
    if row.client_id is not None and row.client_id != client_id:
        return None
    return ResolvedTemplate(
        system=row.system_prompt,
        user=row.user_prompt,
        version=f"tmpl:{row.id}:v{row.version}",
    )


class AiChatUnavailable(Exception):
    """Raised when a chat completion cannot be served (no provider, provider failure)."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class AiService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        clock: Clock | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._settings = settings if settings is not None else get_settings()
        self._usage = UsageLogWriter(session_factory)
        self._cache: Any = None
        self._router: Any = None
        self._instructor_client: Any = None
        self._router_settings: RouterSettings | None = None

    # -- config resolution ------------------------------------------------

    async def _load_deployments(self) -> list[AiProviderConfig]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(AiProviderConfig)
                .where(AiProviderConfig.enabled.is_(True))
                .order_by(AiProviderConfig.id)
            )
            return list(result.scalars())

    async def _resolve_template(
        self, task_type: str, client_id: int | None, template_id: int | None = None
    ) -> ResolvedTemplate:
        if task_type not in TASK_SPECS:
            raise TaskSpecError(f"unknown task type {task_type!r}")
        if template_id is not None:
            pinned = await resolve_template_by_id(
                self._session_factory, template_id, client_id
            )
            if pinned is not None:
                return pinned
            logger.warning(
                "ai: pinned template %s unavailable; using active/builtin", template_id
            )
        resolved = await resolve_active_template(
            self._session_factory, task_type, client_id
        )
        if resolved is not None:
            return resolved
        spec = TASK_SPECS[task_type]
        return ResolvedTemplate(
            system=spec.system, user=spec.user, version=builtin_template_version(spec)
        )

    # -- runtime collaborators --------------------------------------------

    def _ensure_built(self, rows: list[AiProviderConfig], cfg: RouterSettings) -> None:
        self._router_settings = cfg
        self._router = build_router(rows, cfg)
        self._instructor_client = build_instructor(self._router)

    def _instructor(self) -> Any:
        if self._instructor_client is None:
            raise AiChatUnavailable("no_provider")
        return self._instructor_client

    async def _ensure_cache(self) -> None:
        if self._cache is None:
            cache_cfg = await load_cache_settings(self._session_factory, self._settings)
            self._cache = NativeCache(
                cache_type=cache_cfg.cache_type,
                namespace=cache_cfg.namespace,
                ttl_taxonomy_s=cache_cfg.ttl_taxonomy_s,
                ttl_content_s=cache_cfg.ttl_content_s,
                redis_url=cache_cfg.redis_url,
                disk_dir=cache_cfg.disk_dir,
            )

    def invalidate(self, provider_config_id: int | None = None) -> None:
        """Drop built collaborators so the next call rebuilds them."""
        self._router = None
        self._instructor_client = None
        self._cache = None
        self._router_settings = None

    async def apply_settings(self, row: GlobalSetting) -> None:
        """Build cache + router from a settings row and swap them in on success.

        Raises (leaving the previously active collaborators untouched) when the
        configured cache backend or router cannot be built.
        """
        cfg = RouterSettings(
            timeout_s=row.ai_router_timeout_s,
            num_retries=row.ai_router_num_retries,
            allowed_fails=row.ai_router_allowed_fails,
            cooldown_s=row.ai_router_cooldown_s,
            instructor_max_retries=row.ai_instructor_max_retries,
        )
        rows = await self._load_deployments()
        router = build_router(rows, cfg)
        instructor_client = build_instructor(router)
        cache = NativeCache(
            cache_type=row.ai_cache_type,
            namespace=row.ai_cache_namespace,
            ttl_taxonomy_s=row.ai_cache_ttl_taxonomy_s,
            ttl_content_s=row.ai_cache_ttl_content_s,
            redis_url=self._settings.redis_url,
            disk_dir=self._settings.ai_cache_dir,
            redis_host=self._settings.redis_host,
            redis_port=self._settings.redis_port,
            redis_password=self._settings.redis_password,
            redis_ssl=self._settings.redis_ssl,
        )
        if not cache.enabled:
            raise ValueError("configured cache backend is unavailable")
        self._router = router
        self._instructor_client = instructor_client
        self._router_settings = cfg
        self._cache = cache

    async def cache_status(self) -> dict[str, Any]:
        await self._ensure_cache()
        return await self._cache.status()

    async def clear_cache(self, namespace: str | None = None) -> int:
        await self._ensure_cache()
        return await self._cache.clear(namespace)

    # -- public API ---------------------------------------------------------

    async def run_task(
        self,
        task_type: str,
        variables: dict[str, Any],
        *,
        client_id: int | None = None,
        feed_source_id: int | None = None,
        template_id: int | None = None,
    ) -> AiResult:
        if task_type not in TASK_SPECS:
            await self._log_error(task_type, client_id, feed_source_id, "invalid_task")
            return AiResult(value=None, status="fallback", error_code="invalid_task",
                            prompt_tokens=0, completion_tokens=0)
        try:
            template = await self._resolve_template(task_type, client_id, template_id)
            messages = render_messages(template.system, template.user, variables)
        except TaskSpecError:
            logger.exception("ai task %s could not render; falling back", task_type)
            await self._log_error(task_type, client_id, feed_source_id, "invalid_task")
            return AiResult(value=None, status="fallback", error_code="invalid_task",
                            prompt_tokens=0, completion_tokens=0)
        return await self._execute_task(
            log_task_type=task_type,
            cache_task_type=task_type,
            response_model=TASK_SPECS[task_type].response_model,
            messages=messages,
            client_id=client_id,
            feed_source_id=feed_source_id,
        )

    async def run_inline_task(
        self,
        system: str,
        user: str,
        variables: dict[str, Any],
        *,
        client_id: int | None = None,
        feed_source_id: int | None = None,
    ) -> AiResult:
        try:
            messages = render_messages(system, user, variables)
        except TaskSpecError:
            logger.exception("ai inline task could not render; falling back")
            await self._log_error(GENERIC_AI_TASK, client_id, feed_source_id, "invalid_task")
            return AiResult(value=None, status="fallback", error_code="invalid_task",
                            prompt_tokens=0, completion_tokens=0)
        return await self._execute_task(
            log_task_type=GENERIC_AI_TASK,
            cache_task_type=GENERIC_AI_TASK,
            response_model=RuleValueResult,
            messages=messages,
            client_id=client_id,
            feed_source_id=feed_source_id,
        )

    async def _execute_task(
        self,
        *,
        log_task_type: str,
        cache_task_type: str,
        response_model: type[Any],
        messages: list[dict[str, str]],
        client_id: int | None,
        feed_source_id: int | None,
    ) -> AiResult:
        rows = await self._load_deployments()
        if not rows:
            await self._log_error(log_task_type, client_id, feed_source_id, "no_provider")
            return AiResult(value=None, status="fallback", error_code="no_provider",
                            prompt_tokens=0, completion_tokens=0)

        cfg = self._router_settings or await load_router_settings(self._session_factory)
        if self._router is None:
            try:
                self._ensure_built(rows, cfg)
            except Exception as exc:
                logger.warning("ai router build failed: %s", exc, exc_info=True)
                await self._log_error(log_task_type, client_id, feed_source_id, "provider_error")
                return AiResult(value=None, status="fallback", error_code="provider_error",
                                prompt_tokens=0, completion_tokens=0)
        await self._ensure_cache()

        cache_kwargs = self._cache.request_kwargs(cache_task_type)
        cache_request = {"model": TIER_BULK, "messages": messages, **cache_kwargs}

        cached = await self._cache.lookup(**cache_request)
        if cached is not None:
            try:
                value = response_model.model_validate(cached)
            except Exception:  # noqa: BLE001 — any invalid cached payload is a miss
                value = None
            if value is not None:
                await self._log_usage(UsageRecord(
                    client_id=client_id, feed_source_id=feed_source_id,
                    task_type=log_task_type, provider_config_id=None, model=TIER_BULK,
                    cache_hit=True, prompt_tokens=0, completion_tokens=0,
                    cost_usd=None, latency_ms=0, error_code=None,
                ))
                return AiResult(value=value, status="cache_hit", error_code=None,
                                prompt_tokens=0, completion_tokens=0)

        started = time.monotonic()
        try:
            value, completion = await self._instructor().create_with_completion(
                response_model=response_model,
                messages=messages,
                model=TIER_BULK,
                max_retries=cfg.instructor_max_retries,
            )
        except Exception as exc:
            logger.warning("ai task %s failed: %s", log_task_type, exc, exc_info=True)
            await self._log_error(log_task_type, client_id, feed_source_id, "provider_error")
            return AiResult(value=None, status="fallback", error_code="provider_error",
                            prompt_tokens=0, completion_tokens=0)

        latency_ms = int((time.monotonic() - started) * 1000)
        await self._cache.store(value.model_dump(), **cache_request)
        usage = getattr(completion, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        await self._log_usage(UsageRecord(
            client_id=client_id, feed_source_id=feed_source_id,
            task_type=log_task_type, provider_config_id=None, model=TIER_BULK,
            cache_hit=False, prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens, cost_usd=None,
            latency_ms=latency_ms, error_code=None,
        ))
        return AiResult(value=value, status="ok", error_code=None,
                        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)

    async def complete_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        client_id: int | None = None,
        feed_source_id: int | None = None,
    ) -> AiResponse:
        rows = await self._load_deployments()
        if not rows:
            await self._log_error("chat", client_id, feed_source_id, "no_provider")
            raise AiChatUnavailable("no_provider")
        cfg = self._router_settings or await load_router_settings(self._session_factory)
        if self._router is None:
            try:
                self._ensure_built(rows, cfg)
            except Exception as exc:
                logger.warning("ai router build failed: %s", exc, exc_info=True)
                await self._log_error("chat", client_id, feed_source_id, "provider_error")
                raise AiChatUnavailable("provider_error") from exc
        started = time.monotonic()
        try:
            response = await self._router.acompletion(
                model=TIER_BULK, messages=messages, tools=tools or None,
            )
        except Exception as exc:  # chat degrades to 503, never aborts
            logger.warning("ai chat failed: %s", exc, exc_info=True)
            await self._log_error("chat", client_id, feed_source_id, "provider_error")
            raise AiChatUnavailable("provider_error") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        usage = getattr(response, "usage", None)
        message = response.choices[0].message
        await self._log_usage(UsageRecord(
            client_id=client_id, feed_source_id=feed_source_id,
            task_type="chat", provider_config_id=None, model=response.model or TIER_BULK,
            cache_hit=False,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            cost_usd=None, latency_ms=latency_ms, error_code=None,
        ))
        return AiResponse(
            content=message.content or "",
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            model=response.model or TIER_BULK,
            latency_ms=latency_ms,
            tool_calls=getattr(message, "tool_calls", None),
            finish_reason=getattr(response.choices[0], "finish_reason", "stop") or "stop",
        )

    async def test_provider(self, config_id: int) -> dict[str, Any]:
        async with self._session_factory() as session:
            config = await session.get(AiProviderConfig, config_id)
        if config is None:
            return {"status": "error", "error_code": "no_provider"}
        cfg = self._router_settings or await load_router_settings(self._session_factory)
        started = time.monotonic()
        try:
            router = build_router([config], cfg)
            response = await router.acompletion(
                model=config.tier,
                messages=[
                    {"role": "system", "content": "Reply with the single word OK."},
                    {"role": "user", "content": "Ping"},
                ],
                max_tokens=8,
                temperature=0.0,
            )
        except Exception as exc:  # probe must report any failure
            logger.warning("ai provider probe failed: %s", exc, exc_info=True)
            return {"status": "error", "error_code": "provider_error"}
        usage = getattr(response, "usage", None)
        return {
            "status": "ok",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        }

    # -- internals -----------------------------------------------------------

    async def _log_error(
        self,
        task_type: str,
        client_id: int | None,
        feed_source_id: int | None,
        error_code: str,
    ) -> None:
        await self._log_usage(UsageRecord(
            client_id=client_id, feed_source_id=feed_source_id,
            task_type=task_type, provider_config_id=None, model="",
            cache_hit=False, prompt_tokens=0, completion_tokens=0,
            cost_usd=None, latency_ms=0, error_code=error_code,
        ))

    async def _log_usage(self, record: UsageRecord) -> None:
        await self._usage.write(record)
