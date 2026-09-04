"""Tests for the custom_labels plugin (primitives, validation, process semantics)."""

import importlib.util
import logging
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "custom_labels_plugin",
    Path(__file__).resolve().parents[2] / "plugins/core/custom_labels/plugin.py",
)
assert _spec is not None and _spec.loader is not None
_plugin = importlib.util.module_from_spec(_spec)
sys.modules["custom_labels_plugin"] = _plugin
_spec.loader.exec_module(_plugin)

compile_template = _plugin.compile_template
matches = _plugin.matches
parse_id_list = _plugin.parse_id_list
render_template = _plugin.render_template
resolve_path = _plugin.resolve_path


class TestParseIdList:
    def test_split_on_newlines_and_commas(self):
        assert parse_id_list("a,b\n c ,d\n") == frozenset({"a", "b", "c", "d"})

    def test_dedupes_and_drops_empty(self):
        assert parse_id_list("a\na\n\n, ,b") == frozenset({"a", "b"})

    def test_none_and_empty(self):
        assert parse_id_list(None) == frozenset()
        assert parse_id_list("  \n,") == frozenset()


class TestCompileTemplate:
    def test_static_only(self):
        assert compile_template("Mid Funnel") == (("lit", "Mid Funnel"),)

    def test_mixed(self):
        assert compile_template("{brand} - Mid Funnel") == (
            ("tok", "brand"),
            ("lit", " - Mid Funnel"),
        )

    def test_adjacent_tokens_and_trailing_literal(self):
        assert compile_template("{a}{b}!") == (
            ("tok", "a"),
            ("tok", "b"),
            ("lit", "!"),
        )

    def test_token_with_subfield_path(self):
        assert compile_template("under {price.value}") == (
            ("lit", "under "),
            ("tok", "price.value"),
        )


class TestResolvePath:
    def test_scalar(self):
        assert resolve_path({"id": "x1"}, "id") == ["x1"]

    def test_scalar_empty_is_empty(self):
        assert resolve_path({"id": ""}, "id") == []

    def test_missing_head(self):
        assert resolve_path({}, "id") == []

    def test_repeated_scalar_each_element(self):
        assert resolve_path({"gtin": ["a", "", "b"]}, "gtin") == ["a", "b"]

    def test_structured_subfield(self):
        assert resolve_path({"price": {"value": "9.99"}}, "price.value") == ["9.99"]

    def test_repeated_structured_requires_single_element(self):
        assert resolve_path({"p": [{"value": "1"}]}, "p.value") == ["1"]
        assert resolve_path({"p": [{"value": "1"}, {"value": "2"}]}, "p.value") == []

    def test_missing_subfield(self):
        assert resolve_path({"price": {}}, "price.value") == []
        assert resolve_path({"price": {"other": "x"}}, "price.value") == []

    def test_non_string_scalar_coerced(self):
        assert resolve_path({"id": 42}, "id") == ["42"]


class TestRenderTemplate:
    def test_static(self):
        assert render_template(compile_template("Sale"), {"id": "x"}) == "Sale"

    def test_tokens_substituted(self):
        assert render_template(compile_template("{brand} - Mid"), {"brand": "Acme"}) == "Acme - Mid"

    def test_empty_token_returns_none(self):
        assert render_template(compile_template("{brand} - Mid"), {"brand": ""}) is None
        assert render_template(compile_template("{brand} - Mid"), {}) is None


class TestMatches:
    def test_hit_and_miss(self):
        assert matches({"id": "a"}, "id", frozenset({"a", "b"})) is True
        assert matches({"id": "z"}, "id", frozenset({"a"})) is False
        assert matches({}, "id", frozenset({"a"})) is False

    def test_repeated_scalar_any_element(self):
        assert matches({"id": ["x", "a"]}, "id", frozenset({"a"})) is True


CustomLabelsPlugin = _plugin.CustomLabelsPlugin
validate_config_fn = None  # bound via class in Task 3; tests call the method

from registry.model import (
    AttributeKind,
    ExportStatus,
    FeedDomain,
    RegistryAttribute,
    RegistryDocument,
    RequirementStatus,
    SubField,
)


