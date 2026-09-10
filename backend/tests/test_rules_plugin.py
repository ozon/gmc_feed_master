"""RulesPlugin behaviour tests (actions, ordering, contract compliance)."""

import copy
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins/core/rules"))
from plugin import RulesPlugin, apply_action, evaluate_condition, validate_config


def _ctx():
    class _Ctx:
        client_id = 0
        feed_source_id = 0
        run_id = 0
        logger = logging.getLogger("test")

    return _Ctx()


def test_set_action_fix():
    result = apply_action({"condition": "old"}, {"op": "set", "field": "condition", "value": "new"})
    assert result == {"condition": "new"}


def test_replace_substring():
    result = apply_action(
        {"title": "Hello <b>World</b>"},
        {"op": "replace", "field": "title", "find": "<b>", "with": ""},
    )
    # literal replace removes "<b>" occurrences only, not "</b>"
    assert result == {"title": "Hello World</b>"}


def test_replace_case_sensitive_flag():
    result = apply_action(
        {"title": "Big SALE"},
        {"op": "replace", "field": "title", "find": "sale", "with": "Deal", "caseSensitive": False},
    )
    assert result == {"title": "Big Deal"}


def test_replace_regex_with_capture_group():
    result = apply_action(
        {"title": "Item 123 - Blue"},
        {"op": "replace", "field": "title", "find": r"/Item (\d+)/", "with": "SKU-$1"},
    )
    assert result == {"title": "SKU-123 - Blue"}


def test_replace_case_insensitive_backslash_in_with():
    result = apply_action(
        {"title": "Big Sale"},
        {"op": "replace", "field": "title", "find": "sale", "with": "C:\\path", "caseSensitive": False},
    )
    assert result == {"title": "Big C:\\path"}


def test_replace_regex_preserves_backslash_in_with():
    result = apply_action(
        {"title": "Item 1"},
        {"op": "replace", "field": "title", "find": r"/Item (\d+)/", "with": "C:\\path $1"},
    )
    assert result == {"title": "C:\\path 1"}


def test_validate_config_rejects_empty_find():
    with pytest.raises(ValueError):
        validate_config({"rules": [{
            "id": "r", "name": "n", "when": {"op": "all"},
            "then": [{"op": "replace", "field": "f", "find": "", "with": "x"}],
        }]})


def test_append_and_prepend_coerce():
    assert apply_action({"title": "A"}, {"op": "append", "field": "title", "value": 5})["title"] == "A5"
    assert apply_action({"title": "A"}, {"op": "prepend", "field": "title", "value": "x"})["title"] == "xA"


def test_remove_and_clear():
    assert apply_action({"a": 1, "b": 2}, {"op": "remove", "field": "a"}) == {"b": 2}
    assert apply_action({"a": "text"}, {"op": "clear", "field": "a"}) == {"a": ""}


def test_apply_action_returns_new_dict():
    original = {"title": "A"}
    result = apply_action(original, {"op": "set", "field": "title", "value": "B"})
    assert result is not original
    assert original["title"] == "A"


def test_unknown_action_op_raises():
    with pytest.raises(ValueError):
        apply_action({}, {"op": "explode", "field": "x"})


def test_process_applies_rules_in_order():
    config = {
        "rules": [
            {"id": "r1", "name": "n", "isMasterRule": False, "isActive": True,
             "when": {"op": "all"},
             "then": [{"op": "set", "field": "title", "value": "mid"}]},
            {"id": "r2", "name": "n", "isMasterRule": False, "isActive": True,
             "when": {"op": "all"},
             "then": [{"op": "append", "field": "title", "value": "!"}]},
        ]
    }
    out = RulesPlugin().process({"title": "start"}, config, {}, _ctx())
    assert out == {"title": "mid!"}


def test_process_skips_inactive_rules():
    config = {
        "rules": [
            {"id": "r1", "name": "n", "isMasterRule": False, "isActive": False,
             "when": {"op": "all"},
             "then": [{"op": "set", "field": "title", "value": "x"}]},
        ]
    }
    out = RulesPlugin().process({"title": "orig"}, config, {}, _ctx())
    assert out == {"title": "orig"}


def test_process_ignores_master_flag():
    config = {
        "rules": [
            {"id": "r1", "name": "n", "isMasterRule": True, "isActive": True,
             "when": {"op": "all"},
             "then": [{"op": "set", "field": "title", "value": "master-was-here"}]},
        ]
    }
    out = RulesPlugin().process({"title": "orig"}, config, {}, _ctx())
    assert out == {"title": "master-was-here"}  # flag is UI-only; rule still runs


def test_process_respects_when_condition():
    config = {
        "rules": [
            {"id": "r1", "name": "n", "isMasterRule": False, "isActive": True,
             "when": {"op": "equals", "field": "brand", "arg": "Acme"},
             "then": [{"op": "set", "field": "title", "value": "acme-item"}]},
        ]
    }
    out = RulesPlugin().process({"brand": "Acme", "title": "x"}, config, {}, _ctx())
    assert out["title"] == "acme-item"
    out = RulesPlugin().process({"brand": "Other", "title": "x"}, config, {}, _ctx())
    assert out["title"] == "x"


