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
