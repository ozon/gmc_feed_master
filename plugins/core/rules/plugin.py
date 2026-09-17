"""Rules core plugin — row-based data transformation rules."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
_IDENT_RE = re.compile(r"[a-z_][a-z0-9_]*")

STRUCTURED_AI_TASKS: tuple[str, ...] = (
    "title_optimization",
    "description_optimization",
    "category_classification",
    "attribute_enrichment",
)
GENERIC_AI_TASK = "rule_value"

# Local mirror of app/pipeline/enrichment.py::TASK_FIELDS — plugins do not import
# app code. Locked by test_ai_output_fields_mirror_task_fields.
_AI_OUTPUT_FIELDS: dict[str, tuple[str, ...]] = {
    "title_optimization": ("title",),
    "description_optimization": ("description",),
    "category_classification": ("google_product_category",),
    "attribute_enrichment": (
        "color", "size", "material", "gtin", "gender", "age_group",
        "custom_label_0", "custom_label_1", "custom_label_2",
        "custom_label_3", "custom_label_4",
    ),
}


class ConditionError(ValueError):
    """Invalid condition node (unknown op, bad regex, malformed args)."""


_MAX_INDEX = 10_000  # mirrors app/mapping/indexed_path.MAX_INDEX (isolation: local copy)


def _parse_indexed(path: str) -> tuple[str, int | None, str | None]:
    """attr | attr.sub | attr.N | attr.N.sub (N 1-based, <= 10 000).
    Raises ValueError."""
    parts = path.split(".")
    if not parts or not parts[0] or len(parts) > 3:
        raise ValueError(f"invalid path {path!r}")
    attr = parts[0]
    if len(parts) == 1:
        return attr, None, None
    second = parts[1]
    if second.isdigit():
        index = int(second)
        if index < 1:
            raise ValueError(f"invalid index in {path!r}: 1-based")
        if index > _MAX_INDEX:
            raise ValueError(f"invalid index in {path!r}: N must be <= {_MAX_INDEX}")
        sub = parts[2] if len(parts) == 3 else None
        if sub == "":
            raise ValueError(f"invalid path {path!r}")
        return attr, index, sub
    if len(parts) == 3:
        raise ValueError(f"invalid path {path!r}")
    return attr, None, second


def _field_value(product: dict[str, Any], field: str) -> Any:
    try:
        attr, index, sub = _parse_indexed(field)
    except ValueError:
        return None
    value = product.get(attr)
    if index is not None:
        if not isinstance(value, list) or len(value) < index:
            return None
        value = value[index - 1]
        if sub is not None:
            return value.get(sub) if isinstance(value, dict) else None
        return value
    if sub is not None:
        if isinstance(value, dict):
            return value.get(sub)
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
            return value[0].get(sub)
        return None
    return value


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _compile(arg: Any) -> re.Pattern[str]:
    try:
        return re.compile(str(arg))
    except re.error as exc:
        raise ConditionError(f"invalid regex {arg!r}: {exc}") from exc


def _compare_texts(actual: str, expected: str, case_sensitive: bool) -> tuple[str, str]:
    if case_sensitive:
        return actual, expected
    return actual.lower(), expected.lower()


def evaluate_condition(node: dict[str, Any], product: dict[str, Any]) -> bool:
    """Evaluate an IF-AST node against a product. Raises ConditionError on bad shape."""
    if not isinstance(node, dict):
        raise ConditionError("condition node must be an object")
    op = node.get("op")

    if op == "all":
        return True
    if op in ("and", "or"):
        children = node.get("children")
        if not isinstance(children, list) or not children:
            raise ConditionError(f"{op} requires a non-empty children list")
        results = (evaluate_condition(child, product) for child in children)
        return all(results) if op == "and" else any(results)

    if op is None:
        raise ConditionError("condition node is missing op")

    field = node.get("field")
    if not isinstance(field, str) or not field:
        raise ConditionError(f"condition op {op!r} requires a non-empty field")
    value = _field_value(product, field)

    if op == "exists":
        return value is not None
    if op == "empty":
        return value is None or (isinstance(value, str) and value == "")

    if op in ("equals", "contains", "starts_with", "ends_with"):
        arg = node.get("arg")
        if arg is None:
            raise ConditionError(f"condition op {op!r} requires arg")
        case_sensitive = node.get("caseSensitive", True)
        actual, expected = _compare_texts(_as_text(value), _as_text(arg), case_sensitive)
        if op == "equals":
            return actual == expected
        if op == "contains":
            return expected in actual
        if op == "starts_with":
            return actual.startswith(expected)
        return actual.endswith(expected)

    if op == "regex":
        arg = node.get("arg")
        if arg is None:
            raise ConditionError("condition op 'regex' requires arg")
        pattern = _compile(arg)
        return pattern.search(_as_text(value)) is not None

    if op in ("gt", "lt", "gte", "lte", "between"):
        if node.get("arg") is None:
            raise ConditionError(f"condition op {op!r} requires arg")
        number = _as_number(value)
        arg = _as_number(node.get("arg"))
        if number is None or arg is None:
            return False
        if op == "gt":
            return number > arg
        if op == "lt":
            return number < arg
        if op == "gte":
            return number >= arg
        if op == "lte":
            return number <= arg
        arg2 = _as_number(node.get("arg2"))
        if arg2 is None:
            raise ConditionError("condition op 'between' requires arg2")
        return arg <= number <= arg2

    raise ConditionError(f"unknown condition op {op!r}")


# ---------------------------------------------------------------------------
# THEN actions
# ---------------------------------------------------------------------------


class ActionError(ValueError):
    """Invalid action node."""


_ACTION_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "set": ("field", "value"),
    "replace": ("field", "find", "with"),
    "append": ("field", "value"),
    "prepend": ("field", "value"),
    "remove": ("field",),
    "clear": ("field",),
    "ai": (),
}


def _apply_replace(text: str, action: dict[str, Any]) -> str:
    find = str(action["find"])
    with_value = str(action["with"])
    case_sensitive = action.get("caseSensitive", True)
    if find.startswith("/"):
        pattern = find[1:].removesuffix("/")
        escaped = with_value.replace("\\", "\\\\")
        replacement = re.sub(r"\$(\d+)", r"\\\1", escaped)
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            return re.sub(pattern, replacement, text, flags=flags)
        except re.error as exc:
            raise ActionError(f"invalid regex find {find!r}: {exc}") from exc
    if case_sensitive:
        return text.replace(find, with_value)
    return re.sub(re.escape(find), lambda _m: with_value, text, flags=re.IGNORECASE)


def apply_action(product: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """Apply one THEN action; returns a NEW product dict (copy-on-write)."""
    if not isinstance(action, dict):
        raise ActionError("action node must be an object")
    op = action.get("op")
    if op not in _ACTION_REQUIRED_KEYS:
        raise ActionError(f"unknown action op {op!r}")
    if op == "ai":
        return dict(product)
    field = action.get("field")
    if not isinstance(field, str) or not field:
        raise ActionError(f"action op {op!r} requires a non-empty field")

    try:
        attr, index, sub = _parse_indexed(field)
    except ValueError as exc:
        raise ActionError(f"invalid field path {field!r}: {exc}") from exc

    if index is not None:
        return _apply_indexed_action(product, attr, index, sub, action, op)

    next_product: dict[str, Any] = dict(product)

    if op == "set":
        next_product[field] = action.get("value")
    elif op in ("append", "prepend"):
        value = action.get("value")
        current = next_product.get(field)
        text = "" if current is None else str(current)
        addition = "" if value is None else str(value)
        next_product[field] = addition + text if op == "prepend" else text + addition
    elif op == "replace":
        current = next_product.get(field)
        text = "" if current is None else str(current)
        next_product[field] = _apply_replace(text, action)
    elif op == "remove":
        next_product.pop(field, None)
    elif op == "clear":
        next_product[field] = ""

    return next_product


def _apply_indexed_action(
    product: dict[str, Any],
    attr: str,
    index: int,
    sub: str | None,
    action: dict[str, Any],
    op: str,
) -> dict[str, Any]:
    """Index-addressed THEN action (copy-on-write). Index is 1-based."""
    next_product = dict(product)
    idx0 = index - 1
    current = next_product.get(attr)

    if sub is None:
        if op in ("set", "append", "prepend", "replace"):
            bucket = list(current) if isinstance(current, list) else []
            while len(bucket) <= idx0:
                bucket.append("")
            if op == "set":
                text = "" if action.get("value") is None else str(action["value"])
            elif op in ("append", "prepend"):
                existing = "" if bucket[idx0] is None else str(bucket[idx0])
                addition = "" if action.get("value") is None else str(action["value"])
                text = addition + existing if op == "prepend" else existing + addition
            else:  # replace
                text = "" if bucket[idx0] is None else str(bucket[idx0])
                text = _apply_replace(text, action)
            bucket[idx0] = text
            next_product[attr] = bucket
            return next_product
        if op == "remove":
            if isinstance(current, list) and len(current) > idx0:
                bucket = list(current)
                bucket.pop(idx0)
                next_product[attr] = bucket
            return next_product
        if op == "clear":
            if isinstance(current, list) and len(current) > idx0:
                bucket = list(current)
                bucket[idx0] = ""
                next_product[attr] = bucket
            return next_product
        raise ActionError(f"unknown action op {op!r}")

    bucket = [
        dict(elem) if isinstance(elem, dict) else elem
        for elem in (current if isinstance(current, list) else [])
    ]
    while len(bucket) <= idx0:
        bucket.append({})
    element = bucket[idx0]
    if not isinstance(element, dict):
        raise ActionError(f"cannot address sub-field on non-object element of {attr!r}")
    if op == "set":
        element[sub] = action.get("value")
    elif op in ("append", "prepend"):
        existing = "" if element.get(sub) is None else str(element.get(sub))
        addition = "" if action.get("value") is None else str(action["value"])
        element[sub] = addition + existing if op == "prepend" else existing + addition
    elif op == "replace":
        text = "" if element.get(sub) is None else str(element.get(sub))
        element[sub] = _apply_replace(text, action)
    elif op == "remove":
        element.pop(sub, None)
    elif op == "clear":
        element[sub] = ""
    else:
        raise ActionError(f"unknown action op {op!r}")
    bucket[idx0] = element
    next_product[attr] = bucket
    return next_product


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def _ai_output_fields(action: dict[str, Any]) -> tuple[str, ...]:
    if action.get("promptSource") == "custom":
        field = action.get("field")
        return (field,) if isinstance(field, str) and field else ()
    return _AI_OUTPUT_FIELDS.get(str(action.get("taskType")), ())


def _validate_ai_action(action: dict[str, Any], path: str) -> None:
    source = action.get("promptSource")
    if source not in ("template", "custom"):
        raise ValueError(f"{path}: op 'ai' requires promptSource 'template' or 'custom'")
    if source == "template":
        if action.get("taskType") not in STRUCTURED_AI_TASKS:
            raise ValueError(
                f"{path}: op 'ai' template requires taskType in {STRUCTURED_AI_TASKS}"
            )
        template_id = action.get("templateId")
        if isinstance(template_id, bool) or not isinstance(template_id, int):
            raise ValueError(f"{path}: op 'ai' template requires an integer templateId")
        return
    if action.get("taskType") != GENERIC_AI_TASK:
        raise ValueError(
            f"{path}: op 'ai' custom requires taskType {GENERIC_AI_TASK!r}"
        )
    for key in ("system", "user"):
        if not isinstance(action.get(key), str) or not action.get(key):
            raise ValueError(f"{path}: op 'ai' custom requires a non-empty {key}")
    variables = action.get("variables")
    if (
        not isinstance(variables, list)
        or not variables
        or not all(isinstance(v, str) and v for v in variables)
    ):
        raise ValueError(f"{path}: op 'ai' custom requires a non-empty variables list")
    declared = set(variables)
    for name in variables:
        if _IDENT_RE.fullmatch(name) is None:
            raise ValueError(
                f"{path}: op 'ai' variable {name!r} must be a lowercase identifier"
            )
    used = _PLACEHOLDER_RE.findall(action["system"]) + _PLACEHOLDER_RE.findall(action["user"])
    for name in used:
        if name not in declared:
            raise ValueError(
                f"{path}: op 'ai' placeholder {{{{{name}}}}} is not declared in variables"
            )
    if not isinstance(action.get("field"), str) or not action.get("field"):
        raise ValueError(f"{path}: op 'ai' custom requires a non-empty field")


def _pending_entry(product: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_id": str(product.get("id", "")),
        "field": action.get("field") or "",
        "taskType": action.get("taskType"),
        "promptSource": action.get("promptSource"),
        "templateId": action.get("templateId"),
        "system": action.get("system"),
        "user": action.get("user"),
        "variables": list(action.get("variables") or []),
    }


def _validate_condition(node: Any, path: str) -> None:
    if not isinstance(node, dict):
        raise TypeError(f"{path}: condition must be an object")
    op = node.get("op")
    if op == "all":
        return
    if op in ("and", "or"):
        children = node.get("children")
        if not isinstance(children, list) or not children:
            raise ValueError(f"{path}: {op} requires a non-empty children list")
        for index, child in enumerate(children):
            _validate_condition(child, f"{path}.children[{index}]")
        return
    if op == "exists" or op == "empty":
        field = node.get("field")
        if not isinstance(field, str) or not field:
            raise ValueError(f"{path}: op {op!r} requires a non-empty field")
        return
    if op in ("equals", "contains", "starts_with", "ends_with", "regex"):
        if not isinstance(node.get("field"), str) or not node.get("field"):
            raise ValueError(f"{path}: op {op!r} requires a non-empty field")
        if node.get("arg") is None:
            raise ValueError(f"{path}: op {op!r} requires arg")
        if op == "regex":
            _compile(node["arg"])
        return
    if op in ("gt", "lt", "gte", "lte"):
        if not isinstance(node.get("field"), str) or not node.get("field"):
            raise ValueError(f"{path}: op {op!r} requires a non-empty field")
        if _as_number(node.get("arg")) is None:
            raise ValueError(f"{path}: op {op!r} requires a numeric arg")
        return
    if op == "between":
        if not isinstance(node.get("field"), str) or not node.get("field"):
            raise ValueError(f"{path}: op 'between' requires a non-empty field")
        if _as_number(node.get("arg")) is None or _as_number(node.get("arg2")) is None:
            raise ValueError(f"{path}: op 'between' requires numeric arg and arg2")
        return
    raise ValueError(f"{path}: unknown condition op {op!r}")


def validate_config(config: Any) -> None:
    """Strict validation of a rules config document."""
    if not isinstance(config, dict):
        raise TypeError("config must be an object")
    if not config:
        return  # empty config = no rules
    rules = config.get("rules")
    if rules is None:
        return
    if not isinstance(rules, list):
        raise TypeError("config.rules must be an array")
    for index, rule in enumerate(rules):
        path = f"rules[{index}]"
        if not isinstance(rule, dict):
            raise TypeError(f"{path}: rule must be an object")
        if not isinstance(rule.get("id"), str) or not rule.get("id"):
            raise ValueError(f"{path}: id must be a non-empty string")
        if not isinstance(rule.get("name"), str) or not rule.get("name"):
            raise ValueError(f"{path}: name must be a non-empty string")
        _validate_condition(rule.get("when"), f"{path}.when")
        then = rule.get("then")
        if not isinstance(then, list):
            raise TypeError(f"{path}.then must be an array")
        ai_outputs: set[str] = set()
        for action_index, action in enumerate(then):
            action_path = f"{path}.then[{action_index}]"
            op = action.get("op") if isinstance(action, dict) else None
            if op == "ai":
                _validate_ai_action(action, action_path)
                ai_outputs.update(_ai_output_fields(action))
                continue
            if op not in _ACTION_REQUIRED_KEYS:
                raise ValueError(f"{action_path}: unknown action op {op!r}")
            for key in _ACTION_REQUIRED_KEYS[op]:
                if key != "field" and action.get(key) is None:
                    raise ValueError(f"{action_path}: op {op!r} requires {key}")
            if not isinstance(action.get("field"), str) or not action.get("field"):
                raise ValueError(f"{action_path}: op {op!r} requires a non-empty field")
            if action["field"] in ai_outputs:
                raise ValueError(
                    f"{action_path}: field {action['field']!r} is written by a "
                    f"preceding 'ai' action; an 'ai' action must be the last write "
                    f"to its field"
                )
            try:
                _parse_indexed(action["field"])
            except ValueError as exc:
                raise ValueError(f"{action_path}: {exc}") from exc
            if op == "replace" and action.get("find") == "":
                raise ValueError(f"{action_path}: op 'replace' requires a non-empty find")


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class RulesPlugin:
    """Pipeline module executing ordered row-based rules."""

    def validate_config(self, config: dict[str, Any]) -> None:
        validate_config(config)

    def process(
        self,
        product: dict[str, Any],
        config: dict[str, Any],
        data: dict[str, Any],
        ctx: Any,
    ) -> dict[str, Any] | None:
        rules = config.get("rules", []) if isinstance(config, dict) else []
        current = product
        for rule in rules:
            if not isinstance(rule, dict) or not rule.get("isActive", True):
                continue
            if not evaluate_condition(rule.get("when", {"op": "all"}), current):
                continue
            for action in rule.get("then", []):
                if isinstance(action, dict) and action.get("op") == "ai":
                    pending = getattr(getattr(ctx, "run_state", None), "rule_ai_pending", None)
                    if pending is None:
                        logger.warning(
                            "rules: ai action on product %s dropped (no run_state)",
                            product.get("id"),
                        )
                    else:
                        pending.append(_pending_entry(current, action))
                    continue
                current = apply_action(current, action)
        return current

    def register_routes(self, router: Any) -> None:
        from fastapi import Depends, HTTPException, Query
        from pydantic import BaseModel
        from sqlalchemy import or_, select

        from app.access import CurrentUser, ensure_feed_source_access, get_current_user
        from app.ai.tasks import CANONICAL_VARIABLES
        from app.ai.templates import (
            parse_placeholders,
            render_messages,
            validate_template,
        )
        from app.db.engine import get_db_session
        from app.models.ai import PromptTemplate
        from app.models.feed_source import FeedSource
        from app.models.staging import StagingProduct

        class PreviewRequest(BaseModel):
            feed_source_id: int
            taskType: str
            templateId: int | None = None
            system: str | None = None
            user: str | None = None
            variables: list[str] | None = None
            product_id: str | None = None

        async def ai_templates(
            feed_source_id: int = Query(...),
            task_type: str = Query(...),
            user: CurrentUser = Depends(get_current_user),
            db_session: Any = Depends(get_db_session),
        ) -> dict[str, Any]:
            if db_session is None:
                raise HTTPException(status_code=503, detail="database unavailable")
            await ensure_feed_source_access(db_session, user, feed_source_id)
            if task_type not in CANONICAL_VARIABLES:
                raise HTTPException(status_code=422, detail=f"unknown task type {task_type!r}")
            async with db_session.begin():
                feed = await db_session.get(FeedSource, feed_source_id)
                if feed is None:
                    raise HTTPException(status_code=404, detail="feed source not found")
                statement = select(PromptTemplate).where(
                    PromptTemplate.task_type == task_type
                )
                if feed.client_id is not None:
                    statement = statement.where(or_(
                        PromptTemplate.client_id.is_(None),
                        PromptTemplate.client_id == feed.client_id,
                    ))
                else:
                    statement = statement.where(PromptTemplate.client_id.is_(None))
                statement = statement.order_by(PromptTemplate.version.desc())
                rows = (await db_session.execute(statement)).scalars().all()
            return {"items": [
                {"id": r.id, "name": r.name, "task_type": r.task_type,
                 "client_id": r.client_id, "version": r.version, "is_active": r.is_active}
                for r in rows
            ]}

        async def ai_preview(
            payload: PreviewRequest,
            user: CurrentUser = Depends(get_current_user),
            db_session: Any = Depends(get_db_session),
        ) -> dict[str, Any]:
            if db_session is None:
                raise HTTPException(status_code=503, detail="database unavailable")
            await ensure_feed_source_access(db_session, user, payload.feed_source_id)
            has_draft = (
                payload.system is not None
                or payload.user is not None
                or payload.variables is not None
            )
            if payload.templateId is not None and has_draft:
                raise HTTPException(
                    status_code=422, detail="provide either templateId or an inline draft"
                )
            if payload.templateId is None and not (
                payload.system is not None and payload.user is not None
            ):
                raise HTTPException(
                    status_code=422, detail="inline draft requires system and user"
                )
            async with db_session.begin():
                feed = await db_session.get(FeedSource, payload.feed_source_id)
                if feed is None:
                    raise HTTPException(status_code=404, detail="feed source not found")
                if payload.templateId is not None:
                    if payload.taskType not in CANONICAL_VARIABLES:
                        raise HTTPException(
                            status_code=422,
                            detail=f"unknown task type {payload.taskType!r}",
                        )
                    row = await db_session.get(PromptTemplate, payload.templateId)
                    if row is None or row.task_type != payload.taskType:
                        raise HTTPException(status_code=422, detail="template not usable")
                    if row.client_id is not None and row.client_id != feed.client_id:
                        raise HTTPException(status_code=422, detail="template not usable")
                    system = row.system_prompt
                    user_prompt = row.user_prompt
                    declared = list(row.variables)
                    canonical = list(CANONICAL_VARIABLES[payload.taskType])
                else:
                    if payload.taskType != GENERIC_AI_TASK:
                        raise HTTPException(
                            status_code=422,
                            detail="inline draft requires taskType 'rule_value'",
                        )
                    system = payload.system or ""
                    user_prompt = payload.user or ""
                    declared = list(payload.variables or [])
                    canonical = list(declared)
                statement = select(StagingProduct).where(
                    StagingProduct.feed_source_id == payload.feed_source_id,
                    StagingProduct.status == "active",
                    StagingProduct.excluded.is_(False),
                )
                if payload.product_id is not None:
                    statement = statement.where(
                        StagingProduct.product_id == payload.product_id
                    )
                statement = statement.order_by(StagingProduct.id).limit(1)
                staged = (await db_session.execute(statement)).scalar_one_or_none()
                if staged is None:
                    raise HTTPException(status_code=404, detail="no sample product found")
                product = staged.raw_data or {}

            validation = validate_template(canonical, system, user_prompt, declared)
            if validation.errors:
                raise HTTPException(status_code=422, detail={
                    "errors": validation.errors, "warnings": validation.warnings,
                })
            values = {name: product.get(name) for name in canonical}
            warnings = list(validation.warnings)
            for name in canonical:
                if values[name] is None:
                    warnings.append(
                        f"variable {name!r} is missing in the sample product; rendered empty"
                    )
            messages = render_messages(system, user_prompt, values, lenient=True)
            used = sorted(parse_placeholders(system) | parse_placeholders(user_prompt))
            return {"messages": messages, "used_variables": used,
                    "warnings": warnings, "errors": []}

        ai_templates.__annotations__.update({
            "feed_source_id": int, "task_type": str, "user": CurrentUser,
            "return": dict[str, Any],
        })
        router.get("/ai/templates", response_model=None)(ai_templates)

        # `from __future__ import annotations` (module level) turns the local
        # PreviewRequest annotation into a string; FastAPI's eval_str cannot see
        # function locals, so the body model would silently degrade to a query
        # param. Resolve it explicitly (same pattern as CategoryPlugin).
        ai_preview.__annotations__.update({
            "payload": PreviewRequest, "user": CurrentUser,
            "return": dict[str, Any],
        })
        router.post("/ai/preview", response_model=None)(ai_preview)