def _registry():
    def attr(name, kind=AttributeKind.SCALAR, fields=()):
        return RegistryAttribute(
            name=name, kind=kind, type="string",
            required=RequirementStatus.OPTIONAL,
            domain=FeedDomain.PRIMARY,
            export_status=ExportStatus.EXPORTABLE,
            fields=fields,
        )

    return RegistryDocument(attributes={
        "id": attr("id"),
        "brand": attr("brand"),
        "item_group_id": attr("item_group_id"),
        "price": attr("price", AttributeKind.STRUCTURED,
                      (SubField("value", "String", RequirementStatus.REQUIRED),)),
    })


CONFIG = {
    "slotRules": [
        {
            "id": "r1", "name": "Mid Funnel", "isActive": True,
            "targetSlot": "custom_label_1", "matchField": "id",
            "valueTemplate": "{brand} - Mid Funnel",
        },
        {
            "id": "r2", "name": "Rising", "isActive": True,
            "targetSlot": "custom_label_1", "matchField": "item_group_id",
            "valueTemplate": "Rising {brand}",
        },
        {
            "id": "r3", "name": "Static", "isActive": True,
            "targetSlot": "custom_label_0", "matchField": "id",
            "valueTemplate": "Static Sale",
            "fallbackTemplate": "EverythingElse",
        },
    ]
}
DATA = {"slotIds": {"r1": "a, b\nb\nc", "r2": "g1", "r3": "s1"}}


def _ctx():
    from app.plugins.runtime import RunContext

    return RunContext(client_id=1, feed_source_id=1, run_id=1, logger=logging.getLogger("t"))


@pytest.fixture()
def plugin():
    return CustomLabelsPlugin()


def _state(plugin, config=CONFIG, data=DATA):
    return plugin.prepare_run(config, data, _ctx())


# --- validation -------------------------------------------------------------


class TestValidateConfig:
    def test_valid_config_passes(self, plugin, monkeypatch):
        monkeypatch.setattr("registry.loader.load_registry", _registry)
        plugin.validate_config(CONFIG)

    def test_empty_config_passes(self, plugin):
        plugin.validate_config({})
        plugin.validate_config(None)

    def test_rejects_unknown_target_slot(self, plugin):
        bad = {"slotRules": [{**CONFIG["slotRules"][0], "targetSlot": "custom_label_9"}]}
        with pytest.raises(ValueError, match="targetSlot"):
            plugin.validate_config(bad)

    def test_rejects_empty_match_field_and_template(self, plugin):
        with pytest.raises(ValueError, match="matchField"):
            plugin.validate_config({"slotRules": [{**CONFIG["slotRules"][0], "matchField": ""}]})
        with pytest.raises(ValueError, match="valueTemplate"):
            plugin.validate_config({"slotRules": [{**CONFIG["slotRules"][0], "valueTemplate": ""}]})

    def test_rejects_non_registry_match_field(self, plugin, monkeypatch):
        monkeypatch.setattr("registry.loader.load_registry", _registry)
        bad = {"slotRules": [{**CONFIG["slotRules"][0], "matchField": "sku"}]}
        with pytest.raises(ValueError, match="unknown registry attribute"):
            plugin.validate_config(bad)

    def test_rejects_unknown_token_path(self, plugin, monkeypatch):
        monkeypatch.setattr("registry.loader.load_registry", _registry)
        bad = {"slotRules": [{**CONFIG["slotRules"][0], "valueTemplate": "{nope} x"}]}
        with pytest.raises(ValueError, match="unknown registry attribute"):
            plugin.validate_config(bad)

    def test_rejects_unknown_subfield_token(self, plugin, monkeypatch):
        monkeypatch.setattr("registry.loader.load_registry", _registry)
        bad = {"slotRules": [{**CONFIG["slotRules"][0], "valueTemplate": "{price.nope}"}]}
        with pytest.raises(ValueError, match="unknown subfield"):
            plugin.validate_config(bad)

    def test_rejects_duplicate_ids(self, plugin):
        dup = {"slotRules": [CONFIG["slotRules"][0], dict(CONFIG["slotRules"][0])]}
        with pytest.raises(ValueError, match="duplicate"):
            plugin.validate_config(dup)

    def test_rejects_second_fallback_on_same_slot(self, plugin):
        second = {**CONFIG["slotRules"][1], "fallbackTemplate": "Other"}
        with pytest.raises(ValueError, match="fallback"):
            plugin.validate_config({"slotRules": [CONFIG["slotRules"][0], second]})


