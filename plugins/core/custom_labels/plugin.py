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


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def _registry_document():
    # Imported lazily so tests can monkeypatch registry.loader.load_registry.
    from registry.loader import load_registry

    return load_registry()


def _validate_registry_path(path: str, registry: Any, where: str) -> None:
    head, _, sub = path.partition(".")
    attribute = registry.attributes.get(head)
    if attribute is None:
        raise ValueError(f"{where}: unknown registry attribute {head!r}")
    if sub:
        field_names = {field.name for field in attribute.fields}
        if sub not in field_names:
            raise ValueError(f"{where}: unknown subfield {sub!r} on {head!r}")


def _validate_template(template: str, where: str) -> None:
    registry = _registry_document()
    for kind, token_path in compile_template(template):
        if kind == "tok":
            _validate_registry_path(token_path, registry, f"{where} token {{{token_path}}}")


def validate_config(config: Any) -> None:
    """Strict validation of a custom_labels config document. Empty config passes."""
    if not isinstance(config, dict) or not config:
        return
    rules = config.get("slotRules")
    if rules is None:
        return
    if not isinstance(rules, list):
        raise ValueError("config.slotRules must be an array")
    seen_ids: set[str] = set()
    first_rule_per_slot: dict[str, str] = {}
    for index, rule in enumerate(rules):
        path = f"slotRules[{index}]"
        if not isinstance(rule, dict):
            raise ValueError(f"{path}: rule must be an object")
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            raise ValueError(f"{path}: id must be a non-empty string")
        if rule_id in seen_ids:
            raise ValueError(f"{path}: duplicate rule id {rule_id!r}")
        seen_ids.add(rule_id)
        if not isinstance(rule.get("name"), str) or not rule["name"]:
            raise ValueError(f"{path}: name must be a non-empty string")
        if rule.get("targetSlot") not in _TARGET_SLOTS:
            raise ValueError(f"{path}: targetSlot must be one of {', '.join(_TARGET_SLOTS)}")
        if rule.get("matchMode", "values") not in ("values", "all"):
            raise ValueError(f"{path}: matchMode must be 'values' or 'all'")
        match_field = rule.get("matchField")
        if not isinstance(match_field, str) or not match_field:
            raise ValueError(f"{path}: matchField must be a non-empty string")
        _validate_registry_path(match_field, _registry_document(), f"{path}.matchField")
        template = rule.get("valueTemplate")
        if not isinstance(template, str) or not template:
            raise ValueError(f"{path}: valueTemplate must be a non-empty string")
        _validate_template(template, path)
        fallback = rule.get("fallbackTemplate", "")
        if not isinstance(fallback, str):
            raise ValueError(f"{path}: fallbackTemplate must be a string")
        if fallback:
            _validate_template(fallback, path)
            slot = rule["targetSlot"]
            if slot in first_rule_per_slot:
                raise ValueError(
                    f"{path}: fallbackTemplate already declared by rule "
                    f"{first_rule_per_slot[slot]!r} for {slot}"
                )
        first_rule_per_slot.setdefault(rule["targetSlot"], rule_id)


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


def _build_state(config: Any, data: Any) -> dict[str, Any]:
    rules = (config or {}).get("slotRules") or []
    slot_ids = (data or {}).get("slotIds") or {}
    prepared: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict) or not rule.get("isActive", True):
            continue
        raw = slot_ids.get(rule.get("id"), "")
        prepared.append({
            "id": rule["id"],
            "targetSlot": rule["targetSlot"],
            "matchField": rule["matchField"],
            "matchAll": rule.get("matchMode") == "all",
            "ids": parse_id_list(raw if isinstance(raw, str) else ""),
            "template": compile_template(rule["valueTemplate"]),
            "fallback": compile_template(rule.get("fallbackTemplate") or ""),
        })
    return {"rules": prepared}


class CustomLabelsPlugin:
    """Pipeline module assigning custom labels from bulk-ID slot rules."""

    def validate_config(self, config: Any) -> None:
        validate_config(config)

    def prepare_run(self, config: Any, data: Any, ctx: Any) -> dict[str, Any]:
        return _build_state(config, data)

    def process(
        self,
        product: dict[str, Any],
        config: Any,
        data: Any,
        ctx: Any,
        state: Any = None,
    ) -> dict[str, Any]:
        rules = (state or _build_state(config, data)).get("rules") or []
        if not rules:
            return product
        result = dict(product)
        by_slot: dict[str, list[dict[str, Any]]] = {}
        for rule in rules:
            by_slot.setdefault(rule["targetSlot"], []).append(rule)

        for slot, slot_rules in by_slot.items():
            value: str | None = None
            any_matched = False
            for rule in slot_rules:
                if not rule["matchAll"] and not matches(
                    product, rule["matchField"], rule["ids"]
                ):
                    continue
                any_matched = True
                value = render_template(rule["template"], product)
                if value is not None:
                    break
                # matched but a token resolved empty -> skip to the next rule
            if value is None and any_matched and slot_rules[0]["fallback"]:
                value = render_template(slot_rules[0]["fallback"], product)
            if value:
                result[slot] = value
        return result
