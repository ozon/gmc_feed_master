from __future__ import annotations

import hashlib
import json
from typing import Any


def strip_derived(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_derived(item)
            for key, item in value.items()
            if not (isinstance(key, str) and key.startswith("_"))
        }
    if isinstance(value, list):
        return [strip_derived(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        strip_derived(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def content_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