# --- process semantics -------------------------------------------------------


class TestProcess:
    def test_first_match_wins_per_slot_and_slots_are_independent(self, plugin):
        state = _state(plugin)
        product = {"id": "a", "item_group_id": "g1", "brand": "Acme"}
        out = plugin.process(product, CONFIG, DATA, _ctx(), state=state)
        assert out["custom_label_1"] == "Acme - Mid Funnel"  # r1 beats r2 (priority)
        assert "custom_label_0" not in out  # r3's IDs don't contain "a"

    def test_evaluation_continues_across_slots(self, plugin):
        state = _state(plugin)
        out = plugin.process({"id": "s1", "brand": "B"}, CONFIG, DATA, _ctx(), state=state)
        assert out["custom_label_0"] == "Static Sale"
        assert "custom_label_1" not in out

    def test_empty_token_skips_all_dynamic_rules_for_that_slot(self, plugin):
        state = _state(plugin)
        # "a" is in r1's IDs and "g1" in r2's, but brand empty -> both skipped
        out = plugin.process(
            {"id": "a", "item_group_id": "g1", "brand": ""}, CONFIG, DATA, _ctx(), state=state,
        )
        assert "custom_label_1" not in out

    def test_matched_but_token_empty_falls_to_lower_priority_static_rule(self, plugin):
        config = {"slotRules": [
            {"id": "r1", "name": "Dyn", "isActive": True, "targetSlot": "custom_label_0",
             "matchField": "id", "valueTemplate": "{brand} X"},
            {"id": "r2", "name": "Stat", "isActive": True, "targetSlot": "custom_label_0",
             "matchField": "id", "valueTemplate": "Static"},
        ]}
        data = {"slotIds": {"r1": "a", "r2": "a"}}
        state = _state(plugin, config, data)
        out = plugin.process({"id": "a", "brand": ""}, config, data, _ctx(), state=state)
        assert out["custom_label_0"] == "Static"

    def test_no_fallback_when_no_rule_matches(self, plugin):
        state = _state(plugin)
        out = plugin.process({"id": "zzz", "brand": "B"}, CONFIG, DATA, _ctx(), state=state)
        assert "custom_label_0" not in out  # no rule matched → no fallback
        assert "custom_label_1" not in out  # no fallback declared on custom_label_1

    def test_fallback_applied_when_rule_matched_but_token_empty(self, plugin):
        config = {"slotRules": [
            {"id": "r1", "name": "Fb", "isActive": True, "targetSlot": "custom_label_0",
             "matchField": "id", "valueTemplate": "{brand} X",
             "fallbackTemplate": "Fallback Value"},
        ]}
        data = {"slotIds": {"r1": "a"}}
        state = _state(plugin, config, data)
        out = plugin.process({"id": "a", "brand": ""}, config, data, _ctx(), state=state)
        assert out["custom_label_0"] == "Fallback Value"

    def test_inactive_rules_skipped(self, plugin):
        config = {"slotRules": [{**CONFIG["slotRules"][0], "isActive": False}]}
        state = _state(plugin, config, DATA)
        out = plugin.process({"id": "a", "brand": "B"}, config, DATA, _ctx(), state=state)
        assert "custom_label_1" not in out

    def test_without_state_rebuilds_from_config_and_data(self, plugin):
        # process must still work when called without state (defensive path)
        out = plugin.process({"id": "a", "brand": "Acme"}, CONFIG, DATA, _ctx())
        assert out["custom_label_1"] == "Acme - Mid Funnel"

    def test_original_product_not_mutated(self, plugin):
        state = _state(plugin)
        product = {"id": "a", "brand": "B"}
        plugin.process(product, CONFIG, DATA, _ctx(), state=state)
        assert product == {"id": "a", "brand": "B"}

    def test_structured_subfield_token(self, plugin):
        config = {"slotRules": [
            {"id": "r1", "name": "Price", "isActive": True, "targetSlot": "custom_label_2",
             "matchField": "id", "valueTemplate": "under {price.value}"},
        ]}
        data = {"slotIds": {"r1": "a"}}
        state = _state(plugin, config, data)
        out = plugin.process(
            {"id": "a", "price": {"value": "9.99"}}, config, data, _ctx(), state=state,
        )
        assert out["custom_label_2"] == "under 9.99"
