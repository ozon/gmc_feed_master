"""FilterPlugin engine tests: condition ops, validation, process contract."""

import copy
import importlib.util
import logging
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "filter_plugin",
    Path(__file__).resolve().parents[2] / "plugins/core/filter/plugin.py",
)
assert _spec is not None and _spec.loader is not None
_filter_module = importlib.util.module_from_spec(_spec)
sys.modules["filter_plugin"] = _filter_module
_spec.loader.exec_module(_filter_module)

FilterError = _filter_module.FilterError
FilterPlugin = _filter_module.FilterPlugin
evaluate_condition = _filter_module.evaluate_condition
passes_all = _filter_module.passes_all
validate_config = _filter_module.validate_config


def _ctx():
    class _Ctx:
        client_id = 0
        feed_source_id = 0
        run_id = 0
        logger = logging.getLogger("test")

    return _Ctx()


# --- evaluate_condition: text ops ---

def test_equals_case_sensitive_default():
    node = {"field": "brand", "op": "equals", "arg": "Acme"}
    assert evaluate_condition(node, {"brand": "Acme"}) is True
    assert evaluate_condition(node, {"brand": "acme"}) is False


def test_equals_case_insensitive():
    node = {"field": "brand", "op": "equals", "arg": "acme", "caseSensitive": False}
    assert evaluate_condition(node, {"brand": "ACME"}) is True


def test_not_equals_is_inverse_on_present_values():
    node = {"field": "brand", "op": "not_equals", "arg": "Acme"}
    assert evaluate_condition(node, {"brand": "Globex"}) is True
    assert evaluate_condition(node, {"brand": "Acme"}) is False


def test_not_equals_true_when_field_missing():
    node = {"field": "brand", "op": "not_equals", "arg": "Acme"}
    assert evaluate_condition(node, {}) is True


def test_contains_and_not_contains():
    has = {"field": "description", "op": "contains", "arg": "refurb"}
    assert evaluate_condition(has, {"description": "used refurbished item"}) is True
    assert evaluate_condition(has, {"description": "brand new"}) is False
    not_has = {"field": "description", "op": "not_contains", "arg": "refurb"}
    assert evaluate_condition(not_has, {"description": "brand new"}) is True
    assert evaluate_condition(not_has, {"description": "refurbished"}) is False


def test_not_contains_true_when_field_missing():
    node = {"field": "description", "op": "not_contains", "arg": "refurb"}
    assert evaluate_condition(node, {}) is True


def test_contains_case_insensitive():
    node = {"field": "title", "op": "contains", "arg": "sale", "caseSensitive": False}
    assert evaluate_condition(node, {"title": "BIG SALE today"}) is True


def test_text_ops_coerce_non_strings():
    node = {"field": "price", "op": "contains", "arg": "9"}
    assert evaluate_condition(node, {"price": 19.99}) is True


# --- evaluate_condition: exists / empty ---

def test_exists():
    node = {"field": "image_link", "op": "exists"}
    assert evaluate_condition(node, {"image_link": "https://x"}) is True
    assert evaluate_condition(node, {"image_link": None}) is False
    assert evaluate_condition(node, {}) is False


def test_empty():
    node = {"field": "image_link", "op": "empty"}
    assert evaluate_condition(node, {}) is True
    assert evaluate_condition(node, {"image_link": ""}) is True
    assert evaluate_condition(node, {"image_link": None}) is True
    assert evaluate_condition(node, {"image_link": "x"}) is False


# --- conjunctive evaluation ---

def test_passes_all_conjunction():
    conditions = [
        {"field": "brand", "op": "equals", "arg": "Acme"},
        {"field": "image_link", "op": "exists"},
    ]
    assert passes_all(conditions, {"brand": "Acme", "image_link": "x"}) is True
    assert passes_all(conditions, {"brand": "Acme"}) is False


def test_passes_all_empty_conditions_is_true():
    assert passes_all([], {"anything": 1}) is True


def test_evaluate_unknown_op_raises():
    with pytest.raises(FilterError):
        evaluate_condition({"field": "x", "op": "regex", "arg": "."}, {"x": "y"})


def test_evaluate_missing_field_key_raises():
    with pytest.raises(FilterError):
        evaluate_condition({"op": "equals", "arg": "x"}, {"y": "z"})


# --- validate_config ---

def test_validate_config_accepts_empty_and_minimal():
    validate_config({})
    validate_config({"conditions": []})
    validate_config({"isActive": False, "conditions": []})


def test_validate_config_accepts_valid_document():
    validate_config({
        "isActive": True,
        "conditions": [
            {"field": "brand", "op": "equals", "arg": "Acme", "caseSensitive": False},
            {"field": "image_link", "op": "exists"},
        ],
    })


def test_validate_config_rejects_bad_shapes():
    with pytest.raises(ValueError):
        validate_config({"conditions": "nope"})
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"op": "equals", "arg": "x"}]})  # missing field
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"field": "", "op": "equals", "arg": "x"}]})
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"field": "f", "op": "nope"}]})
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"field": "f", "op": "equals"}]})  # missing arg
    with pytest.raises(ValueError):
        validate_config({"conditions": [{"field": "f", "op": "exists", "arg": "x"}]})  # arg not allowed


# --- FilterPlugin.process ---

def _cfg(conditions, is_active=True):
    return {"isActive": is_active, "conditions": conditions}


def test_process_drops_non_matching_product():
    plugin = FilterPlugin()
    config = _cfg([{"field": "brand", "op": "equals", "arg": "Acme"}])
    assert plugin.process({"brand": "Acme"}, config, {}, _ctx()) == {"brand": "Acme"}
    assert plugin.process({"brand": "Other"}, config, {}, _ctx()) is None


def test_process_inactive_is_passthrough():
    plugin = FilterPlugin()
    config = _cfg([{"field": "brand", "op": "equals", "arg": "Acme"}], is_active=False)
    assert plugin.process({"brand": "Other"}, config, {}, _ctx()) == {"brand": "Other"}


def test_process_empty_conditions_passthrough():
    plugin = FilterPlugin()
    assert plugin.process({"a": 1}, _cfg([]), {}, _ctx()) == {"a": 1}


def test_process_returns_same_dict_never_copies():
    plugin = FilterPlugin()
    product = {"brand": "Acme"}
    out = plugin.process(product, _cfg([]), {}, _ctx())
    assert out is product


def test_process_does_not_mutate_original_product():
    class Ctx:
        client_id = feed_source_id = run_id = 0
        logger = logging.getLogger("test")

    product = {"brand": "Acme"}
    Ctx.original_product = copy.deepcopy(product)
    config = _cfg([{"field": "brand", "op": "equals", "arg": "Acme"}])
    assert FilterPlugin().process(product, config, {}, Ctx()) is product
    assert Ctx.original_product == {"brand": "Acme"}


def test_process_missing_config_keys_defaults():
    plugin = FilterPlugin()
    assert plugin.process({"a": 1}, {}, _ctx()) == {"a": 1}
