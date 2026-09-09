"""Category core plugin — taxonomy rules + manual assignments."""

from __future__ import annotations

import csv
import io
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


class CategoryPlugin:
    """Pipeline module assigning google_product_category from taxonomy rules."""

    def validate_config(self, config: Any) -> None:
        return None

    def process(
        self,
        product: dict[str, Any],
        config: Any,
        data: Any,
        ctx: Any,
    ) -> dict[str, Any]:
        return product
