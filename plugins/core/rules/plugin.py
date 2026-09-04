"""Rules core plugin — row-based data transformation rules."""

from __future__ import annotations

import re
from typing import Any


class ConditionError(ValueError):
    """Invalid condition node (unknown op, bad regex, malformed args)."""


def _field_value(product: dict[str, Any], field: str) -> Any:
    return product.get(field)


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
}


def _apply_replace(text: str, action: dict[str, Any]) -> str:
    find = str(action["find"])
    with_value = str(action["with"])
    case_sensitive = action.get("caseSensitive", True)
    if find.startswith("/"):
        pattern = find[1:].removesuffix("/")
        replacement = re.sub(r"\$(\d+)", r"\\\1", with_value)
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            return re.sub(pattern, replacement, text, flags=flags)
        except re.error as exc:
            raise ActionError(f"invalid regex find {find!r}: {exc}") from exc
    if case_sensitive:
        return text.replace(find, with_value)
    return re.sub(re.escape(find), with_value, text, flags=re.IGNORECASE)


def apply_action(product: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """Apply one THEN action; returns a NEW product dict (copy-on-write)."""
    if not isinstance(action, dict):
        raise ActionError("action node must be an object")
    op = action.get("op")
    if op not in _ACTION_REQUIRED_KEYS:
        raise ActionError(f"unknown action op {op!r}")
    field = action.get("field")
    if not isinstance(field, str) or not field:
        raise ActionError(f"action op {op!r} requires a non-empty field")

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


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def _validate_condition(node: Any, path: str) -> None:
    if not isinstance(node, dict):
        raise ValueError(f"{path}: condition must be an object")
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
        raise ValueError("config must be an object")
    if not config:
        return  # empty config = no rules
    rules = config.get("rules")
    if rules is None:
        return
    if not isinstance(rules, list):
        raise ValueError("config.rules must be an array")
    for index, rule in enumerate(rules):
        path = f"rules[{index}]"
        if not isinstance(rule, dict):
            raise ValueError(f"{path}: rule must be an object")
        if not isinstance(rule.get("id"), str) or not rule.get("id"):
            raise ValueError(f"{path}: id must be a non-empty string")
        if not isinstance(rule.get("name"), str) or not rule.get("name"):
            raise ValueError(f"{path}: name must be a non-empty string")
        _validate_condition(rule.get("when"), f"{path}.when")
        then = rule.get("then")
        if not isinstance(then, list):
            raise ValueError(f"{path}.then must be an array")
        for action_index, action in enumerate(then):
            action_path = f"{path}.then[{action_index}]"
            op = action.get("op") if isinstance(action, dict) else None
            if op not in _ACTION_REQUIRED_KEYS:
                raise ValueError(f"{action_path}: unknown action op {op!r}")
            for key in _ACTION_REQUIRED_KEYS[op]:
                if key != "field" and action.get(key) is None:
                    raise ValueError(f"{action_path}: op {op!r} requires {key}")
            if not isinstance(action.get("field"), str) or not action.get("field"):
                raise ValueError(f"{action_path}: op {op!r} requires a non-empty field")


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
                current = apply_action(current, action)
        return current
