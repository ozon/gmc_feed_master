"""Category plugin rule engine + validate_config."""

from pathlib import Path
from typing import ClassVar

import pytest

from tests.category_plugin_module import category_plugin as cp

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "category"


@pytest.fixture(autouse=True)
def fixture_taxonomy(monkeypatch):
    monkeypatch.setattr(cp, "_taxonomy_directory", lambda: FIXTURES)
    monkeypatch.setattr(cp, "_INDEX", None)


def _rule(**over):
    rule = {
        "id": "r1",
        "source_field": "product_type",
        "operator": "eq",
        "source_value": "Shoes",
        "taxonomy_id": "166",
        "is_excluded": False,
    }
    rule.update(over)
    return rule


class TestResolvePath:
    def test_scalar(self):
        assert cp.resolve_path({"product_type": "Shoes"}, "product_type") == ["Shoes"]

    def test_repeated_scalar_skips_empty(self):
        assert cp.resolve_path({"product_type": ["A", ""]}, "product_type") == ["A"]

    def test_subfield(self):
        assert cp.resolve_path({"shipping": {"country": "DE"}}, "shipping.country") == ["DE"]

    def test_missing(self):
        assert cp.resolve_path({}, "product_type") == []


class TestRuleMatches:
    def test_eq_is_case_and_whitespace_insensitive(self):
        compiled = cp.compile_rule(_rule(source_value="  shoes "))
        assert cp.rule_matches(compiled, {"product_type": "  SHOES "})

    def test_ne_true_when_no_candidate_equals(self):
        compiled = cp.compile_rule(_rule(operator="ne", source_value="Hats"))
        assert cp.rule_matches(compiled, {"product_type": "Shoes"})
        assert not cp.rule_matches(compiled, {"product_type": "hats"})

    def test_ne_true_when_field_missing(self):
        compiled = cp.compile_rule(_rule(operator="ne", source_value="Hats"))
        assert cp.rule_matches(compiled, {})

    def test_contains_is_case_sensitive(self):
        compiled = cp.compile_rule(_rule(operator="contains", source_value="Shoe"))
        assert cp.rule_matches(compiled, {"product_type": "Big Shoe Rack"})
        assert not cp.rule_matches(compiled, {"product_type": "shoe rack"})

    def test_regex_searches(self):
        compiled = cp.compile_rule(_rule(operator="regex", source_value=r"^sh\d{2}$"))
        assert cp.rule_matches(compiled, {"product_type": "sh42"})
        assert not cp.rule_matches(compiled, {"product_type": "sh4"})

    def test_in_matches_list_members_stripped(self):
        compiled = cp.compile_rule(_rule(operator="in", source_value=["Boots", " Shoes "]))
        assert cp.rule_matches(compiled, {"product_type": "Shoes"})
        assert not cp.rule_matches(compiled, {"product_type": "Socks"})

    def test_default_source_field_is_product_type(self):
        compiled = cp.compile_rule(
            {"id": "r", "operator": "eq", "source_value": "x", "taxonomy_id": "1"}
        )
        assert compiled["source_field"] == "product_type"


class TestApplyCategory:
    RULES: ClassVar[list] = [
        cp.compile_rule(_rule(id="r-auto", taxonomy_id="166")),
        cp.compile_rule(_rule(id="r-second", source_value="Boots", taxonomy_id="53")),
    ]

    def test_manual_assignment_wins_before_rules(self):
        outcome = cp.apply_category(
            {"id": "p1", "product_type": "Shoes"}, self.RULES, {"p1": "53"}
        )
        assert outcome == {"taxonomy_id": "53", "provenance": "manual", "rule_id": None}

    def test_first_matching_rule_wins(self):
        outcome = cp.apply_category(
            {"id": "p1", "product_type": "Shoes"}, self.RULES, {}
        )
        assert outcome == {"taxonomy_id": "166", "provenance": "auto", "rule_id": "r-auto"}

    def test_excluded_rule_sets_empty_taxonomy(self):
        rules = [cp.compile_rule(_rule(id="r-x", is_excluded=True))]
        outcome = cp.apply_category({"id": "p1", "product_type": "Shoes"}, rules, {})
        assert outcome == {"taxonomy_id": "", "provenance": "excluded", "rule_id": "r-x"}

    def test_no_match_returns_none(self):
        assert cp.apply_category({"id": "p1", "product_type": "Socks"}, self.RULES, {}) is None


class TestValidateConfig:
    def test_empty_config_passes(self):
        cp.validate_config({})
        cp.validate_config(None)

    def test_valid_config_passes(self):
        cp.validate_config({"rules": [_rule(), _rule(id="r2", taxonomy_id="53")]})

    def test_rejects_non_list_rules(self):
        with pytest.raises(ValueError, match="array"):
            cp.validate_config({"rules": {}})

    def test_rejects_missing_id(self):
        with pytest.raises(ValueError, match="id"):
            cp.validate_config(
                {"rules": [{"operator": "eq", "source_value": "x", "taxonomy_id": "1"}]}
            )

    def test_rejects_duplicate_ids(self):
        with pytest.raises(ValueError, match="duplicate"):
            cp.validate_config({"rules": [_rule(), _rule()]})

    def test_rejects_unknown_operator(self):
        with pytest.raises(ValueError, match="operator"):
            cp.validate_config({"rules": [_rule(operator="nope")]})

    def test_in_requires_array_source_value(self):
        with pytest.raises(ValueError, match="array"):
            cp.validate_config({"rules": [_rule(operator="in", source_value="Shoes")]})

    def test_rejects_bad_regex(self):
        with pytest.raises(ValueError, match="regex"):
            cp.validate_config({"rules": [_rule(operator="regex", source_value="([)")]})

    def test_taxonomy_id_required_unless_excluded(self):
        with pytest.raises(ValueError, match="taxonomy_id"):
            cp.validate_config({"rules": [_rule(taxonomy_id=None)]})
        cp.validate_config({"rules": [_rule(taxonomy_id=None, is_excluded=True)]})

    def test_rejects_unknown_taxonomy_id(self):
        with pytest.raises(ValueError, match="not found"):
            cp.validate_config({"rules": [_rule(taxonomy_id="99999999")]})


class TestPluginValidateConfigDelegates:
    def test_delegates(self):
        plugin = cp.CategoryPlugin()
        plugin.validate_config({})
        with pytest.raises(ValueError, match="array"):
            plugin.validate_config({"rules": {}})
