from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..ai.tasks import CANONICAL_VARIABLES
from .enrichment import TASK_FIELDS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuleAiOutcome:
    products: int
    applied: int
    failed: int
    spent: int


async def _run_entry(
    ai_service: Any,
    entry: dict[str, Any],
    product: dict[str, Any],
    client_id: int | None,
    feed_source_id: int | None,
) -> tuple[dict[str, Any], str]:
    if entry.get("promptSource") == "template":
        task_type = str(entry.get("taskType"))
        variables = {
            name: product.get(name) for name in CANONICAL_VARIABLES.get(task_type, [])
        }
        result = await ai_service.run_task(
            task_type, variables, client_id=client_id,
            feed_source_id=feed_source_id, template_id=entry.get("templateId"),
        )
    else:
        variables = {
            name: product.get(name) for name in (entry.get("variables") or [])
        }
        result = await ai_service.run_inline_task(
            entry.get("system") or "", entry.get("user") or "", variables,
            client_id=client_id, feed_source_id=feed_source_id,
        )
    if result.value is None:
        return {}, result.status
    if entry.get("promptSource") == "template":
        task_type = str(entry.get("taskType"))
        dumped = result.value.model_dump() if hasattr(result.value, "model_dump") else {}
        updates = {
            field: str(dumped[field])
            for field in TASK_FIELDS.get(task_type, ())
            if dumped.get(field) not in (None, "")
        }
        return updates, result.status
    value = getattr(result.value, "value", None)
    field = entry.get("field")
    if value in (None, "") or not field:
        return {}, result.status
    return {str(field): str(value)}, result.status


async def apply_rule_ai_actions(
    *,
    ai_service: Any,
    products: list[dict[str, Any]],
    pending: list[dict[str, Any]],
    limit: int,
    budget: int,
    client_id: int | None,
    feed_source_id: int | None,
) -> tuple[dict[str, dict[str, Any]], RuleAiOutcome]:
    if ai_service is None:
        return {}, RuleAiOutcome(products=0, applied=0, failed=0, spent=0)

    by_id = {str(p.get("id", "")): p for p in products if p.get("id") is not None}
    order: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in pending:
        pid = entry.get("product_id")
        if not isinstance(pid, str) or pid not in by_id:
            continue
        if pid not in grouped:
            order.append(pid)
            grouped[pid] = []
        grouped[pid].append(entry)

    changed: dict[str, dict[str, Any]] = {}
    touched = applied = failed = spent = 0
    for pid in order:
        if touched >= limit or spent >= budget:
            break
        current = by_id[pid]
        product_changed = False
        for entry in grouped[pid]:
            if spent >= budget:
                break
            try:
                updates, status = await _run_entry(
                    ai_service, entry, current, client_id, feed_source_id
                )
            except Exception:
                logger.warning("rule_ai: entry failed for product %s", pid, exc_info=True)
                failed += 1
                continue
            if status == "fallback":
                failed += 1
                continue
            if status == "ok":
                spent += 1
            if updates:
                current = {**current, **updates}
                product_changed = True
                applied += 1
        touched += 1
        if product_changed:
            changed[pid] = current
    return changed, RuleAiOutcome(
        products=touched, applied=applied, failed=failed, spent=spent
    )
