from app.staging.config_resolver import _resolve_declared
from tests.labels_equivalence import (
    CLIENT_SLOT_RULES,
    EXPECTED_BY_SLOT,
    EXPECTED_MERGED_IDS,
    EXPECTED_MERGED_NAMES,
    GLOBAL_SLOT_RULES,
    UNION_HINTS,
)

ALL_SCOPES = ["global", "client", "feed_source"]


class TestScopeMerge:
    def _resolve(self, maps):
        return _resolve_declared(ALL_SCOPES, maps, None)

    def test_global_only(self):
        assert self._resolve({"global": {"a": 1}}) == {"a": 1}

    def test_client_overrides_global_per_key(self):
        assert self._resolve({
            "global": {"a": 1, "b": 2}, "client": {"b": 3},
        }) == {"a": 1, "b": 3}

    def test_feed_source_wins(self):
        merged = self._resolve({
            "global": {"a": 1, "b": 2, "c": 3},
            "client": {"c": 30},
            "feed_source": {"a": 10},
        })
        assert merged == {"a": 10, "b": 2, "c": 30}

    def test_non_dict_values_replace_wholesale(self):
        assert self._resolve({
            "global": {"rules": [1, 2, 3]}, "client": {"rules": [9]},
        }) == {"rules": [9]}

    def test_dict_values_merge_recursively(self):
        merged = self._resolve({
            "global": {"limits": {"title": 150, "desc": 5000}},
            "client": {"limits": {"title": 100}},
        })
        assert merged == {"limits": {"title": 100, "desc": 5000}}

    def test_missing_at_specific_scope_falls_through(self):
        assert self._resolve({
            "global": {"a": 1}, "feed_source": {"b": 2},
        }) == {"a": 1, "b": 2}

    def test_type_flip_replaces(self):
        assert self._resolve({
            "global": {"a": {"nested": 1}}, "client": {"a": "flat"},
        }) == {"a": "flat"}


class TestUnionByKey:
    def test_hinted_list_unions_by_id_in_ancestor_order(self):
        merged = _resolve_declared(
            ["global", "client"],
            {"global": {"slotRules": GLOBAL_SLOT_RULES},
             "client": {"slotRules": CLIENT_SLOT_RULES}},
            UNION_HINTS,
        )
        rules = merged["slotRules"]
        assert [r["id"] for r in rules] == EXPECTED_MERGED_IDS
        assert [r["name"] for r in rules] == EXPECTED_MERGED_NAMES
        by_slot: dict[str, list[str]] = {}
        for rule in rules:
            by_slot.setdefault(rule["targetSlot"], []).append(rule["id"])
        assert by_slot == EXPECTED_BY_SLOT

    def test_client_only_config_extends_global(self):
        merged = _resolve_declared(
            ["global", "client"],
            {"global": {"slotRules": GLOBAL_SLOT_RULES},
             "client": {"slotRules": [CLIENT_SLOT_RULES[1]]}},
            UNION_HINTS,
        )
        assert [r["id"] for r in merged["slotRules"]] == ["g1", "g2", "c2"]

    def test_ancestor_only_config_passes_through(self):
        merged = _resolve_declared(
            ["global", "client"],
            {"global": {"slotRules": GLOBAL_SLOT_RULES}, "client": {}},
            UNION_HINTS,
        )
        assert [r["id"] for r in merged["slotRules"]] == ["g1", "g2"]

    def test_without_hint_lists_still_replace_wholesale(self):
        merged = _resolve_declared(
            ["global", "client"],
            {"global": {"slotRules": GLOBAL_SLOT_RULES},
             "client": {"slotRules": CLIENT_SLOT_RULES}},
            None,
        )
        assert [r["id"] for r in merged["slotRules"]] == ["g1", "c2", "c3"]

    def test_unknown_strategy_replaces_wholesale(self):
        merged = _resolve_declared(
            ["global", "client"],
            {"global": {"slotRules": GLOBAL_SLOT_RULES},
             "client": {"slotRules": CLIENT_SLOT_RULES}},
            {"slotRules": {"strategy": "nope"}},
        )
        assert [r["id"] for r in merged["slotRules"]] == ["g1", "c2", "c3"]

    def test_non_dict_items_are_appended(self):
        merged = _resolve_declared(
            ["global", "client"],
            {"global": {"slotRules": ["raw"]},
             "client": {"slotRules": [{"id": "c2", "name": "C"}]}},
            UNION_HINTS,
        )
        assert merged["slotRules"] == ["raw", {"id": "c2", "name": "C"}]
