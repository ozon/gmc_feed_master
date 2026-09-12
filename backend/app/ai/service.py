from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..clock import Clock
from ..models.ai import AiProviderConfig, PromptTemplate
from .cache import AiResultCacheStore
from .openai_compat import OpenAICompatibleProvider
from .provider import AIProvider, AiRequest, AiResponse
from .resilience import (
    CircuitBreaker,
    RetryPolicy,
    classify_failure,
)
from .tasks import TASK_SPECS, TaskSpec, input_hash, validate_task
from .templates import TaskSpecError, render_messages
from .usage import UsageLogWriter, UsageRecord, estimate_cost

logger = logging.getLogger(__name__)

TEMPLATE_VERSION_BUILTIN = "builtin"


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


def default_provider_factory(config: AiProviderConfig) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        timeout_s=config.timeout_s,
    )


class AiChatUnavailable(Exception):
    """Raised when a chat completion cannot be served (no provider, breaker open, provider failure)."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class AiService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        clock: Clock | None = None,
        provider_factory: Callable[[AiProviderConfig], AIProvider] | None = None,
        retry_policy: RetryPolicy | None = None,
        breaker_failure_threshold: int = 5,
        breaker_window_s: int = 60,
        breaker_cooldown_s: int = 30,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._provider_factory = (
            provider_factory if provider_factory is not None else default_provider_factory
        )
        self._retry_policy = retry_policy if retry_policy is not None else RetryPolicy()
        self._cache = AiResultCacheStore(session_factory)
        self._usage = UsageLogWriter(session_factory)
        self._providers: dict[int, AIProvider] = {}
        self._breakers: dict[int, CircuitBreaker] = {}
        self._semaphores: dict[int, asyncio.Semaphore] = {}
        self._breaker_failure_threshold = breaker_failure_threshold
        self._breaker_window_s = breaker_window_s
        self._breaker_cooldown_s = breaker_cooldown_s

    # -- config resolution ------------------------------------------------

    async def _default_config(self) -> AiProviderConfig | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(AiProviderConfig)
                .where(AiProviderConfig.enabled.is_(True), AiProviderConfig.is_default.is_(True))
                .order_by(AiProviderConfig.id)
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def _get_config(self, provider_config_id: int) -> AiProviderConfig | None:
        async with self._session_factory() as session:
            return await session.get(AiProviderConfig, provider_config_id)

    async def _resolve_template(
        self, task_type: str, client_id: int | None
    ) -> ResolvedTemplate:
        if task_type not in TASK_SPECS:
            raise TaskSpecError(f"unknown task type {task_type!r}")
        resolved = await resolve_active_template(
            self._session_factory, task_type, client_id
        )
        if resolved is not None:
            return resolved
        spec = TASK_SPECS[task_type]
        return ResolvedTemplate(
            system=spec.system, user=spec.user, version=builtin_template_version(spec)
        )

    # -- per-config collaborators -----------------------------------------

    def _provider_for(self, config: AiProviderConfig) -> AIProvider:
        provider = self._providers.get(config.id)
        if provider is None:
            provider = self._provider_factory(config)
            self._providers[config.id] = provider
        return provider

    def _breaker_for(self, config: AiProviderConfig) -> CircuitBreaker:
        breaker = self._breakers.get(config.id)
        if breaker is None:
            breaker = CircuitBreaker(
                failure_threshold=self._breaker_failure_threshold,
                window_s=self._breaker_window_s,
                cooldown_s=self._breaker_cooldown_s,
                clock=self._clock,
            )
            self._breakers[config.id] = breaker
        return breaker

    def _semaphore_for(self, config: AiProviderConfig) -> asyncio.Semaphore:
        semaphore = self._semaphores.get(config.id)
        if semaphore is None:
            semaphore = asyncio.Semaphore(max(1, config.max_concurrency))
            self._semaphores[config.id] = semaphore
        return semaphore

    def invalidate(self, provider_config_id: int) -> None:
        """Drop cached collaborators for a config so the next call rebuilds them.

        Called by the admin routes after PATCH/DELETE so runtime config edits
        (api_key, base_url, model, max_concurrency) take effect immediately.
        """
        self._providers.pop(provider_config_id, None)
        self._breakers.pop(provider_config_id, None)
        self._semaphores.pop(provider_config_id, None)

    # -- public API ---------------------------------------------------------

    async def run_task(
        self,
        task_type: str,
        variables: dict[str, Any],
        *,
        client_id: int | None = None,
        feed_source_id: int | None = None,
    ) -> AiResult:
        config = await self._default_config()
        if config is None:
            await self._log_usage(UsageRecord(
                client_id=client_id, feed_source_id=feed_source_id,
                task_type=task_type, provider_config_id=None, model="",
                cache_hit=False, prompt_tokens=0, completion_tokens=0,
                cost_usd=None, latency_ms=0, error_code="no_provider",
            ))
            return AiResult(value=None, status="fallback", error_code="no_provider",
                            prompt_tokens=0, completion_tokens=0)

        try:
            template = await self._resolve_template(task_type, client_id)
        except TaskSpecError:
            await self._log_usage(UsageRecord(
                client_id=client_id, feed_source_id=feed_source_id,
                task_type=task_type, provider_config_id=None, model="",
                cache_hit=False, prompt_tokens=0, completion_tokens=0,
                cost_usd=None, latency_ms=0, error_code="invalid_task",
            ))
            return AiResult(value=None, status="fallback", error_code="invalid_task",
                            prompt_tokens=0, completion_tokens=0)

        hash_value = input_hash(task_type, variables)

        cache_entry = await self._cache.lookup(
            task_type, config.id, config.model, template.version, hash_value
        )
        if cache_entry is not None:
            await self._log_usage(UsageRecord(
                client_id=client_id, feed_source_id=feed_source_id,
                task_type=task_type, provider_config_id=config.id, model=config.model,
                cache_hit=True, prompt_tokens=0, completion_tokens=0,
                cost_usd=None, latency_ms=0, error_code=None,
            ))
            return AiResult(value=cache_entry.output.get("value"), status="cache_hit",
                            error_code=None, prompt_tokens=0, completion_tokens=0)

        return await self._call_provider(
            config, task_type, variables, hash_value, template,
            client_id=client_id, feed_source_id=feed_source_id,
        )

    async def complete_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        client_id: int | None = None,
        feed_source_id: int | None = None,
    ) -> AiResponse:
        config = await self._default_config()
        if config is None:
            await self._log_usage(UsageRecord(
                client_id=client_id, feed_source_id=feed_source_id,
                task_type="chat", provider_config_id=None, model="",
                cache_hit=False, prompt_tokens=0, completion_tokens=0,
                cost_usd=None, latency_ms=0, error_code="no_provider",
            ))
            raise AiChatUnavailable("no_provider")
        breaker = self._breaker_for(config)
        if not breaker.allow_call():
            await self._log_usage(UsageRecord(
                client_id=client_id, feed_source_id=feed_source_id,
                task_type="chat", provider_config_id=config.id, model=config.model,
                cache_hit=False, prompt_tokens=0, completion_tokens=0,
                cost_usd=None, latency_ms=0, error_code="circuit_open",
            ))
            raise AiChatUnavailable("circuit_open")
        provider = self._provider_for(config)
        semaphore = self._semaphore_for(config)
        error_code: str | None = None
        async with semaphore:
            for attempt in range(1, self._retry_policy.max_attempts + 1):
                try:
                    response = await provider.complete(AiRequest(
                        task_type="chat", messages=messages, tools=tools,
                    ))
                except Exception as exc:  # noqa: BLE001 — chat degrades to 502, never aborts
                    outcome, retryable = classify_failure(exc)
                    if not retryable or attempt == self._retry_policy.max_attempts:
                        error_code = outcome.value
                        breaker.record_failure()
                        break
                    await asyncio.sleep(self._retry_policy.delay_for_attempt(attempt))
                    continue
                breaker.record_success()
                cost = estimate_cost(
                    response.prompt_tokens, response.completion_tokens,
                    config.input_price_per_mtok, config.output_price_per_mtok,
                )
                await self._log_usage(UsageRecord(
                    client_id=client_id, feed_source_id=feed_source_id,
                    task_type="chat", provider_config_id=config.id, model=response.model,
                    cache_hit=False, prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    cost_usd=cost, latency_ms=response.latency_ms, error_code=None,
                ))
                return response
        await self._log_usage(UsageRecord(
            client_id=client_id, feed_source_id=feed_source_id,
            task_type="chat", provider_config_id=config.id, model=config.model,
            cache_hit=False, prompt_tokens=0, completion_tokens=0,
            cost_usd=None, latency_ms=0, error_code=error_code or "unknown",
        ))
        raise AiChatUnavailable(error_code or "unknown")

    async def test_provider(self, config_id: int) -> dict[str, Any]:
        config = await self._get_config(config_id)
        if config is None:
            return {"status": "error", "error_code": "no_provider"}
        provider = self._provider_for(config)
        try:
            request = AiRequest(
                task_type="test",
                messages=[
                    {"role": "system", "content": "Reply with the single word OK."},
                    {"role": "user", "content": "Ping"},
                ],
                max_tokens=8,
                temperature=0.0,
            )
            response = await provider.complete(request)
        except Exception as exc:  # noqa: BLE001 — probe must report any failure
            outcome, _ = classify_failure(exc)
            return {"status": "error", "error_code": outcome.value}
        return {
            "status": "ok",
            "latency_ms": response.latency_ms,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
        }

    # -- internals -----------------------------------------------------------

    async def _call_provider(
        self,
        config: AiProviderConfig,
        task_type: str,
        variables: dict[str, Any],
        hash_value: str,
        template: ResolvedTemplate,
        *,
        client_id: int | None,
        feed_source_id: int | None,
    ) -> AiResult:
        breaker = self._breaker_for(config)
        if not breaker.allow_call():
            await self._log_usage(UsageRecord(
                client_id=client_id, feed_source_id=feed_source_id,
                task_type=task_type, provider_config_id=config.id, model=config.model,
                cache_hit=False, prompt_tokens=0, completion_tokens=0,
                cost_usd=None, latency_ms=0, error_code="circuit_open",
            ))
            return AiResult(value=None, status="fallback", error_code="circuit_open",
                            prompt_tokens=0, completion_tokens=0)

        provider = self._provider_for(config)
        semaphore = self._semaphore_for(config)
        try:
            messages = render_messages(template.system, template.user, variables)
        except TaskSpecError:
            logger.exception("ai task %s could not render; falling back", task_type)
            await self._log_usage(UsageRecord(
                client_id=client_id, feed_source_id=feed_source_id,
                task_type=task_type, provider_config_id=config.id, model=config.model,
                cache_hit=False, prompt_tokens=0, completion_tokens=0,
                cost_usd=None, latency_ms=0, error_code="invalid_task",
            ))
            return AiResult(value=None, status="fallback", error_code="invalid_task",
                            prompt_tokens=0, completion_tokens=0)
        retryable_error_code: str | None = None

        async with semaphore:
            for attempt in range(1, self._retry_policy.max_attempts + 1):
                try:
                    response = await provider.complete(AiRequest(
                        task_type=task_type, messages=messages,
                    ))
                except Exception as exc:  # noqa: BLE001 — AI failures degrade to fallback, never abort runs
                    outcome, retryable = classify_failure(exc)
                    if not retryable or attempt == self._retry_policy.max_attempts:
                        retryable_error_code = outcome.value
                        breaker.record_failure()
                        break
                    await asyncio.sleep(self._retry_policy.delay_for_attempt(attempt))
                    continue
                # Provider responded — validate the content.
                try:
                    value = validate_task(task_type, response.content)
                except TaskSpecError:
                    breaker.record_failure()
                    await self._log_usage(UsageRecord(
                        client_id=client_id, feed_source_id=feed_source_id,
                        task_type=task_type, provider_config_id=config.id,
                        model=response.model, cache_hit=False,
                        prompt_tokens=response.prompt_tokens,
                        completion_tokens=response.completion_tokens,
                        cost_usd=None, latency_ms=response.latency_ms,
                        error_code="invalid_response",
                    ))
                    return AiResult(value=None, status="fallback",
                                    error_code="invalid_response",
                                    prompt_tokens=response.prompt_tokens,
                                    completion_tokens=response.completion_tokens)
                breaker.record_success()
                await self._cache.store(
                    task_type, config.id, config.model, template.version,
                    hash_value, {"value": value},
                )
                cost = estimate_cost(
                    response.prompt_tokens, response.completion_tokens,
                    config.input_price_per_mtok, config.output_price_per_mtok,
                )
                await self._log_usage(UsageRecord(
                    client_id=client_id, feed_source_id=feed_source_id,
                    task_type=task_type, provider_config_id=config.id,
                    model=response.model, cache_hit=False,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    cost_usd=cost, latency_ms=response.latency_ms, error_code=None,
                ))
                return AiResult(value=value, status="ok", error_code=None,
                                prompt_tokens=response.prompt_tokens,
                                completion_tokens=response.completion_tokens)

        # Exhausted retries (or non-retryable failure).
        if retryable_error_code is None:
            retryable_error_code = "unknown"
        await self._log_usage(UsageRecord(
            client_id=client_id, feed_source_id=feed_source_id,
            task_type=task_type, provider_config_id=config.id, model=config.model,
            cache_hit=False, prompt_tokens=0, completion_tokens=0,
            cost_usd=None, latency_ms=0, error_code=retryable_error_code,
        ))
        return AiResult(value=None, status="fallback", error_code=retryable_error_code,
                        prompt_tokens=0, completion_tokens=0)

    async def _log_usage(self, record: UsageRecord) -> None:
        await self._usage.write(record)
