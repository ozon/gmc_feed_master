"""Tests for the custom_labels plugin (primitives, validation, process semantics)."""

import importlib.util
import logging
import sys
from pathlib import Path

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
