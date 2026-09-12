from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from ..access import CurrentUser, require_admin
from ..ai.tasks import CANONICAL_VARIABLES
from ..ai.templates import parse_placeholders, render_messages, validate_template
from ..ai.usage import aggregate_usage
from ..db.engine import get_db_session
from ..models.ai import AiProviderConfig, PromptTemplate
from ..models.client import Client
from ..models.staging import StagingProduct
from ..schemas.ai_admin import (
    AiProviderCreate,
    AiProviderOut,
    AiProviderUpdate,
    PromptTemplateCreate,
    PromptTemplateOut,
    PromptTemplatePreviewRequest,
)

router = APIRouter()

DbSession = Annotated[AsyncSession | None, Depends(get_db_session)]
AdminUser = Annotated[CurrentUser, Depends(require_admin)]
UsageGroupBy = Annotated[str, Query(pattern="^(client|feed_source|task_type|day)$")]
UsageFrom = Annotated[datetime | None, Query(alias="from")]
UsageTo = Annotated[datetime | None, Query(alias="to")]


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _is_deadlock(exc: OperationalError) -> bool:
    return "deadlock" in str(getattr(exc, "orig", exc)).lower()


def _ai_service(request: Request):
    service = getattr(request.app.state, "ai_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="ai service unavailable")
    return service


async def _clear_other_defaults(session: AsyncSession, keep_id: int) -> None:
    await session.execute(
        update(AiProviderConfig)
        .where(AiProviderConfig.id != keep_id)
        .values(is_default=False)
    )


@router.get("/admin/ai/providers", response_model=list[AiProviderOut])
async def list_providers(
    _admin: AdminUser,
    db_session: DbSession,
) -> list[AiProviderOut]:
    session = _require_db(db_session)
    result = await session.execute(select(AiProviderConfig).order_by(AiProviderConfig.id))
    return [AiProviderOut.model_validate(row) for row in result.scalars()]


@router.post("/admin/ai/providers", status_code=201, response_model=AiProviderOut)
async def create_provider(
    payload: AiProviderCreate,
    _admin: AdminUser,
    db_session: DbSession,
) -> AiProviderOut:
    session = _require_db(db_session)
    async with session.begin():
        row = AiProviderConfig(**payload.model_dump())
        session.add(row)
        await session.flush()
        if row.is_default:
            await _clear_other_defaults(session, row.id)
    return AiProviderOut.model_validate(row)


@router.patch("/admin/ai/providers/{provider_id}", response_model=AiProviderOut)
async def update_provider(
    provider_id: int,
    payload: AiProviderUpdate,
    request: Request,
    _admin: AdminUser,
    db_session: DbSession,
) -> AiProviderOut:
    session = _require_db(db_session)
    async with session.begin():
        row = await session.get(AiProviderConfig, provider_id)
        if row is None:
            raise HTTPException(status_code=404, detail="provider not found")
        updates = payload.model_dump(exclude_unset=True)
        if "api_key" in updates:
            row.api_key = updates.pop("api_key")
        for key, value in updates.items():
            setattr(row, key, value)
        await session.flush()
        if row.is_default:
            await _clear_other_defaults(session, row.id)
    await session.refresh(row)
    service = getattr(request.app.state, "ai_service", None)
    if service is not None:
        service.invalidate(provider_id)
    return AiProviderOut.model_validate(row)


@router.delete("/admin/ai/providers/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: int,
    request: Request,
    _admin: AdminUser,
    db_session: DbSession,
) -> None:
    session = _require_db(db_session)
    async with session.begin():
        row = await session.get(AiProviderConfig, provider_id)
        if row is None:
            raise HTTPException(status_code=404, detail="provider not found")
        await session.delete(row)
    service = getattr(request.app.state, "ai_service", None)
    if service is not None:
        service.invalidate(provider_id)


@router.post("/admin/ai/providers/{provider_id}/test")
async def test_provider(
    provider_id: int,
    request: Request,
    _admin: AdminUser,
    db_session: DbSession,
) -> dict[str, Any]:
    _require_db(db_session)  # service resolves config through its own session
    service = _ai_service(request)
    return await service.test_provider(provider_id)


@router.get("/admin/ai/usage")
async def get_usage(
    _admin: AdminUser,
    db_session: DbSession,
    group_by: UsageGroupBy = "client",
    client_id: int | None = None,
    feed_source_id: int | None = None,
    task_type: str | None = None,
    from_dt: UsageFrom = None,
    to_dt: UsageTo = None,
) -> dict[str, Any]:
    session = _require_db(db_session)
    rows = await aggregate_usage(
        session,
        client_id=client_id, feed_source_id=feed_source_id,
        task_type=task_type, from_dt=from_dt, to_dt=to_dt,
        group_by=group_by,
    )
    return {"rows": rows}


def _template_scope_filter(client_id: int | None):
    if client_id is None:
        return PromptTemplate.client_id.is_(None)
    return PromptTemplate.client_id == client_id


async def _deactivate_other_templates(
    session: AsyncSession, task_type: str, client_id: int | None, keep_id: int
) -> None:
    await session.execute(
        update(PromptTemplate)
        .where(
            PromptTemplate.task_type == task_type,
            _template_scope_filter(client_id),
            PromptTemplate.id != keep_id,
        )
        .values(is_active=False)
    )


@router.get("/admin/ai/prompt-templates", response_model=list[PromptTemplateOut])
async def list_prompt_templates(
    _admin: AdminUser,
    db_session: DbSession,
    task_type: str | None = None,
    client_id: int | None = None,
) -> list[PromptTemplateOut]:
    session = _require_db(db_session)
    statement = select(PromptTemplate).order_by(
        PromptTemplate.task_type, PromptTemplate.client_id, PromptTemplate.version.desc()
    )
    if task_type is not None:
        statement = statement.where(PromptTemplate.task_type == task_type)
    if client_id is not None:
        statement = statement.where(PromptTemplate.client_id == client_id)
    result = await session.execute(statement)
    return [PromptTemplateOut.model_validate(row) for row in result.scalars()]


@router.get("/admin/ai/prompt-templates/{template_id}", response_model=PromptTemplateOut)
async def get_prompt_template(
    template_id: int,
    _admin: AdminUser,
    db_session: DbSession,
) -> PromptTemplateOut:
    session = _require_db(db_session)
    row = await session.get(PromptTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="prompt template not found")
    return PromptTemplateOut.model_validate(row)


@router.post("/admin/ai/prompt-templates", status_code=201, response_model=PromptTemplateOut)
async def create_prompt_template(
    payload: PromptTemplateCreate,
    _admin: AdminUser,
    db_session: DbSession,
) -> PromptTemplateOut:
    session = _require_db(db_session)
    if payload.task_type not in CANONICAL_VARIABLES:
        raise HTTPException(
            status_code=422, detail=f"unknown task type {payload.task_type!r}"
        )
    validation = validate_template(
        CANONICAL_VARIABLES[payload.task_type],
        payload.system_prompt, payload.user_prompt, payload.variables,
    )
    if validation.errors:
        raise HTTPException(
            status_code=422,
            detail={"errors": validation.errors, "warnings": validation.warnings},
        )
    try:
        async with session.begin():
            if (
                payload.client_id is not None
                and await session.get(Client, payload.client_id) is None
            ):
                raise HTTPException(status_code=404, detail="client not found")
            max_version = (await session.execute(
                select(func.max(PromptTemplate.version)).where(
                    PromptTemplate.task_type == payload.task_type,
                    _template_scope_filter(payload.client_id),
                )
            )).scalar()
            row = PromptTemplate(
                task_type=payload.task_type,
                client_id=payload.client_id,
                version=(max_version or 0) + 1,
                name=payload.name,
                system_prompt=payload.system_prompt,
                user_prompt=payload.user_prompt,
                variables=payload.variables,
                is_active=False,
                created_by=_admin.username,
            )
            session.add(row)
            await session.flush()
            if payload.activate:
                await _deactivate_other_templates(
                    session, payload.task_type, payload.client_id, keep_id=row.id
                )
                row.is_active = True
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="concurrent template modification; retry"
        ) from exc
    except OperationalError as exc:
        if not _is_deadlock(exc):
            raise
        raise HTTPException(
            status_code=409, detail="concurrent template modification; retry"
        ) from exc
    return PromptTemplateOut.model_validate(row)


