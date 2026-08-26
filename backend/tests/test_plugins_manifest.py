"""Tests for plugin manifest parsing and validation (Task 2)."""

import dataclasses

import pytest

from app.plugins.manifest import ManifestError, PluginManifest, parse_manifest


def minimal_manifest() -> dict:
    return {
        "id": "my_plugin",
        "name": "My Plugin",
        "version": "1.0.0",
        "extension_point": "pipeline_module",
        "config_schema": {},
        "data_schema": {},
    }


class TestValidMinimal:
    def test_minimal_manifest_round_trips(self):
        doc = minimal_manifest()
        m = parse_manifest(doc)
        assert isinstance(m, PluginManifest)
        assert m.id == "my_plugin"
        assert m.name == "My Plugin"
        assert m.version == "1.0.0"
        assert m.extension_point == "pipeline_module"
        assert m.config_schema == {}
        assert m.data_schema == {}
        assert m.config_scope == ("global",)
        assert m.data_scope == ("global",)
        assert m.raw is doc

    def test_raw_preserves_input_document(self):
        doc = {**minimal_manifest(), "extra_key": {"nested": [1, 2]}}
        m = parse_manifest(doc)
        assert m.raw == doc
        assert m.raw["extra_key"] == {"nested": [1, 2]}

    def test_result_is_immutable(self):
        m = parse_manifest(minimal_manifest())
        with pytest.raises(dataclasses.FrozenInstanceError):
            m.id = "changed"  # type: ignore[misc]


class TestScopeNormalization:
    def test_missing_scope_defaults_to_global(self):
        m = parse_manifest(minimal_manifest())
        assert m.config_scope == ("global",)
        assert m.data_scope == ("global",)

    def test_bare_string_becomes_one_tuple(self):
        doc = {**minimal_manifest(), "config_scope": "client"}
        m = parse_manifest(doc)
        assert m.config_scope == ("client",)

    def test_list_of_valid_scopes(self):
        doc = {
            **minimal_manifest(),
            "config_scope": ["global", "client"],
            "data_scope": ["feed_source"],
        }
        m = parse_manifest(doc)
        assert m.config_scope == ("global", "client")
        assert m.data_scope == ("feed_source",)

    def test_empty_string_scope_rejected(self):
        doc = {**minimal_manifest(), "data_scope": ""}
        with pytest.raises(ManifestError) as excinfo:
            parse_manifest(doc)
        assert excinfo.value.reason != ""

    @pytest.mark.parametrize("scope_key", ["config_scope", "data_scope"])
    def test_undeclared_scope_value_rejected(self, scope_key):
        doc = {**minimal_manifest(), scope_key: ["global", "tenant"]}
        with pytest.raises(ManifestError):
            parse_manifest(doc)

    @pytest.mark.parametrize("scope_key", ["config_scope", "data_scope"])
    def test_empty_scope_list_accepted(self, scope_key):
        doc = {**minimal_manifest(), scope_key: []}
        m = parse_manifest(doc)
        assert getattr(m, scope_key) == ()

    def test_mixed_valid_invalid_scopes_rejected(self):
        doc = {**minimal_manifest(), "data_scope": ["client", "bogus"]}
        with pytest.raises(ManifestError):
            parse_manifest(doc)

    def test_non_string_non_list_scope_rejected(self):
        doc = {**minimal_manifest(), "config_scope": 42}
        with pytest.raises(ManifestError):
            parse_manifest(doc)


class TestDocumentShape:
    def test_non_object_document_rejected(self):
        for bad in ([], "str", 5, None, True):
            with pytest.raises(ManifestError):
                parse_manifest(bad)

    @pytest.mark.parametrize(
        "missing",
        [
            "id",
            "name",
            "version",
            "extension_point",
            "config_schema",
            "data_schema",
        ],
    )
    def test_each_required_key_missing_rejected(self, missing):
        doc = minimal_manifest()
        del doc[missing]
        with pytest.raises(ManifestError):
            parse_manifest(doc)


class TestFieldValidation:
    @pytest.mark.parametrize("bad_id", ["Bad-Id", "1abc", "_lead", "", "has space", "UPPER"])
    def test_bad_id_rejected(self, bad_id):
        doc = {**minimal_manifest(), "id": bad_id}
        with pytest.raises(ManifestError):
            parse_manifest(doc)

    def test_non_string_id_rejected(self):
        doc = {**minimal_manifest(), "id": 123}
        with pytest.raises(ManifestError):
            parse_manifest(doc)

    @pytest.mark.parametrize("field", ["name", "version"])
    def test_empty_name_or_version_rejected(self, field):
        doc = {**minimal_manifest(), field: ""}
        with pytest.raises(ManifestError):
            parse_manifest(doc)

    @pytest.mark.parametrize("field", ["name", "version"])
    def test_non_string_name_or_version_rejected(self, field):
        doc = {**minimal_manifest(), field: 7}
        with pytest.raises(ManifestError):
            parse_manifest(doc)

    def test_wrong_extension_point_rejected(self):
        doc = {**minimal_manifest(), "extension_point": "quality_rule"}
        with pytest.raises(ManifestError):
            parse_manifest(doc)


class TestSchemaValidation:
    @pytest.mark.parametrize("field", ["config_schema", "data_schema"])
    def test_non_dict_schema_rejected(self, field):
        doc = {**minimal_manifest(), field: ["not", "a", "dict"]}
        with pytest.raises(ManifestError):
            parse_manifest(doc)

    @pytest.mark.parametrize("field", ["config_schema", "data_schema"])
    def test_schema_invalid_against_meta_schema_rejected(self, field):
        doc = {**minimal_manifest(), field: {"type": "nope"}}
        with pytest.raises(ManifestError):
            parse_manifest(doc)

    def test_valid_nontrivial_schema_accepted(self):
        schema = {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 0},
                "mode": {"enum": ["fast", "slow"]},
            },
            "required": ["limit"],
        }
        doc = {**minimal_manifest(), "config_schema": schema}
        m = parse_manifest(doc)
        assert m.config_schema == schema


class TestErrorReasons:
    def test_error_has_reason_attribute(self):
        with pytest.raises(ManifestError) as excinfo:
            parse_manifest(None)
        assert isinstance(excinfo.value.reason, str)
        assert excinfo.value.reason != ""

    def test_distinct_reasons_for_distinct_failures(self):
        reasons = set()
        cases = [
            None,
            {},
            {**minimal_manifest(), "id": "Bad-Id"},
            {**minimal_manifest(), "extension_point": "quality_rule"},
            {**minimal_manifest(), "config_schema": {"type": "nope"}},
            {**minimal_manifest(), "config_scope": ["nope"]},
        ]
        for case in cases:
            try:
                parse_manifest(case)
            except ManifestError as e:
                reasons.add(e.reason)
        assert len(reasons) == len(cases)
