"""Category core plugin — taxonomy rules + manual assignments."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any

OPERATORS = ("eq", "ne", "contains", "regex", "in")
DEFAULT_SOURCE_FIELD = "product_type"
MIN_TAXONOMY_ENTRIES = 1000
_LANGUAGE_FILES = {
    "en-US": "taxonomy-with-ids.en-US.csv",
    "de-DE": "taxonomy-with-ids.de-DE.csv",
}
_FETCHABLE_LANGUAGES = ("de-DE",)
_FETCH_URL_TEMPLATE = (
    "https://www.google.com/basepages/producttype/taxonomy-with-ids.{lang}.txt"
)
_SEGMENT_JOIN = " > "


def _taxonomy_directory() -> Path:
    return Path(__file__).resolve().parent


def parse_taxonomy_csv(text: str) -> dict[str, str]:
    """Parse the house taxonomy CSV (id,segment1..segment7) into id -> path."""
    entries: dict[str, str] = {}
    for row in csv.reader(io.StringIO(text)):
        if not row or not row[0].strip():
            continue
        taxonomy_id = row[0].strip()
        segments = [cell.strip() for cell in row[1:] if cell.strip()]
        if not segments:
            raise ValueError(f"taxonomy id {taxonomy_id!r} has no path segments")
        if taxonomy_id in entries:
            raise ValueError(f"duplicate taxonomy id {taxonomy_id!r}")
        entries[taxonomy_id] = _SEGMENT_JOIN.join(segments)
    return entries


def taxonomy_txt_to_csv(text: str) -> str:
    """Convert Google's official taxonomy .txt into the house CSV format."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        taxonomy_id, sep, rest = line.partition(" - ")
        if not sep:
            raise ValueError(f"taxonomy line missing ' - ' separator: {line[:40]!r}")
        segments = [seg.strip() for seg in rest.split(">") if seg.strip()]
        if not segments:
            raise ValueError(f"taxonomy id {taxonomy_id.strip()!r} has no path segments")
        out = io.StringIO()
        csv.writer(out, lineterminator="").writerow([taxonomy_id.strip(), *segments])
        lines.append(out.getvalue())
    return "\n".join(lines) + ("\n" if lines else "")


class TaxonomyIndex:
    """Merged {id -> {language -> path}} over the plugin directory's CSV files."""

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, str]] = {}
        self._languages: list[str] = []
        self._stamps: dict[str, tuple[int, int]] = {}

    def _rebuild_if_stale(self) -> None:
        stamps: dict[str, tuple[int, int]] = {}
        for language, filename in _LANGUAGE_FILES.items():
            path = _taxonomy_directory() / filename
            if path.is_file():
                stat = path.stat()
                stamps[language] = (stat.st_mtime_ns, stat.st_size)
        if stamps == self._stamps and self._stamps:
            return
        entries: dict[str, dict[str, str]] = {}
        for language, filename in _LANGUAGE_FILES.items():
            path = _taxonomy_directory() / filename
            if not path.is_file():
                continue
            for taxonomy_id, taxonomy_path in parse_taxonomy_csv(
                path.read_text(encoding="utf-8")
            ).items():
                entries.setdefault(taxonomy_id, {})[language] = taxonomy_path
        self._entries = entries
        self._languages = [language for language in _LANGUAGE_FILES if language in stamps]
        self._stamps = stamps

    def invalidate(self) -> None:
        self._stamps = {}

    def languages(self) -> list[str]:
        self._rebuild_if_stale()
        return list(self._languages)

    def contains(self, taxonomy_id: str) -> bool:
        self._rebuild_if_stale()
        return taxonomy_id in self._entries

    def path(self, taxonomy_id: str, language: str) -> str | None:
        self._rebuild_if_stale()
        return self._entries.get(taxonomy_id, {}).get(language)

    def search(
        self, query: str, language: str, limit: int, offset: int
    ) -> list[dict[str, str]]:
        self._rebuild_if_stale()
        needle = query.strip().casefold()
        starts: list[tuple[str, str]] = []
        contains: list[tuple[str, str]] = []
        for taxonomy_id, paths in self._entries.items():
            taxonomy_path = paths.get(language)
            if taxonomy_path is None:
                continue
            folded = taxonomy_path.casefold()
            if not needle or folded.startswith(needle):
                starts.append((taxonomy_id, taxonomy_path))
            elif needle in folded:
                contains.append((taxonomy_id, taxonomy_path))
        starts.sort(key=lambda item: item[1].casefold())
        contains.sort(key=lambda item: item[1].casefold())
        merged = starts + contains
        return [
            {"id": taxonomy_id, "path": taxonomy_path}
            for taxonomy_id, taxonomy_path in merged[offset : offset + limit]
        ]


_INDEX: TaxonomyIndex | None = None


def taxonomy_index() -> TaxonomyIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = TaxonomyIndex()
    return _INDEX


async def _fetch_url(url: str) -> bytes:
    from app.ingest.fetch import HttpFetcher

    return await HttpFetcher().fetch(url)


def resolve_path(product: dict[str, Any], path: str) -> list[str]:
    """Resolve a registry attribute path to candidate string values (spec §2.1)."""
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