@router.post(
    "/admin/ai/prompt-templates/{template_id}/activate", response_model=PromptTemplateOut
)
async def activate_prompt_template(
    template_id: int,
    _admin: AdminUser,
    db_session: DbSession,
) -> PromptTemplateOut:
    session = _require_db(db_session)
    try:
        async with session.begin():
            row = await session.get(PromptTemplate, template_id)
            if row is None:
                raise HTTPException(status_code=404, detail="prompt template not found")
            await _deactivate_other_templates(
                session, row.task_type, row.client_id, keep_id=row.id
            )
            row.is_active = True
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="concurrent activation; retry"
        ) from exc
    except OperationalError as exc:
        if not _is_deadlock(exc):
            raise
        raise HTTPException(
            status_code=409, detail="concurrent activation; retry"
        ) from exc
    await session.refresh(row)
    return PromptTemplateOut.model_validate(row)


@router.post("/admin/ai/prompt-templates/preview")
async def preview_prompt_template(
    payload: PromptTemplatePreviewRequest,
    _admin: AdminUser,
    db_session: DbSession,
) -> dict[str, Any]:
    session = _require_db(db_session)

    # -- template source: template_id XOR inline draft -----------------------
    has_draft = (
        payload.system_prompt is not None
        or payload.user_prompt is not None
        or payload.variables is not None
    )
    if payload.template_id is not None and has_draft:
        raise HTTPException(
            status_code=422, detail="provide either template_id or an inline draft, not both"
        )
    if payload.task_type not in CANONICAL_VARIABLES:
        raise HTTPException(status_code=422, detail=f"unknown task type {payload.task_type!r}")

    if payload.template_id is not None:
        row = await session.get(PromptTemplate, payload.template_id)
        if row is None:
            raise HTTPException(status_code=404, detail="prompt template not found")
        if row.task_type != payload.task_type:
            raise HTTPException(
                status_code=422,
                detail=f"template {row.id} belongs to task type {row.task_type!r}",
            )
        system_prompt = row.system_prompt
        user_prompt = row.user_prompt
        declared = row.variables
    else:
        # None-check inside the branch lets mypy narrow str | None -> str
        if payload.system_prompt is None or payload.user_prompt is None:
            raise HTTPException(
                status_code=422,
                detail="inline draft requires system_prompt and user_prompt",
            )
        system_prompt = payload.system_prompt
        user_prompt = payload.user_prompt
        declared = payload.variables or []

    # -- product source: inline XOR staging sample ---------------------------
    if payload.product is not None and payload.feed_source_id is not None:
        raise HTTPException(
            status_code=422, detail="provide either product or feed_source_id, not both"
        )
    if payload.product is None and payload.feed_source_id is None:
        raise HTTPException(status_code=422, detail="product or feed_source_id is required")
    if payload.product is not None:
        product = payload.product
    else:
        statement = select(StagingProduct).where(
            StagingProduct.feed_source_id == payload.feed_source_id,
            StagingProduct.status == "active",
            StagingProduct.excluded.is_(False),
        )
        if payload.product_id is not None:
            statement = statement.where(StagingProduct.product_id == payload.product_id)
        statement = statement.order_by(StagingProduct.id).limit(1)
        staged = (await session.execute(statement)).scalar_one_or_none()
        if staged is None:
            raise HTTPException(status_code=404, detail="no sample product found")
        product = staged.raw_data or {}

    # -- validate + lenient render (dry run: no AI call, no usage rows) -------
    canonical = CANONICAL_VARIABLES[payload.task_type]
    validation = validate_template(canonical, system_prompt, user_prompt, declared)
    if validation.errors:
        raise HTTPException(
            status_code=422,
            detail={"errors": validation.errors, "warnings": validation.warnings},
        )
    values = {name: product.get(name) for name in canonical}
    warnings = list(validation.warnings)
    for name in canonical:
        if values[name] is None:
            warnings.append(f"variable {name!r} is missing in the sample product; rendered empty")
    messages = render_messages(system_prompt, user_prompt, values, lenient=True)
    used = parse_placeholders(system_prompt) | parse_placeholders(user_prompt)
    return {
        "messages": messages,
        "used_variables": sorted(used),
        "warnings": warnings,
        "errors": [],
    }
