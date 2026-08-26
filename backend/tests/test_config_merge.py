from app.staging.config_resolver import merge_scopes


class TestMergeScopes:
    def test_global_only(self):
        assert merge_scopes({"a": 1}, None, None) == {"a": 1}

    def test_client_overrides_global_per_key(self):
        assert merge_scopes({"a": 1, "b": 2}, {"b": 3}, None) == {"a": 1, "b": 3}

    def test_feed_source_wins(self):
        merged = merge_scopes({"a": 1, "b": 2, "c": 3}, {"c": 30}, {"a": 10})
        assert merged == {"a": 10, "b": 2, "c": 30}

    def test_non_dict_values_replace_wholesale(self):
        assert merge_scopes({"rules": [1, 2, 3]}, {"rules": [9]}, None) == {"rules": [9]}

    def test_dict_values_merge_recursively(self):
        merged = merge_scopes(
            {"limits": {"title": 150, "desc": 5000}},
            {"limits": {"title": 100}},
            None,
        )
        assert merged == {"limits": {"title": 100, "desc": 5000}}

    def test_missing_at_specific_scope_falls_through(self):
        assert merge_scopes({"a": 1}, {}, {"b": 2}) == {"a": 1, "b": 2}

    def test_type_flip_replaces(self):
        assert merge_scopes({"a": {"nested": 1}}, {"a": "flat"}, None) == {"a": "flat"}
