"""Condition-AST evaluation tests for the rules core plugin."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins/core/rules"))
from plugin import evaluate_condition  # noqa: E402


def test_all_matches_everything():
    assert evaluate_condition({"op": "all"}, {"id": "1"}) is True
    assert evaluate_condition({"op": "all"}, {}) is True


def test_equals_default_case_sensitive():
    node = {"op": "equals", "field": "title", "arg": "Hello"}
    assert evaluate_condition(node, {"title": "Hello"}) is True
    assert evaluate_condition(node, {"title": "hello"}) is False


def test_equals_case_insensitive():
    node = {"op": "equals", "field": "title", "arg": "hello", "caseSensitive": False}
    assert evaluate_condition(node, {"title": "HeLLo"}) is True


def test_contains():
    node = {"op": "contains", "field": "description", "arg": "<p>"}
    assert evaluate_condition(node, {"description": "a <p> b"}) is True
    assert evaluate_condition(node, {"description": "a b"}) is False


def test_contains_case_insensitive():
    node = {"op": "contains", "field": "title", "arg": "sale", "caseSensitive": False}
    assert evaluate_condition(node, {"title": "Big SALE today"}) is True


def test_starts_with_and_ends_with():
    assert evaluate_condition({"op": "starts_with", "field": "id", "arg": "SKU"}, {"id": "SKU-1"}) is True
    assert evaluate_condition({"op": "ends_with", "field": "id", "arg": "-1"}, {"id": "SKU-1"}) is True
    assert evaluate_condition({"op": "starts_with", "field": "id", "arg": "sku", "caseSensitive": False}, {"id": "SKU-1"}) is True


def test_regex_match():
    node = {"op": "regex", "field": "link", "arg": r"^https?://"}
    assert evaluate_condition(node, {"link": "https://x.y"}) is True
    assert evaluate_condition(node, {"link": "ftp://x.y"}) is False


def test_invalid_regex_raises_condition_error():
    from plugin import ConditionError

    with pytest.raises(ConditionError):
        evaluate_condition({"op": "regex", "field": "link", "arg": "("}, {"link": "x"})


def test_exists_and_empty():
    assert evaluate_condition({"op": "exists", "field": "title"}, {"title": "x"}) is True
    assert evaluate_condition({"op": "exists", "field": "title"}, {"title": None}) is False
    assert evaluate_condition({"op": "exists", "field": "title"}, {}) is False
    assert evaluate_condition({"op": "empty", "field": "title"}, {}) is True
    assert evaluate_condition({"op": "empty", "field": "title"}, {"title": ""}) is True
    assert evaluate_condition({"op": "empty", "field": "title"}, {"title": None}) is True
    assert evaluate_condition({"op": "empty", "field": "title"}, {"title": "x"}) is False


def test_numeric_comparisons():
    assert evaluate_condition({"op": "gt", "field": "price", "arg": 10}, {"price": 10.5}) is True
    assert evaluate_condition({"op": "gt", "field": "price", "arg": 10}, {"price": 10}) is False
    assert evaluate_condition({"op": "gte", "field": "price", "arg": 10}, {"price": 10}) is True
    assert evaluate_condition({"op": "lt", "field": "price", "arg": 10}, {"price": 9}) is True
    assert evaluate_condition({"op": "lte", "field": "price", "arg": 10}, {"price": 10}) is True
    assert evaluate_condition({"op": "between", "field": "price", "arg": 5, "arg2": 10}, {"price": 7}) is True
    assert evaluate_condition({"op": "between", "field": "price", "arg": 5, "arg2": 10}, {"price": 5}) is True
    assert evaluate_condition({"op": "between", "field": "price", "arg": 5, "arg2": 10}, {"price": 11}) is False


def test_numeric_on_non_numeric_value_is_false():
    assert evaluate_condition({"op": "gt", "field": "price", "arg": 10}, {"price": "cheap"}) is False
    assert evaluate_condition({"op": "between", "field": "price", "arg": 1, "arg2": 2}, {}) is False


def test_numeric_on_string_digits_coerces():
    assert evaluate_condition({"op": "gt", "field": "price", "arg": 10}, {"price": "15"}) is True


def test_and_or_groups():
    cond = {
        "op": "and",
        "children": [
            {"op": "equals", "field": "brand", "arg": "Acme"},
            {"op": "gt", "field": "price", "arg": 5},
        ],
    }
    assert evaluate_condition(cond, {"brand": "Acme", "price": 7}) is True
    assert evaluate_condition(cond, {"brand": "Acme", "price": 3}) is False
    either = {
        "op": "or",
        "children": [
            {"op": "equals", "field": "brand", "arg": "Acme"},
            {"op": "equals", "field": "brand", "arg": "Globex"},
        ],
    }
    assert evaluate_condition(either, {"brand": "Globex"}) is True
    assert evaluate_condition(either, {"brand": "Initech"}) is False


def test_text_ops_coerce_non_string_values():
    node = {"op": "contains", "field": "price", "arg": "9"}
    assert evaluate_condition(node, {"price": 19.99}) is True
    assert evaluate_condition(node, {"price": 20.0}) is False


def test_unknown_op_raises():
    from plugin import ConditionError

    with pytest.raises(ConditionError):
        evaluate_condition({"op": "nope", "field": "x"}, {"x": "1"})
