"""Filter core plugin — conjunctive scalar condition product filter."""

from __future__ import annotations

from typing import Any

_ALLOWED_OPS = ("equals", "not_equals", "contains", "not_contains", "exists", "empty")
_TEXT_OPS = ("equals", "not_equals", "contains", "not_contains")


class FilterError(ValueError):
    """Invalid filter condition (unknown op, missing field, malformed args)."""


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _texts(value: Any, arg: Any, case_sensitive: bool) -> tuple[str, str]:
    actual, expected = _as_text(value), _as_text(arg)
    if case_sensitive:
        return actual, expected
    return actual.lower(), expected.lower()


def evaluate_condition(condition: dict[str, Any], product: dict[str, Any]) -> bool:
    """Evaluate one condition against a product. Raises FilterError on bad shape."""
    if not isinstance(condition, dict):
        raise FilterError("filter condition must be an object")
    op = condition.get("op")
    if op not in _ALLOWED_OPS:
        raise FilterError(f"unknown filter op {op!r}")
    field = condition.get("field")
    if not isinstance(field, str) or not field:
        raise FilterError(f"filter op {op!r} requires a non-empty field")
    value = product.get(field)

    if op == "exists":
        return value is not None
    if op == "empty":
        return value is None or (isinstance(value, str) and value == "")

    arg = condition.get("arg")
    if arg is None:
        raise FilterError(f"filter op {op!r} requires arg")
    case_sensitive = condition.get("caseSensitive", True)

    if op == "equals":
        actual, expected = _texts(value, arg, case_sensitive)
        return actual == expected
    if op == "not_equals":
        if value is None:
            return True
        actual, expected = _texts(value, arg, case_sensitive)
        return actual != expected
    if op == "contains":
        actual, expected = _texts(value, arg, case_sensitive)
        return expected in actual
    # not_contains
    if value is None:
        return True
    actual, expected = _texts(value, arg, case_sensitive)
    return expected not in actual


def passes_all(conditions: list[dict[str, Any]], product: dict[str, Any]) -> bool:
    """Conjunctive evaluation; empty condition list passes."""
    return all(evaluate_condition(c, product) for c in conditions)


def _validate_condition(condition: Any, index: int) -> None:
    if not isinstance(condition, dict):
        raise ValueError(f"conditions[{index}]: condition must be an object")
    op = condition.get("op")
    if op not in _ALLOWED_OPS:
        raise ValueError(f"conditions[{index}]: unknown filter op {op!r}")
    field = condition.get("field")
    if not isinstance(field, str) or not field:
        raise ValueError(f"conditions[{index}]: op {op!r} requires a non-empty field")
    if op in _TEXT_OPS:
        if condition.get("arg") is None:
            raise ValueError(f"conditions[{index}]: op {op!r} requires arg")
    else:
        if condition.get("arg") is not None:
            raise ValueError(f"conditions[{index}]: op {op!r} does not take arg")


def validate_config(config: Any) -> None:
    """Strict validation of a filter config document. Empty config passes."""
    if config is None:
        return
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    if not config:
        return
    conditions = config.get("conditions")
    if conditions is None:
        return
    if not isinstance(conditions, list):
        raise ValueError("config.conditions must be an array")
    for index, condition in enumerate(conditions):
        _validate_condition(condition, index)


class FilterPlugin:
    """Pipeline module dropping products that fail the conjunctive condition set."""

    def validate_config(self, config: dict[str, Any]) -> None:
        validate_config(config)

    def process(
        self,
        product: dict[str, Any],
        config: dict[str, Any],
        data: dict[str, Any] | None = None,
        ctx: Any = None,
    ) -> dict[str, Any] | None:
        conditions = config.get("conditions", []) if isinstance(config, dict) else []
        if not config.get("isActive", True):
            return product
        if passes_all(conditions, product):
            return product
        return None
