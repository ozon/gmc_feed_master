from __future__ import annotations

from typing import Any


def _merge_dicts(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_scopes(
    global_payload: dict[str, Any],
    client_payload: dict[str, Any] | None,
    feed_source_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved = dict(global_payload)
    if client_payload is not None:
        resolved = _merge_dicts(resolved, client_payload)
    if feed_source_payload is not None:
        resolved = _merge_dicts(resolved, feed_source_payload)
    return resolved