def test_process_empty_then_is_noop():
    config = {
        "rules": [
            {"id": "r1", "name": "n", "isMasterRule": False, "isActive": True,
             "when": {"op": "all"}, "then": []},
        ]
    }
    out = RulesPlugin().process({"title": "x"}, config, {}, _ctx())
    assert out == {"title": "x"}


def test_process_does_not_mutate_original_product():
    class Ctx:
        client_id = feed_source_id = run_id = 0
        logger = logging.getLogger("test")

    product = {"title": "x"}
    Ctx.original_product = copy.deepcopy(product)
    config = {
        "rules": [
            {"id": "r1", "name": "n", "isMasterRule": False, "isActive": True,
             "when": {"op": "all"},
             "then": [{"op": "set", "field": "title", "value": "changed"}]},
        ]
    }
    RulesPlugin().process(product, config, {}, Ctx())
    assert Ctx.original_product == {"title": "x"}


def test_validate_config_accepts_empty():
    validate_config({})
    validate_config({"rules": []})


def test_validate_config_rejects_bad_shapes():
    with pytest.raises(ValueError):
        validate_config({"rules": "nope"})
    with pytest.raises(ValueError):
        validate_config({"rules": [{"no_id": True}]})
    with pytest.raises(ValueError):
        validate_config({"rules": [{"id": "r", "name": "n", "when": {"op": "all"}, "then": [
            {"op": "set", "field": "f"}  # missing value
        ]}]})
    with pytest.raises(ValueError):
        validate_config({"rules": [{"id": "r", "name": "n", "when": {"op": "nope"}, "then": []}]})
    with pytest.raises(ValueError):
        validate_config({"rules": [{"id": "r", "name": "n", "when": {"op": "and", "children": []}, "then": []}]})


def test_validate_config_accepts_valid_document():
    validate_config({
        "rules": [{
            "id": "r1", "name": "ok", "isMasterRule": True, "isActive": True,
            "when": {"op": "and", "children": [{"op": "empty", "field": "title"}]},
            "then": [{"op": "set", "field": "title", "value": "x"}],
        }]
    })


# --- indexed path tests (Task 6) ---


def test_condition_reads_indexed_path():
    product = {"product_detail": [
        {"attribute_name": "Battery"},
        {"attribute_name": "Color"},
    ]}
    assert evaluate_condition(
        {"op": "equals", "field": "product_detail.2.attribute_name", "arg": "Color"},
        product,
    )


def test_action_set_indexed_repeated_scalar():
    product = {"additional_image_link": ["a.jpg", "b.jpg"]}
    out = apply_action(product, {"op": "set", "field": "additional_image_link.1",
                                 "value": "hero.jpg"})
    assert out["additional_image_link"] == ["hero.jpg", "b.jpg"]


def test_action_set_indexed_extends_list():
    product = {"additional_image_link": ["a.jpg"]}
    out = apply_action(product, {"op": "set", "field": "additional_image_link.3",
                                 "value": "c.jpg"})
    assert out["additional_image_link"] == ["a.jpg", "", "c.jpg"]


def test_action_set_indexed_structured_sub():
    product = {"product_detail": [{"section_name": "General"}]}
    out = apply_action(product, {"op": "set", "field": "product_detail.1.attribute_name",
                                 "value": "Battery"})
    assert out["product_detail"][0]["attribute_name"] == "Battery"


def test_action_set_indexed_structured_sub_extends():
    product = {"product_detail": [{"section_name": "General"}]}
    out = apply_action(product, {"op": "set", "field": "product_detail.3.section_name",
                                 "value": "Extra"})
    assert out["product_detail"] == [
        {"section_name": "General"}, {}, {"section_name": "Extra"},
    ]


def test_action_replace_indexed_element():
    product = {"additional_image_link": ["a-old.jpg", "b.jpg"]}
    out = apply_action(product, {"op": "replace", "field": "additional_image_link.1",
                                 "find": "old", "with": "new"})
    assert out["additional_image_link"][0] == "a-new.jpg"


def test_action_remove_indexed_element():
    product = {"additional_image_link": ["a.jpg", "b.jpg", "c.jpg"]}
    out = apply_action(product, {"op": "remove", "field": "additional_image_link.2"})
    assert out["additional_image_link"] == ["a.jpg", "c.jpg"]


def test_action_clear_indexed_element():
    product = {"additional_image_link": ["a.jpg", "b.jpg"]}
    out = apply_action(product, {"op": "clear", "field": "additional_image_link.1"})
    assert out["additional_image_link"][0] == ""
    assert out["additional_image_link"][1] == "b.jpg"
