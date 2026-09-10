from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from registry.loader import load_registry

from ..auth import require_user
from ..db.engine import get_db_session
from ..models.feed_source import FeedSource
from ..models.staging import StagingProduct
from ..qc.constants import BASELINE_ALTERNATIVE_PAIRS, BASELINE_REQUIRED
from ..schemas.field_mapping import RegistryAttributeOut, RegistrySubFieldOut

router = APIRouter()


def _attribute_sub_kind(parent_kind: str) -> str | None:
    """Sub-field effective kind, mirroring matcher._SUB_EFFECTIVE_KINDS."""
    if parent_kind == "structured":
        return "scalar"
    if parent_kind == "repeated_structured":
        return "repeated_scalar"
    return None


async def _require_feed_source(session: AsyncSession, feed_source_id: int) -> None:
    if await session.get(FeedSource, feed_source_id) is None:
        raise HTTPException(status_code=404, detail="feed source not found")


async def compute_max_repeats(
    session: AsyncSession, feed_source_id: int
) -> dict[str, int]:
    """Max observed list length per attribute (operator directive 1).

    Streams only the two JSON columns with yield_per -- never full model
    instances. processed_data falls back to raw_data when null (QC precedent).
    """
    result: dict[str, int] = {}
    stmt = (
        select(StagingProduct.processed_data, StagingProduct.raw_data)
        .where(StagingProduct.feed_source_id == feed_source_id)
        .execution_options(yield_per=1000)
    )
    stream = await session.stream(stmt)
    async for processed_data, raw_data in stream:
        product = processed_data if processed_data is not None else (raw_data or {})
        if not isinstance(product, dict):
            continue
        for key, value in product.items():
            if isinstance(value, list) and value:
                result[key] = max(result.get(key, 0), len(value))
    return result


@router.get("/registry/attributes", response_model=list[RegistryAttributeOut])
async def list_registry_attributes(
    feed_source_id: int | None = None,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> list[RegistryAttributeOut]:
    registry = load_registry()
    baseline_names = set(BASELINE_REQUIRED)
    for pair in BASELINE_ALTERNATIVE_PAIRS:
        baseline_names.update(pair)

    observed: dict[str, int] = {}
    if feed_source_id is not None:
        if db_session is None:
            raise HTTPException(status_code=503, detail="database unavailable")
        async with db_session.begin():
            await _require_feed_source(db_session, feed_source_id)
            observed = await compute_max_repeats(db_session, feed_source_id)

    attributes: list[RegistryAttributeOut] = []
    for attribute in sorted(registry.attributes.values(), key=lambda attr: attr.name):
        kind = attribute.kind.value
        if kind in ("repeated_scalar", "repeated_structured"):
            max_repeats = observed.get(attribute.name, 0)
        else:
            max_repeats = 1
        attributes.append(
            RegistryAttributeOut(
                name=attribute.name,
                kind=kind,
                required=attribute.required.value,
                baseline_required=attribute.name in baseline_names,
                sub_fields=[
                    RegistrySubFieldOut(
                        name=sub.name,
                        type=sub.type,
                        required=sub.required.value,
                        kind=_attribute_sub_kind(kind),
                    )
                    for sub in attribute.fields
                ],
                enum_values=list(attribute.enum_values),
                max_repeats=max_repeats,
            )
        )
    return attributes
