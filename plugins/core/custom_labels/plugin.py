"""Custom Labels core plugin — bulk-ID slot rules with dynamic value templates."""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Pure primitives
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\{([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)?)\}")
_SEPARATOR_RE = re.compile(r"[\n,]+")

_TARGET_SLOTS = tuple(f"custom_label_{i}" for i in range(5))


def parse_id_list(raw: str | None) -> frozenset[str]:
    """Split on newlines/commas, trim, drop empties, dedupe."""
    if not raw:
        return frozenset()
    return frozenset(part for part in (p.strip() for p in _SEPARATOR_RE.split(raw)) if part)


def compile_template(template: str) -> tuple[tuple[str, str], ...]:
    """Compile a template into ("lit", text) / ("tok", path) segments."""
    segments: list[tuple[str, str]] = []
    pos = 0
    for match in _TOKEN_RE.finditer(template):
        if match.start() > pos:
            segments.append(("lit", template[pos : match.start()]))
        segments.append(("tok", match.group(1)))
        pos = match.end()
    if pos < len(template):
        segments.append(("lit", template[pos:]))
    return tuple(segments)


def resolve_path(product: dict[str, Any], path: str) -> list[str]:
    """Resolve a registry attribute path to candidate string values.

    Path shapes and semantics (spec §2.1):
    - ``attr`` on scalar -> [value] (empty string -> no candidates)
    - ``attr`` on repeated_scalar -> every non-empty element
    - ``attr.subfield`` on structured -> [value]
    - ``attr.subfield`` on repeated_structured -> [value] only when exactly
      one element exists, else no candidates (ambiguous -> treated as empty)
    """
    head, _, sub = path.partition(".")
    value = product.get(head)
    if value is None:
        return []
    if sub:
        if isinstance(value, dict):
            item = value.get(sub)
            return [str(item)] if item not in (None, "") else []
        if isinstance(value, list):
            if len(value) != 1 or not isinstance(value[0], dict):
                return []
            item = value[0].get(sub)
            return [str(item)] if item not in (None, "") else []
        return []
    if isinstance(value, str):
        return [value] if value != "" else []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def render_template(
    segments: tuple[tuple[str, str], ...], product: dict[str, Any]
) -> str | None:
    """Render compiled segments; None when any token resolves empty (token skip)."""
    parts: list[str] = []
    for kind, text in segments:
        if kind == "lit":
            parts.append(text)
            continue
        values = resolve_path(product, text)
        if not values:
            return None
        parts.append(values[0])
    return "".join(parts)


def matches(product: dict[str, Any], match_field: str, ids: frozenset[str]) -> bool:
    """True when any candidate value of `match_field` is in `ids`."""
    return any(value in ids for value in resolve_path(product, match_field))