def compile_rule(rule: dict[str, Any]) -> dict[str, Any]:
    operator = rule["operator"]
    source_value = rule.get("source_value")
    if operator == "in":
        raw_list = source_value if isinstance(source_value, list) else [source_value]
        values = tuple(str(item).strip() for item in raw_list if str(item).strip())
    else:
        values = (str(source_value),)
    pattern = re.compile(values[0]) if operator == "regex" else None
    return {
        "id": rule["id"],
        "source_field": rule.get("source_field") or DEFAULT_SOURCE_FIELD,
        "operator": operator,
        "values": values,
        "pattern": pattern,
        "taxonomy_id": rule.get("taxonomy_id") or "",
        "is_excluded": bool(rule.get("is_excluded", False)),
    }


def rule_matches(compiled: dict[str, Any], product: dict[str, Any]) -> bool:
    candidates = resolve_path(product, compiled["source_field"])
    operator = compiled["operator"]
    if operator == "eq":
        return any(
            candidate.strip().casefold() == compiled["values"][0].strip().casefold()
            for candidate in candidates
        )
    if operator == "ne":
        return not any(
            candidate.strip().casefold() == compiled["values"][0].strip().casefold()
            for candidate in candidates
        )
    if operator == "contains":
        return any(compiled["values"][0] in candidate for candidate in candidates)
    if operator == "regex":
        return any(
            compiled["pattern"] is not None and compiled["pattern"].search(candidate)
            for candidate in candidates
        )
    return any(candidate.strip() in compiled["values"] for candidate in candidates)


def apply_category(
    product: dict[str, Any],
    rules: list[dict[str, Any]],
    assignments: dict[str, str],
) -> dict[str, Any] | None:
    product_id = str(product.get("id", ""))
    if product_id and product_id in assignments:
        return {
            "taxonomy_id": assignments[product_id],
            "provenance": "manual",
            "rule_id": None,
        }
    for compiled in rules:
        if rule_matches(compiled, product):
            if compiled["is_excluded"]:
                return {
                    "taxonomy_id": "",
                    "provenance": "excluded",
                    "rule_id": compiled["id"],
                }
            return {
                "taxonomy_id": compiled["taxonomy_id"],
                "provenance": "auto",
                "rule_id": compiled["id"],
            }
    return None


def validate_config(config: Any) -> None:
    """Strict validation of a category config document. Empty config passes."""
    if not isinstance(config, dict) or not config:
        return
    rules = config.get("rules")
    if rules is None:
        return
    if not isinstance(rules, list):
        raise ValueError("config.rules must be an array")
    seen: set[str] = set()
    index = taxonomy_index()
    for position, rule in enumerate(rules):
        where = f"rules[{position}]"
        if not isinstance(rule, dict):
            raise ValueError(f"{where}: rule must be an object")
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            raise ValueError(f"{where}: id must be a non-empty string")
        if rule_id in seen:
            raise ValueError(f"{where}: duplicate rule id {rule_id!r}")
        seen.add(rule_id)
        source_field = rule.get("source_field")
        if source_field is not None and (
            not isinstance(source_field, str) or not source_field
        ):
            raise ValueError(f"{where}: source_field must be a non-empty string")
        operator = rule.get("operator")
        if operator not in OPERATORS:
            raise ValueError(f"{where}: operator must be one of {', '.join(OPERATORS)}")
        source_value = rule.get("source_value")
        if operator == "in":
            if not isinstance(source_value, list) or not source_value:
                raise ValueError(
                    f"{where}: source_value must be a non-empty array for operator 'in'"
                )
            for item in source_value:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError(
                        f"{where}: source_value entries must be non-empty strings"
                    )
        else:
            if not isinstance(source_value, str) or not source_value:
                raise ValueError(f"{where}: source_value must be a non-empty string")
            if operator == "regex":
                try:
                    re.compile(source_value)
                except re.error as exc:
                    raise ValueError(f"{where}: invalid regex: {exc}") from exc
        is_excluded = rule.get("is_excluded", False)
        if not isinstance(is_excluded, bool):
            raise ValueError(f"{where}: is_excluded must be a boolean")
        taxonomy_id = rule.get("taxonomy_id")
        if not is_excluded:
            if not isinstance(taxonomy_id, str) or not taxonomy_id:
                raise ValueError(
                    f"{where}: taxonomy_id must be a non-empty string when "
                    "is_excluded is false"
                )
            if not index.contains(taxonomy_id):
                raise ValueError(
                    f"{where}: taxonomy_id {taxonomy_id!r} not found in the taxonomy"
                )


def _build_state(config: Any, data: Any) -> dict[str, Any]:
    rules = (config or {}).get("rules") or []
    assignments = (data or {}).get("assignments") or {}
    return {
        "rules": [compile_rule(rule) for rule in rules if isinstance(rule, dict)],
        "assignments": {str(key): str(value) for key, value in assignments.items()},
    }


class CategoryPlugin:
    """Pipeline module assigning google_product_category from taxonomy rules."""

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
        run_state = state if state is not None else _build_state(config, data)
        if not run_state["rules"] and not run_state["assignments"]:
            return product
        outcome = apply_category(product, run_state["rules"], run_state["assignments"])
        if outcome is None:
            return product
        result = dict(product)
        result["google_product_category"] = outcome["taxonomy_id"]
        result["_category_provenance"] = outcome["provenance"]
        if outcome["rule_id"] is not None:
            result["_category_rule_id"] = outcome["rule_id"]
        return result
