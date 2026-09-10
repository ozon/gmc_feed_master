"""Shared slot-rules equivalence fixture — keep in lockstep with
frontend/src/features/customLabels/scopeMerge.test.ts (spec §1.2 gate).
Read-only: consumers must not mutate these dicts in place."""

import copy

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

MERGED_SLOT_RULES = [
    copy.deepcopy(CLIENT_SLOT_RULES[0]),
    copy.deepcopy(GLOBAL_SLOT_RULES[1]),
    copy.deepcopy(CLIENT_SLOT_RULES[1]),
    copy.deepcopy(CLIENT_SLOT_RULES[2]),
]
EXPECTED_MERGED_IDS = ["g1", "g2", "c2", "c3"]
EXPECTED_MERGED_NAMES = ["Client Mid", "Global Top", "Client Only", "Same Slot As G1"]
EXPECTED_BY_SLOT = {
    "custom_label_1": ["g1", "c3"],
    "custom_label_0": ["g2", "c2"],
}
