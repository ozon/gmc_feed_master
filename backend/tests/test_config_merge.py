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


from app.staging.config_resolver import _resolve_declared

# Shared equivalence fixture — keep in lockstep with
# frontend/src/features/customLabels/scopeMerge.test.ts (spec §1.2 gate).
GLOBAL_SLOT_RULES = [
    {"id": "g1", "name": "Global Mid", "isActive": True,
     "targetSlot": "custom_label_1", "matchField": "id",
     "valueTemplate": "{brand} - Mid"},
    {"id": "g2", "name": "Global Top", "isActive": True,
     "targetSlot": "custom_label_0", "matchField": "id",
     "valueTemplate": "{brand} - Top"},
]
CLIENT_SLOT_RULES = [
    {"id": "g1", "name": "Client Mid", "isActive": True,
     "targetSlot": "custom_label_1", "matchField": "brand",
     "valueTemplate": "{brand} - Client"},
    {"id": "c2", "name": "Client Only", "isActive": True,
     "targetSlot": "custom_label_0", "matchField": "id",
     "valueTemplate": "{brand} - ClientOnly"},
    {"id": "c3", "name": "Same Slot As G1", "isActive": True,
     "targetSlot": "custom_label_1", "matchField": "id",
     "valueTemplate": "{brand} - C3"},
]
UNION_HINTS = {"slotRules": {"strategy": "union_by_key", "key": "id"}}


class TestUnionByKey:
    def test_hinted_list_unions_by_id_in_ancestor_order(self):
        merged = _resolve_declared(
            ["global", "client"],
            {"global": {"slotRules": GLOBAL_SLOT_RULES},
             "client": {"slotRules": CLIENT_SLOT_RULES}},
            UNION_HINTS,
        )
        rules = merged["slotRules"]
        # Same ids in the same order as the frontend merge (spec §1.2):
        assert [r["id"] for r in rules] == ["g1", "g2", "c2", "c3"]
        # Content of the more specific tier wins for the overridden id...
        assert [r["name"] for r in rules] == [
            "Client Mid", "Global Top", "Client Only", "Same Slot As G1",
        ]
        # ...and per-slot winning order (first match wins) is identical:
        by_slot: dict[str, list[str]] = {}
        for rule in rules:
            by_slot.setdefault(rule["targetSlot"], []).append(rule["id"])
        assert by_slot == {
            "custom_label_1": ["g1", "c3"],
            "custom_label_0": ["g2", "c2"],
        }

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
