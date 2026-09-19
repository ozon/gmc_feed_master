from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import instructor
from litellm import Router
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.ai import AiProviderConfig
from ..models.global_setting import GlobalSetting

logger = logging.getLogger(__name__)

FALLBACKS = [{"bulk": ["precision"]}]


@dataclass(frozen=True)
class RouterSettings:
    timeout_s: int = 30
    num_retries: int = 2
    allowed_fails: int = 3
    cooldown_s: int = 30
    instructor_max_retries: int = 2


async def load_router_settings(
    session_factory: Callable[[], AsyncSession],
) -> RouterSettings:
    async with session_factory() as session:
        row = await session.get(GlobalSetting, 1)
    if row is None:
        return RouterSettings()
    return RouterSettings(
        timeout_s=row.ai_router_timeout_s,
        num_retries=row.ai_router_num_retries,
        allowed_fails=row.ai_router_allowed_fails,
        cooldown_s=row.ai_router_cooldown_s,
        instructor_max_retries=row.ai_instructor_max_retries,
    )


def _litellm_model(row: AiProviderConfig) -> str:
    if "/" in row.model:
        return row.model
    if row.provider_type == "openai_compatible":
        return f"openai/{row.model}"
    return row.model


def deployment_for(row: AiProviderConfig) -> dict[str, Any]:
    params: dict[str, Any] = {"model": _litellm_model(row)}
    if row.base_url:
        params["api_base"] = row.base_url
    if row.api_key:
        params["api_key"] = row.api_key
    params["timeout"] = row.timeout_s
    return {"model_name": row.tier, "litellm_params": params}


def build_router(
    rows: Sequence[AiProviderConfig], cfg: RouterSettings
) -> Router:
    model_list = [deployment_for(row) for row in rows if row.enabled]
    return Router(
        model_list=model_list,
        fallbacks=FALLBACKS,
        num_retries=cfg.num_retries,
        allowed_fails=cfg.allowed_fails,
        cooldown_time=cfg.cooldown_s,
        timeout=cfg.timeout_s,
    )


def build_instructor(router: Router) -> Any:
    return instructor.from_litellm(router.acompletion, async_client=True)
