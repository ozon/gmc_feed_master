"""Scope merge + config_hash sensitivity for custom_labels config/data edits."""

from app.staging.config_resolver import merge_scopes
from app.staging.hashing import content_hash


class TestSlotIdsPerKeyMerge:
    def test_feed_source_overrides_only_its_rule(self):
        client = {"slotIds": {"r1": "a\nb", "r2": "x\ny"}}
        feed = {"slotIds": {"r2": "z"}}
        resolved = merge_scopes({}, client, feed)
        assert resolved["slotIds"] == {"r1": "a\nb", "r2": "z"}

    def test_client_overrides_global_only_its_rule(self):
        global_cfg = {"slotIds": {"r1": "a", "r2": "x"}}
        client = {"slotIds": {"r1": "b"}}
        resolved = merge_scopes(global_cfg, client, None)
        assert resolved["slotIds"] == {"r1": "b", "r2": "x"}


def _bundle(resolved_config: dict, resolved_data: dict) -> dict:
    return {
        "pipeline": None,
        "instances": [
            {
                "position": 0,
                "plugin": "custom_labels",
                "plugin_version": "1.0.0",
                "instance_config": {},
                "resolved_config": resolved_config,
                "resolved_data": resolved_data,
            }
        ],
    }


class TestConfigHashSensitivity:
    BASE_CONFIG = {"slotRules": [
        {"id": "r1", "name": "Mid", "isActive": True, "targetSlot": "custom_label_1",
         "matchField": "id", "valueTemplate": "{brand} - Mid"},
    ]}
    BASE_DATA = {"slotIds": {"r1": "a\nb"}}

    def test_unchanged_config_and_data_hash_equal(self):
        assert content_hash(_bundle(self.BASE_CONFIG, self.BASE_DATA)) == content_hash(
            _bundle(dict(self.BASE_CONFIG), dict(self.BASE_DATA))
        )

    def test_config_edit_changes_hash(self):
        edited = {"slotRules": [
            {**self.BASE_CONFIG["slotRules"][0], "valueTemplate": "{brand} - NEW"},
        ]}
        assert content_hash(_bundle(edited, self.BASE_DATA)) != content_hash(
            _bundle(self.BASE_CONFIG, self.BASE_DATA)
        )

    def test_data_edit_changes_hash(self):
        edited = {"slotIds": {"r1": "a\nb\nc"}}
        assert content_hash(_bundle(self.BASE_CONFIG, edited)) != content_hash(
            _bundle(self.BASE_CONFIG, self.BASE_DATA)
        )
