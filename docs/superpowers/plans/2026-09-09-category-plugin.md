# Category Plugin (M12) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Category core plugin — taxonomy rules + manual assignments → `google_product_category` with a provenance sidecar, taxonomy autocomplete (en-US shipped, de-DE fetched from Google), per-feed-source 4-bucket stats, and the full v1 UI.

**Architecture:** Platform-native plugin (design spec `docs/superpowers/specs/2026-09-09-category-plugin-design.md`): rules = scoped PluginConfig (`["global","client"]`, `union_by_key` merge by rule id), manual assignments = PluginData, custom `register_routes` for taxonomy/stats/matches/product, stored-sidecar stats. Single `plugin.py` (loader is single-file, `backend/app/plugins/loader.py:40-47`); taxonomy ships as the operator's CSV in the plugin dir; fetched de-DE persists as a gitignored CSV next to it.

**Tech Stack:** Python 3.10+/FastAPI/SQLAlchemy 2.0 async (backend); React 19/Mantine/TanStack Query/dnd-kit/i18next (frontend).

## Global Constraints

- Work on cycle branch `m12-category` (off main `f4931cd`); keep main green; fast-forward merge at cycle end.
- No inline comments in code; module/function docstrings allowed (existing plugin files set the precedent).
- All frontend strings via `t()`; en+de i18n trees identical; namespace `category`; nav label `pluginNames.category` in `common.json`.
- 422 handling via `notifyApiError`; Loading/Empty/ErrorState on every data view; TanStack Query for all server state.
- TDD: RED → GREEN → commit. Backend commands from `backend/`: `uv run pytest …` (needs `TEST_DATABASE_URL`); frontend from `frontend/`: `npm test -- --run && npm run typecheck && npm run build`.
- `uv run pytest tests/test_plugin_contract.py` must pass after every task touching the plugin.
- Lint/type gates: `uv run ruff check .` (zero new in touched files), `uv run mypy .` (≤ 42 baseline, no new; snapshot `backend/docs/mypy-baseline.md`).
- **Plugin route handlers MUST patch `__annotations__` with real class objects before `router.<verb>(...)` registration** (PEP 563 string annotations + function-local imports: unpatched handlers break `app.openapi()` — verified empirically; `plugins/core/custom_labels/plugin.py:362-364` is the working pattern).
- Never mutate `original_product` in `process()`; `_`-prefixed keys are stripped from the content hash (`app/staging/hashing.py:8-17`) and never rendered to XML (`app/export/renderer.py:72-78`).
- Reserved plugin routes `/config` and `/data` must not be registered.
- Atomic file writes: temp file + `os.replace` for the fetched taxonomy.
- Docs update in the same commit as the behavior they describe. Never contradict `gmc-feed-engine-spec.md`.
- Frontend tests: `render` from `src/test/render.tsx`, fetch stubbing per `src/test/fetch.ts` + existing feature tests, `notifications.clean()` in `beforeEach`, `beforeAll(loadNamespaces)` for non-default namespaces, `useBlocker` needs a data router (`createMemoryRouter` + `RouterProvider`).
- Backend route tests: `app_factory` pattern from `backend/tests/test_custom_labels_preview.py:37-73` (`isolated_database_url`, `create_app`, manual router mount with prefix `/plugins/category`, login helper). Scope-guard precedent: `backend/tests/test_scope_enforcement.py` (scoped user + `UserClient` → 404).

---

### Task 1: Plugin scaffold + taxonomy subsystem

**Files:**
- Move: `taxonomy-with-ids.en-US.csv` → `plugins/core/category/taxonomy-with-ids.en-US.csv` (`git mv`)
- Create: `plugins/core/category/__init__.py` (empty)
- Create: `plugins/core/category/.gitignore`
- Create: `plugins/core/category/plugin.json`
- Create: `plugins/core/category/plugin.py` (taxonomy section + minimal plugin class)
- Create: `backend/tests/category_plugin_module.py`
- Create: `backend/tests/fixtures/category/taxonomy-with-ids.en-US.csv`, `backend/tests/fixtures/category/taxonomy-with-ids.de-DE.csv`, `backend/tests/fixtures/category/upstream.de-DE.txt`
- Test: `backend/tests/test_category_taxonomy.py`
- Modify: `backend/docs/plugins.md` (scope-table row)

**Interfaces:**
- Produces (module `plugins/core/category/plugin.py`; loaded app-side as `gmc_plugin_category`, in tests via `backend/tests/category_plugin_module.py` as `category_plugin`):
  - Constants: `OPERATORS = ("eq", "ne", "contains", "regex", "in")`, `DEFAULT_SOURCE_FIELD = "product_type"`, `MIN_TAXONOMY_ENTRIES = 1000`, `_LANGUAGE_FILES = {"en-US": "taxonomy-with-ids.en-US.csv", "de-DE": "taxonomy-with-ids.de-DE.csv"}`, `_FETCHABLE_LANGUAGES = ("de-DE",)`, `_FETCH_URL_TEMPLATE = "https://www.google.com/basepages/producttype/taxonomy-with-ids.{lang}.txt"`
  - `parse_taxonomy_csv(text: str) -> dict[str, str]` (id → path; raises ValueError)
  - `taxonomy_txt_to_csv(text: str) -> str`
  - `TaxonomyIndex` with `invalidate()`, `languages() -> list[str]`, `contains(taxonomy_id: str) -> bool`, `path(taxonomy_id, language) -> str | None`, `search(query, language, limit, offset) -> list[dict[str, str]]` (items `{"id", "path"}`)
  - `taxonomy_index() -> TaxonomyIndex` (module singleton), `_taxonomy_directory() -> Path` (test seam), `_fetch_url(url: str) -> bytes` (test seam)
  - `CategoryPlugin` with placeholder `validate_config` (pass) + `process` (pass-through) — real engine lands in Tasks 2–3

- [ ] **Step 1: Move the operator's taxonomy file and scaffold**

```bash
cd /home/ozon/gmc_feed_master
git mv taxonomy-with-ids.en-US.csv plugins/core/category/taxonomy-with-ids.en-US.csv
touch plugins/core/category/__init__.py
printf 'taxonomy-with-ids.de-DE.csv\n' > plugins/core/category/.gitignore
```

- [ ] **Step 2: Write the manifest** `plugins/core/category/plugin.json`

```json
{
  "id": "category",
  "name": "Category",
  "version": "1.0.0",
  "extension_point": "pipeline_module",
  "entry_point": "plugin:CategoryPlugin",
  "config_scope": ["global", "client"],
  "data_scope": ["global", "client"],
  "config_merge": {"rules": {"strategy": "union_by_key", "key": "id"}},
  "config_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Category",
    "properties": {
      "rules": {
        "type": "array",
        "title": "Rules",
        "items": {
          "type": "object",
          "properties": {
            "id": {"type": "string", "title": "ID"},
            "source_field": {"type": "string", "title": "Source field", "default": "product_type"},
            "operator": {"type": "string", "title": "Operator", "enum": ["eq", "ne", "contains", "regex", "in"]},
            "source_value": {"title": "Source value"},
            "taxonomy_id": {"type": "string", "title": "Taxonomy ID"},
            "is_excluded": {"type": "boolean", "title": "Excluded", "default": false}
          },
          "required": ["id", "source_field", "operator", "source_value"]
        }
      }
    }
  },
  "data_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Category data",
    "properties": {
      "assignments": {
        "type": "object",
        "title": "Manual assignments",
        "additionalProperties": {"type": "string"}
      }
    }
  }
}
```

No `frontend` section yet — it lands in Task 8 together with the component so every intermediate gate stays green.

- [ ] **Step 3: Write the shared test loader** `backend/tests/category_plugin_module.py`

```python
"""Single shared load of plugins/core/category/plugin.py for tests."""

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "category_plugin",
    Path(__file__).resolve().parents[2] / "plugins/core/category/plugin.py",
)
assert _spec is not None and _spec.loader is not None
category_plugin = importlib.util.module_from_spec(_spec)
sys.modules["category_plugin"] = category_plugin
_spec.loader.exec_module(category_plugin)
```

- [ ] **Step 4: Write the fixtures**

`backend/tests/fixtures/category/taxonomy-with-ids.en-US.csv`:

```
1,Animals & Pet Supplies,,,,,,
7385,Animals & Pet Supplies,Pet Supplies,Bird Supplies,Bird Cage Accessories,,,,
499954,Animals & Pet Supplies,Pet Supplies,Bird Supplies,Bird Cage Accessories,Bird Cage Bird Baths,,
166,Apparel & Accessories,,,,,,
53,Gift Cards,,,,,,
```

`backend/tests/fixtures/category/taxonomy-with-ids.de-DE.csv`:

```
1,Tiere & Tierbedarf,,,,,,
166,Bekleidung & Accessoires,,,,,,
5001,Sonstige,,,,,,
```

`backend/tests/fixtures/category/upstream.de-DE.txt`:

```
# Google Product Taxonomy (de-DE fixture)
1 - Tiere & Tierbedarf
166 - Bekleidung & Accessoires
5001 - Sonstiges > Kategorien, Allgemein
```

- [ ] **Step 5: Write the failing tests** `backend/tests/test_category_taxonomy.py`

```python
"""Category plugin taxonomy subsystem: CSV parsing, txt conversion, index."""

from pathlib import Path

import pytest

from tests.category_plugin_module import category_plugin as cp

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "category"


class TestParseTaxonomyCsv:
    def test_parses_simple_paths(self):
        entries = cp.parse_taxonomy_csv(
            "166,Apparel & Accessories,,,,,,\n53,Gift Cards,,,,,,\n"
        )
        assert entries == {"166": "Apparel & Accessories", "53": "Gift Cards"}

    def test_joins_segments_with_gt(self):
        entries = cp.parse_taxonomy_csv(
            "499954,Animals & Pet Supplies,Pet Supplies,Bird Supplies,"
            "Bird Cage Accessories,Bird Cage Bird Baths,,"
        )
        assert entries["499954"] == (
            "Animals & Pet Supplies > Pet Supplies > Bird Supplies > "
            "Bird Cage Accessories > Bird Cage Bird Baths"
        )

    def test_rejects_duplicate_ids(self):
        with pytest.raises(ValueError, match="duplicate"):
            cp.parse_taxonomy_csv("1,Animals,,,,,,\n1,Animals,,,,,,")

    def test_rejects_row_without_segments(self):
        with pytest.raises(ValueError, match="no path segments"):
            cp.parse_taxonomy_csv("1,,,,,,,")

    def test_skips_blank_rows(self):
        entries = cp.parse_taxonomy_csv("\n\n53,Gift Cards,,,,,,\n")
        assert entries == {"53": "Gift Cards"}

    def test_quoted_segment_containing_comma(self):
        entries = cp.parse_taxonomy_csv('5001,"Sonstiges > Kategorien, Allgemein",,,,,,')
        assert entries == {"5001": "Sonstiges > Kategorien, Allgemein"}


class TestTaxonomyTxtToCsv:
    def test_converts_official_format(self):
        csv_text = cp.taxonomy_txt_to_csv(
            "# header comment\n\n1 - Tiere & Tierbedarf\n"
            "166 - Bekleidung & Accessoires\n"
            "5001 - Sonstiges > Kategorien, Allgemein\n"
        )
        assert cp.parse_taxonomy_csv(csv_text) == {
            "1": "Tiere & Tierbedarf",
            "166": "Bekleidung & Accessoires",
            "5001": "Sonstiges > Kategorien, Allgemein",
        }

    def test_rejects_line_without_separator(self):
        with pytest.raises(ValueError, match="separator"):
            cp.taxonomy_txt_to_csv("1 Tiere & Tierbedarf\n")


class TestTaxonomyIndex:
    @pytest.fixture
    def index(self, monkeypatch):
        monkeypatch.setattr(cp, "_taxonomy_directory", lambda: FIXTURES)
        return cp.TaxonomyIndex()

    def test_languages_and_contains(self, index):
        assert index.languages() == ["en-US", "de-DE"]
        assert index.contains("166")
        assert not index.contains("999")

    def test_paths_merge_by_id_across_languages(self, index):
        assert index.path("166", "en-US") == "Apparel & Accessories"
        assert index.path("166", "de-DE") == "Bekleidung & Accessoires"
        assert index.path("5001", "en-US") is None
        assert index.path("5001", "de-DE") == "Sonstige"

    def test_search_ranks_starts_with_before_contains(self, index):
        results = index.search("bird", "en-US", limit=10, offset=0)
        assert [item["id"] for item in results] == ["7385", "499954"]

    def test_search_case_insensitive_and_offset(self, index):
        assert [item["id"] for item in index.search("ANIMALS", "en-US", 10, 0)][:1] == ["1"]
        assert len(index.search("", "en-US", 2, 0)) == 2
        assert len(index.search("", "en-US", 2, 4)) == 1

    def test_invalidate_rebuilds_when_new_file_appears(self, index, monkeypatch, tmp_path):
        monkeypatch.setattr(cp, "_taxonomy_directory", lambda: tmp_path)
        (tmp_path / "taxonomy-with-ids.en-US.csv").write_text(
            "53,Gift Cards,,,,,,\n", encoding="utf-8"
        )
        assert index.languages() == ["en-US"]
        (tmp_path / "taxonomy-with-ids.de-DE.csv").write_text(
            "53,Geschenkgutscheine,,,,,,\n", encoding="utf-8"
        )
        index.invalidate()
        assert index.languages() == ["en-US", "de-DE"]
        assert index.path("53", "de-DE") == "Geschenkgutscheine"


class TestSingleton:
    def test_taxonomy_index_cached_and_directory_seam(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cp, "_taxonomy_directory", lambda: tmp_path)
        monkeypatch.setattr(cp, "_INDEX", None)
        assert cp.taxonomy_index() is cp.taxonomy_index()
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest tests/test_category_taxonomy.py -v`
Expected: FAIL — `AttributeError: module 'category_plugin' has no attribute 'parse_taxonomy_csv'`

- [ ] **Step 7: Implement** `plugins/core/category/plugin.py`

```python
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
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest tests/test_category_taxonomy.py -v`
Expected: PASS (12 tests)

- [ ] **Step 9: Run the contract suites**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest tests/test_plugin_contract.py tests/test_example_plugin_contract.py -v`
Expected: PASS

- [ ] **Step 10: Update `backend/docs/plugins.md`** — add the Category row to the scope table mirroring the custom_labels row:

```markdown
| `category` | `["global", "client"]` (rules, `union_by_key` by `id`) | `["global", "client"]` (client: manual assignments) | Google Product Taxonomy is market-independent; client-wide rule sharing is intentional (spec §5.3) |
```

- [ ] **Step 11: Commit**

```bash
cd /home/ozon/gmc_feed_master
git add plugins/core/category backend/tests/category_plugin_module.py backend/tests/fixtures/category backend/tests/test_category_taxonomy.py backend/docs/plugins.md
git commit -m "feat(category): plugin scaffold + taxonomy CSV parser/index"
```


---

### Task 2: Rule engine + validate_config

**Files:**
- Modify: `plugins/core/category/plugin.py` (append rule-engine section; replace placeholder `validate_config`)
- Test: `backend/tests/test_category_rules.py`

**Interfaces:**
- Consumes: `taxonomy_index()` (Task 1).
- Produces: `resolve_path(product: dict, path: str) -> list[str]`; `compile_rule(rule: dict) -> dict` (keys: `id`, `source_field`, `operator`, `values: tuple[str, ...]`, `pattern: re.Pattern | None`, `taxonomy_id: str`, `is_excluded: bool`); `rule_matches(compiled: dict, product: dict) -> bool`; `apply_category(product: dict, rules: list, assignments: dict) -> dict | None` (outcome keys: `taxonomy_id: str`, `provenance: "manual" | "auto" | "excluded"`, `rule_id: str | None`; `None` = uncategorized); `validate_config(config: Any) -> None` (raises ValueError). `CategoryPlugin.validate_config` delegates to it.

- [ ] **Step 1: Write the failing tests** `backend/tests/test_category_rules.py`

```python
"""Category plugin rule engine + validate_config."""

from pathlib import Path

import pytest

from tests.category_plugin_module import category_plugin as cp

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "category"


@pytest.fixture(autouse=True)
def fixture_taxonomy(monkeypatch):
    monkeypatch.setattr(cp, "_taxonomy_directory", lambda: FIXTURES)
    monkeypatch.setattr(cp, "_INDEX", None)


def _rule(**over):
    rule = {
        "id": "r1",
        "source_field": "product_type",
        "operator": "eq",
        "source_value": "Shoes",
        "taxonomy_id": "166",
        "is_excluded": False,
    }
    rule.update(over)
    return rule


class TestResolvePath:
    def test_scalar(self):
        assert cp.resolve_path({"product_type": "Shoes"}, "product_type") == ["Shoes"]

    def test_repeated_scalar_skips_empty(self):
        assert cp.resolve_path({"product_type": ["A", ""]}, "product_type") == ["A"]

    def test_subfield(self):
        assert cp.resolve_path({"shipping": {"country": "DE"}}, "shipping.country") == ["DE"]

    def test_missing(self):
        assert cp.resolve_path({}, "product_type") == []


class TestRuleMatches:
    def test_eq_is_case_and_whitespace_insensitive(self):
        compiled = cp.compile_rule(_rule(source_value="  shoes "))
        assert cp.rule_matches(compiled, {"product_type": "  SHOES "})

    def test_ne_true_when_no_candidate_equals(self):
        compiled = cp.compile_rule(_rule(operator="ne", source_value="Hats"))
        assert cp.rule_matches(compiled, {"product_type": "Shoes"})
        assert not cp.rule_matches(compiled, {"product_type": "shoes"})

    def test_ne_true_when_field_missing(self):
        compiled = cp.compile_rule(_rule(operator="ne", source_value="Hats"))
        assert cp.rule_matches(compiled, {})

    def test_contains_is_case_sensitive(self):
        compiled = cp.compile_rule(_rule(operator="contains", source_value="Shoe"))
        assert cp.rule_matches(compiled, {"product_type": "Big Shoe Rack"})
        assert not cp.rule_matches(compiled, {"product_type": "shoe rack"})

    def test_regex_searches(self):
        compiled = cp.compile_rule(_rule(operator="regex", source_value=r"^sh\d{2}$"))
        assert cp.rule_matches(compiled, {"product_type": "sh42"})
        assert not cp.rule_matches(compiled, {"product_type": "sh4"})

    def test_in_matches_list_members_stripped(self):
        compiled = cp.compile_rule(_rule(operator="in", source_value=["Boots", " Shoes "]))
        assert cp.rule_matches(compiled, {"product_type": "Shoes"})
        assert not cp.rule_matches(compiled, {"product_type": "Socks"})

    def test_default_source_field_is_product_type(self):
        compiled = cp.compile_rule(
            {"id": "r", "operator": "eq", "source_value": "x", "taxonomy_id": "1"}
        )
        assert compiled["source_field"] == "product_type"


class TestApplyCategory:
    RULES = [
        cp.compile_rule(_rule(id="r-auto", taxonomy_id="166")),
        cp.compile_rule(_rule(id="r-second", source_value="Boots", taxonomy_id="53")),
    ]

    def test_manual_assignment_wins_before_rules(self):
        outcome = cp.apply_category(
            {"id": "p1", "product_type": "Shoes"}, self.RULES, {"p1": "53"}
        )
        assert outcome == {"taxonomy_id": "53", "provenance": "manual", "rule_id": None}

    def test_first_matching_rule_wins(self):
        outcome = cp.apply_category(
            {"id": "p1", "product_type": "Shoes"}, self.RULES, {}
        )
        assert outcome == {"taxonomy_id": "166", "provenance": "auto", "rule_id": "r-auto"}

    def test_excluded_rule_sets_empty_taxonomy(self):
        rules = [cp.compile_rule(_rule(id="r-x", is_excluded=True))]
        outcome = cp.apply_category({"id": "p1", "product_type": "Shoes"}, rules, {})
        assert outcome == {"taxonomy_id": "", "provenance": "excluded", "rule_id": "r-x"}

    def test_no_match_returns_none(self):
        assert cp.apply_category({"id": "p1", "product_type": "Socks"}, self.RULES, {}) is None


class TestValidateConfig:
    def test_empty_config_passes(self):
        cp.validate_config({})
        cp.validate_config(None)

    def test_valid_config_passes(self):
        cp.validate_config({"rules": [_rule(), _rule(id="r2", taxonomy_id="53")]})

    def test_rejects_non_list_rules(self):
        with pytest.raises(ValueError, match="array"):
            cp.validate_config({"rules": {}})

    def test_rejects_missing_id(self):
        with pytest.raises(ValueError, match="id"):
            cp.validate_config(
                {"rules": [{"operator": "eq", "source_value": "x", "taxonomy_id": "1"}]}
            )

    def test_rejects_duplicate_ids(self):
        with pytest.raises(ValueError, match="duplicate"):
            cp.validate_config({"rules": [_rule(), _rule()]})

    def test_rejects_unknown_operator(self):
        with pytest.raises(ValueError, match="operator"):
            cp.validate_config({"rules": [_rule(operator="nope")]})

    def test_in_requires_array_source_value(self):
        with pytest.raises(ValueError, match="array"):
            cp.validate_config({"rules": [_rule(operator="in", source_value="Shoes")]})

    def test_rejects_bad_regex(self):
        with pytest.raises(ValueError, match="regex"):
            cp.validate_config({"rules": [_rule(operator="regex", source_value="([)")]})

    def test_taxonomy_id_required_unless_excluded(self):
        with pytest.raises(ValueError, match="taxonomy_id"):
            cp.validate_config({"rules": [_rule(taxonomy_id=None)]})
        cp.validate_config({"rules": [_rule(taxonomy_id=None, is_excluded=True)]})

    def test_rejects_unknown_taxonomy_id(self):
        with pytest.raises(ValueError, match="not found"):
            cp.validate_config({"rules": [_rule(taxonomy_id="99999999")]})


class TestPluginValidateConfigDelegates:
    def test_delegates(self):
        plugin = cp.CategoryPlugin()
        plugin.validate_config({})
        with pytest.raises(ValueError, match="array"):
            plugin.validate_config({"rules": {}})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest tests/test_category_rules.py -v`
Expected: FAIL — `AttributeError: ... no attribute 'resolve_path'`

- [ ] **Step 3: Implement** — add `import re` to the top imports of `plugins/core/category/plugin.py`, append the rule-engine section after the taxonomy section, and replace the placeholder `validate_config` method.

```python
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
```

In `class CategoryPlugin`, replace the placeholder method:

```python
    def validate_config(self, config: Any) -> None:
        validate_config(config)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest tests/test_category_rules.py tests/test_category_taxonomy.py -v`
Expected: PASS

- [ ] **Step 5: Run the contract suite**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest tests/test_plugin_contract.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /home/ozon/gmc_feed_master
git add plugins/core/category/plugin.py backend/tests/test_category_rules.py
git commit -m "feat(category): rule engine + validate_config"
```


---

### Task 3: prepare_run/process with sidecars + pipeline integration tests

**Files:**
- Modify: `plugins/core/category/plugin.py` (add `_build_state`, `prepare_run`; replace placeholder `process`)
- Test: `backend/tests/test_category_plugin.py`
- Modify: `backend/docs/data-model.md` (sidecar note)

**Interfaces:**
- Consumes: `compile_rule`, `apply_category` (Task 2).
- Produces: `_build_state(config: Any, data: Any) -> dict` (keys `rules: list[dict]`, `assignments: dict[str, str]`); `CategoryPlugin.prepare_run(self, config, data, ctx) -> dict`; `CategoryPlugin.process(self, product, config, data, ctx, state=None) -> dict` attaching `google_product_category`, `_category_provenance` (`manual|auto|excluded`), `_category_rule_id` (auto/excluded only). `process` still accepts the 4-arg contract call.

- [ ] **Step 1: Write the failing tests** `backend/tests/test_category_plugin.py`

Before writing the renderer fixture, read `backend/registry/model.py` and copy the minimal `RegistryDocument`/`RegistryAttribute` construction from an existing renderer test (search `backend/tests/` for `render_feed(`) — field names must match the real model.

```python
"""Category plugin process semantics, sidecar exclusion, config-hash reprocess."""

import copy
import logging

from app.plugins.runtime import RunContext
from app.staging.hashing import content_hash
from tests.category_plugin_module import category_plugin as cp

CONFIG = {"rules": [
    {"id": "r-auto", "source_field": "product_type", "operator": "eq",
     "source_value": "Shoes", "taxonomy_id": "166", "is_excluded": False},
]}
DATA = {"assignments": {"p-manual": "53"}}


def _ctx(product=None):
    return RunContext(
        client_id=0, feed_source_id=0, run_id=0,
        logger=logging.getLogger("category-test"),
        original_product=copy.deepcopy(product or {}),
    )


class TestProcess:
    def test_manual_assignment_wins(self):
        plugin = cp.CategoryPlugin()
        state = plugin.prepare_run(CONFIG, DATA, _ctx())
        product = {"id": "p-manual", "product_type": "Shoes", "title": "Boot"}
        result = plugin.process(product, CONFIG, DATA, _ctx(product), state=state)
        assert result["google_product_category"] == "53"
        assert result["_category_provenance"] == "manual"
        assert "_category_rule_id" not in result

    def test_auto_rule_sets_provenance_and_rule_id(self):
        plugin = cp.CategoryPlugin()
        state = plugin.prepare_run(CONFIG, DATA, _ctx())
        product = {"id": "p-auto", "product_type": "Shoes"}
        result = plugin.process(product, CONFIG, DATA, _ctx(product), state=state)
        assert result["google_product_category"] == "166"
        assert result["_category_provenance"] == "auto"
        assert result["_category_rule_id"] == "r-auto"

    def test_uncategorized_product_untouched(self):
        plugin = cp.CategoryPlugin()
        state = plugin.prepare_run(CONFIG, DATA, _ctx())
        product = {"id": "p-none", "product_type": "Socks"}
        result = plugin.process(product, CONFIG, DATA, _ctx(product), state=state)
        assert result == product
        assert "_category_provenance" not in result

    def test_empty_config_passthrough(self):
        plugin = cp.CategoryPlugin()
        product = {"id": "p1", "title": "x"}
        assert plugin.process(product, {}, {}, _ctx(product)) is product

    def test_original_product_not_mutated(self):
        plugin = cp.CategoryPlugin()
        state = plugin.prepare_run(CONFIG, DATA, _ctx())
        product = {"id": "p-auto", "product_type": "Shoes"}
        original = copy.deepcopy(product)
        plugin.process(product, CONFIG, DATA, _ctx(product), state=state)
        assert product == original

    def test_process_without_state_builds_from_config_data(self):
        plugin = cp.CategoryPlugin()
        product = {"id": "p-auto", "product_type": "Shoes"}
        result = plugin.process(product, CONFIG, DATA, _ctx(product))
        assert result["_category_provenance"] == "auto"


class TestSidecarExclusion:
    def test_sidecars_do_not_change_content_hash(self):
        with_sidecars = {
            "id": "p1", "title": "Shoe", "google_product_category": "166",
            "_category_provenance": "auto", "_category_rule_id": "r-auto",
        }
        without = {"id": "p1", "title": "Shoe", "google_product_category": "166"}
        assert content_hash(with_sidecars) == content_hash(without)

    def test_sidecars_never_reach_xml(self):
        from app.export.renderer import ChannelMetadata, render_feed
        from tests.support_registry import minimal_gmc_registry

        registry = minimal_gmc_registry()
        product = {
            "id": "p1", "title": "Shoe", "google_product_category": "166",
            "_category_provenance": "auto", "_category_rule_id": "r-auto",
        }
        xml = render_feed([product], registry, ChannelMetadata("t", "l", "d")).decode()
        assert "<g:google_product_category>166</g:google_product_category>" in xml
        assert "_category" not in xml


class TestConfigHashReprocess:
    def _bundle(self, resolved_config, resolved_data):
        return {
            "pipeline": None,
            "instances": [{
                "position": 0, "plugin": "category", "plugin_version": "1.0.0",
                "instance_config": {},
                "resolved_config": resolved_config,
                "resolved_data": resolved_data,
            }],
        }

    def test_unchanged_bundle_hash_stable(self):
        assert content_hash(self._bundle(CONFIG, DATA)) == content_hash(
            self._bundle(copy.deepcopy(CONFIG), copy.deepcopy(DATA))
        )

    def test_rule_edit_changes_hash(self):
        edited = {"rules": [{**CONFIG["rules"][0], "taxonomy_id": "53"}]}
        assert content_hash(self._bundle(edited, DATA)) != content_hash(
            self._bundle(CONFIG, DATA)
        )

    def test_assignment_edit_changes_hash(self):
        edited = {"assignments": {"p-manual": "166"}}
        assert content_hash(self._bundle(CONFIG, edited)) != content_hash(
            self._bundle(CONFIG, DATA)
        )
```

The `tests.support_registry.minimal_gmc_registry()` helper does not exist yet — create `backend/tests/support_registry.py` with a two-attribute `RegistryDocument` (title + google_product_category, both SCALAR/OPTIONAL/EXPORTABLE). Copy the exact constructor shape from `backend/registry/model.py` (read it first; `test_custom_labels_preview.py:19-27` shows the imports).

```python
"""Minimal two-attribute GMC registry for renderer tests."""

from registry.model import (
    AttributeKind, ExportStatus, FeedDomain, RegistryAttribute, RegistryDocument,
    RequirementStatus,
)


def minimal_gmc_registry() -> RegistryDocument:
    return RegistryDocument(
        domain=FeedDomain.GMC,
        attributes={
            "title": RegistryAttribute(
                name="title", kind=AttributeKind.SCALAR,
                requirement=RequirementStatus.OPTIONAL,
                export_status=ExportStatus.EXPORTABLE, fields=(),
            ),
            "google_product_category": RegistryAttribute(
                name="google_product_category", kind=AttributeKind.SCALAR,
                requirement=RequirementStatus.OPTIONAL,
                export_status=ExportStatus.EXPORTABLE, fields=(),
            ),
        },
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest tests/test_category_plugin.py -v`
Expected: FAIL — `CategoryPlugin` has no `prepare_run`

- [ ] **Step 3: Implement** — in `plugins/core/category/plugin.py`, add `_build_state` after `validate_config` and update `CategoryPlugin`:

```python
def _build_state(config: Any, data: Any) -> dict[str, Any]:
    rules = (config or {}).get("rules") or []
    assignments = (data or {}).get("assignments") or {}
    return {
        "rules": [compile_rule(rule) for rule in rules if isinstance(rule, dict)],
        "assignments": {str(key): str(value) for key, value in assignments.items()},
    }
```

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest tests/test_category_plugin.py tests/test_category_rules.py tests/test_category_taxonomy.py tests/test_plugin_contract.py -v`
Expected: PASS (contract suite green with prepare_run + state param)

- [ ] **Step 5: Update `backend/docs/data-model.md`** — append to the "Config Hash" section:

```markdown
- The Category plugin attaches `_category_provenance` and `_category_rule_id` sidecars to `staging_products.processed_data`; they are stripped from the content hash (`strip_derived`) and never rendered to XML, and are read by the plugin's stats/matches routes.
```

- [ ] **Step 6: Commit**

```bash
cd /home/ozon/gmc_feed_master
git add plugins/core/category/plugin.py backend/tests/test_category_plugin.py backend/tests/support_registry.py backend/docs/data-model.md
git commit -m "feat(category): prepare_run/process with provenance sidecars"
```


---

### Task 4: Taxonomy + draft-validate routes

**Files:**
- Modify: `plugins/core/category/plugin.py` (add `register_routes`)
- Test: `backend/tests/test_category_routes.py`

**Interfaces:**
- Consumes: Task 1 taxonomy functions + singleton; Task 2 `validate_config`.
- Produces (mounted under `/plugins/category` by `discover_and_mount`, `backend/app/plugins/discovery.py:141`):
  - `POST /validate` body `{"rules": [...]}` → `{"status": "ok"}` | 422 `{"errors": [str]}`
  - `GET /taxonomy/languages` → `{"languages": [...]}`
  - `GET /taxonomy/search?language&q&limit&offset` → `{"items": [{"id","path"}]}`; 422 unknown language
  - `GET /taxonomy/validate?taxonomy_id` → `{"valid": bool, "path": str | null}`
  - `POST /taxonomy/fetch` body `{"language": "de-DE"}` → `{"status": "ok", "language", "entries"}` | 422 not fetchable | 502 upstream | 500 unwritable

- [ ] **Step 1: Write the failing tests** `backend/tests/test_category_routes.py`

```python
"""Category plugin routes: taxonomy endpoints + draft validation."""

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.staging import StagingProduct
from app.models.user import User
from app.persistence.users import seed_initial_user
from tests.category_plugin_module import category_plugin as cp

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "category"

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_factory(isolated_database_url, monkeypatch):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
            await session.execute(delete(StagingProduct))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="pw",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    router = APIRouter()
    cp.CategoryPlugin().register_routes(router)
    app.include_router(router, prefix="/plugins/category")
    yield app, factory, monkeypatch
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


def point_taxonomy_at_fixtures(monkeypatch):
    monkeypatch.setattr(cp, "_taxonomy_directory", lambda: FIXTURES)
    monkeypatch.setattr(cp, "_INDEX", None)


class TestValidateRoute:
    async def test_valid_draft_ok(self, app_factory):
        client = await logged_in_client(app_factory)
        point_taxonomy_at_fixtures(app_factory[2])
        resp = await client.post("/plugins/category/validate", json={
            "rules": [{"id": "r1", "source_field": "product_type", "operator": "eq",
                        "source_value": "Shoes", "taxonomy_id": "166"}],
        })
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_invalid_draft_422(self, app_factory):
        client = await logged_in_client(app_factory)
        resp = await client.post("/plugins/category/validate", json={
            "rules": [{"id": "r1", "operator": "nope", "source_value": "x",
                        "taxonomy_id": "1"}],
        })
        assert resp.status_code == 422
        assert resp.json()["errors"]


class TestTaxonomyRoutes:
    async def test_languages_and_invalidation(self, app_factory, tmp_path):
        _, _, mp = app_factory
        mp.setattr(cp, "_taxonomy_directory", lambda: tmp_path)
        mp.setattr(cp, "_INDEX", None)
        (tmp_path / "taxonomy-with-ids.en-US.csv").write_text(
            "1,Animals,,,,,,\n", encoding="utf-8"
        )
        client = await logged_in_client(app_factory)
        resp = await client.get("/plugins/category/taxonomy/languages")
        assert resp.json() == {"languages": ["en-US"]}
        (tmp_path / "taxonomy-with-ids.de-DE.csv").write_text(
            "1,Tiere,,,,,,\n", encoding="utf-8"
        )
        cp.taxonomy_index().invalidate()
        resp = await client.get("/plugins/category/taxonomy/languages")
        assert resp.json() == {"languages": ["en-US", "de-DE"]}

    async def test_search_ranks_and_422s_unknown_language(self, app_factory):
        client = await logged_in_client(app_factory)
        point_taxonomy_at_fixtures(app_factory[2])
        resp = await client.get(
            "/plugins/category/taxonomy/search?language=en-US&q=bird&limit=10&offset=0"
        )
        assert [item["id"] for item in resp.json()["items"]] == ["7385", "499954"]
        resp = await client.get("/plugins/category/taxonomy/search?language=xx-XX&q=bird")
        assert resp.status_code == 422

    async def test_taxonomy_validate(self, app_factory):
        client = await logged_in_client(app_factory)
        point_taxonomy_at_fixtures(app_factory[2])
        resp = await client.get("/plugins/category/taxonomy/validate?taxonomy_id=166")
        assert resp.json() == {"valid": True, "path": "Apparel & Accessories"}
        resp = await client.get("/plugins/category/taxonomy/validate?taxonomy_id=999")
        assert resp.json() == {"valid": False, "path": None}


class TestFetchRoute:
    async def test_fetch_rejects_unknown_language(self, app_factory):
        client = await logged_in_client(app_factory)
        resp = await client.post("/plugins/category/taxonomy/fetch", json={"language": "fr-FR"})
        assert resp.status_code == 422

    async def test_fetch_de_de_converts_and_persists(self, app_factory, tmp_path):
        _, _, mp = app_factory
        mp.setattr(cp, "_taxonomy_directory", lambda: tmp_path)
        mp.setattr(cp, "_INDEX", None)
        (tmp_path / "taxonomy-with-ids.en-US.csv").write_text(
            "1,Animals,,,,,,\n", encoding="utf-8"
        )
        upstream = FIXTURES.joinpath("upstream.de-DE.txt").read_text(encoding="utf-8")

        async def fake_fetch(url):
            assert "taxonomy-with-ids.de-DE.txt" in url
            return upstream.encode("utf-8")

        mp.setattr(cp, "_fetch_url", fake_fetch)
        mp.setattr(cp, "MIN_TAXONOMY_ENTRIES", 2)
        client = await logged_in_client(app_factory)
        resp = await client.post("/plugins/category/taxonomy/fetch", json={"language": "de-DE"})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "language": "de-DE", "entries": 3}
        stored = cp.parse_taxonomy_csv(
            (tmp_path / "taxonomy-with-ids.de-DE.csv").read_text(encoding="utf-8")
        )
        assert stored["5001"] == "Sonstiges > Kategorien, Allgemein"
        langs = await client.get("/plugins/category/taxonomy/languages")
        assert langs.json() == {"languages": ["en-US", "de-DE"]}

    async def test_fetch_upstream_failure_502(self, app_factory, tmp_path):
        _, _, mp = app_factory
        mp.setattr(cp, "_taxonomy_directory", lambda: tmp_path)
        mp.setattr(cp, "_INDEX", None)

        async def failing_fetch(url):
            raise RuntimeError("boom")

        mp.setattr(cp, "_fetch_url", failing_fetch)
        client = await logged_in_client(app_factory)
        resp = await client.post("/plugins/category/taxonomy/fetch", json={"language": "de-DE"})
        assert resp.status_code == 502

    async def test_fetch_upstream_too_small_502(self, app_factory, tmp_path):
        _, _, mp = app_factory
        mp.setattr(cp, "_taxonomy_directory", lambda: tmp_path)
        mp.setattr(cp, "_INDEX", None)

        async def tiny_fetch(url):
            return "1 - Tiere & Tierbedarf\n".encode("utf-8")

        mp.setattr(cp, "_fetch_url", tiny_fetch)
        client = await logged_in_client(app_factory)
        resp = await client.post("/plugins/category/taxonomy/fetch", json={"language": "de-DE"})
        assert resp.status_code == 502
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest tests/test_category_routes.py -v`
Expected: FAIL — `AttributeError: 'CategoryPlugin' object has no attribute 'register_routes'`

- [ ] **Step 3: Implement `register_routes`** — append the method to `class CategoryPlugin` (add `import os` to the module's top imports):

```python
    def register_routes(self, router: Any) -> None:
        from fastapi import Depends, HTTPException, Query
        from fastapi.responses import JSONResponse
        from pydantic import BaseModel, Field

        from app.access import CurrentUser, get_current_user

        class ValidateRequest(BaseModel):
            rules: list[dict[str, Any]] = Field(default_factory=list)

        class FetchRequest(BaseModel):
            language: str

        async def validate_rules(payload, user=Depends(get_current_user)):
            try:
                validate_config({"rules": payload.rules} if payload.rules else {})
            except ValueError as exc:
                return JSONResponse(status_code=422, content={"errors": [str(exc)]})
            return {"status": "ok"}

        validate_rules.__annotations__.update({
            "payload": ValidateRequest, "user": CurrentUser,
            "return": dict[str, Any] | JSONResponse,
        })
        router.post("/validate", response_model=None)(validate_rules)

        async def taxonomy_languages(user=Depends(get_current_user)):
            return {"languages": taxonomy_index().languages()}

        taxonomy_languages.__annotations__.update({
            "user": CurrentUser, "return": dict[str, Any],
        })
        router.get("/taxonomy/languages")(taxonomy_languages)

        async def taxonomy_search(language, q="", limit=Query(default=20, ge=1, le=100),
                                   offset=Query(default=0, ge=0),
                                   user=Depends(get_current_user)):
            index = taxonomy_index()
            if language not in index.languages():
                raise HTTPException(
                    status_code=422, detail=f"unknown taxonomy language {language!r}"
                )
            return {"items": index.search(q, language, limit, offset)}

        taxonomy_search.__annotations__.update({
            "language": str, "q": str, "limit": int, "offset": int,
            "user": CurrentUser, "return": dict[str, Any],
        })
        router.get("/taxonomy/search", response_model=None)(taxonomy_search)

        async def taxonomy_validate(taxonomy_id, user=Depends(get_current_user)):
            index = taxonomy_index()
            valid = index.contains(taxonomy_id)
            return {
                "valid": valid,
                "path": index.path(taxonomy_id, index.languages()[0]) if valid else None,
            }

        taxonomy_validate.__annotations__.update({
            "taxonomy_id": str, "user": CurrentUser, "return": dict[str, Any],
        })
        router.get("/taxonomy/validate", response_model=None)(taxonomy_validate)

        async def fetch_language(payload, user=Depends(get_current_user)):
            if payload.language not in _FETCHABLE_LANGUAGES:
                raise HTTPException(
                    status_code=422,
                    detail=f"language must be one of {', '.join(_FETCHABLE_LANGUAGES)}",
                )
            try:
                content = await _fetch_url(
                    _FETCH_URL_TEMPLATE.format(lang=payload.language)
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=502, detail=f"upstream fetch failed: {exc}"
                ) from exc
            try:
                csv_text = taxonomy_txt_to_csv(content.decode("utf-8"))
                entries = parse_taxonomy_csv(csv_text)
                if len(entries) < MIN_TAXONOMY_ENTRIES:
                    raise ValueError(
                        f"only {len(entries)} entries, expected at least "
                        f"{MIN_TAXONOMY_ENTRIES}"
                    )
            except (ValueError, UnicodeDecodeError) as exc:
                raise HTTPException(
                    status_code=502, detail=f"upstream taxonomy invalid: {exc}"
                ) from exc
            target = _taxonomy_directory() / _LANGUAGE_FILES[payload.language]
            tmp = target.with_name(target.name + ".tmp")
            try:
                tmp.write_text(csv_text, encoding="utf-8")
                os.replace(tmp, target)
            except OSError as exc:
                raise HTTPException(
                    status_code=500, detail=f"cannot write taxonomy file: {exc}"
                ) from exc
            taxonomy_index().invalidate()
            return {
                "status": "ok",
                "language": payload.language,
                "entries": len(entries),
            }

        fetch_language.__annotations__.update({
            "payload": FetchRequest, "user": CurrentUser, "return": dict[str, Any],
        })
        router.post("/taxonomy/fetch", response_model=None)(fetch_language)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest tests/test_category_routes.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Verify OpenAPI generation stays healthy**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run python -c "
from fastapi import FastAPI, APIRouter
from tests.category_plugin_module import category_plugin as cp
app = FastAPI()
r = APIRouter()
cp.CategoryPlugin().register_routes(r)
app.include_router(r, prefix='/plugins/category')
paths = app.openapi()['paths']
expected = ['/plugins/category/validate', '/plugins/category/taxonomy/languages',
            '/plugins/category/taxonomy/search', '/plugins/category/taxonomy/validate',
            '/plugins/category/taxonomy/fetch']
assert sorted(paths) == sorted(expected), paths
print('OK')
"`
Expected: `OK`

- [ ] **Step 6: Run the contract suite**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest tests/test_plugin_contract.py -v`
Expected: PASS (reserved-route check sees none of the new paths colliding)

- [ ] **Step 7: Commit**

```bash
cd /home/ozon/gmc_feed_master
git add plugins/core/category/plugin.py backend/tests/test_category_routes.py
git commit -m "feat(category): taxonomy + draft-validate routes"
```


---

### Task 5: Stats / matches / product routes

**Files:**
- Modify: `plugins/core/category/plugin.py` (extend `register_routes`)
- Modify: `backend/docs/api.md` (document ALL category routes incl. Task 4's)
- Test: `backend/tests/test_category_stats.py`

**Interfaces:**
- Consumes: `StagingProduct.processed_data` JSONB (models/staging.py:22) with `.astext` access (routes/products.py:19-25 precedent); `ensure_feed_source_access` (access.py:126); scoped-user seeding pattern (test_scope_enforcement.py:25-47).
- Produces (under `/plugins/category`):
  - `GET /stats?feed_source_id` → `{"total": int, "buckets": {"manual","auto","excluded","uncategorized"}, "rules": {rule_id: count}}`
  - `GET /matches?feed_source_id&rule_id&limit&offset` → `{"total": int, "items": [{"product_id","title"}]}`
  - `GET /product?feed_source_id&product_id` → `{"product_id","title","provenance","rule_id","google_product_category","status"}`; 404 unknown product
  - All three: 404 unknown feed source; scoped users get 404 on foreign feed sources

- [ ] **Step 1: Write the failing tests** `backend/tests/test_category_stats.py`

```python
"""Category stats/matches/product routes: buckets, paging, cross-tenant guard."""

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.staging import StagingProduct
from app.models.user import User
from app.persistence.users import hash_password, seed_initial_user
from tests.category_plugin_module import category_plugin as cp

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
            await session.execute(delete(StagingProduct))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="pw",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    router = APIRouter()
    cp.CategoryPlugin().register_routes(router)
    app.include_router(router, prefix="/plugins/category")
    yield app, factory
    await engine.dispose()


async def login(app, username, password):
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200
    return client


async def admin_client(app_factory):
    app, _ = app_factory
    return await login(app, "operator", "pw")


async def _setup_feed(factory, client):
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (
        await client.post(
            f"/clients/{created['id']}/feed-sources",
            json={"name": "DE", "source_format": "wide_tsv"},
        )
    ).json()
    rows = [
        ("p-manual",
         {"id": "p-manual", "title": "Manual Boot", "google_product_category": "53"},
         {"id": "p-manual", "title": "Manual Boot", "google_product_category": "53",
          "_category_provenance": "manual"}),
        ("p-auto",
         {"id": "p-auto", "title": "Auto Shoe", "google_product_category": "166"},
         {"id": "p-auto", "title": "Auto Shoe", "google_product_category": "166",
          "_category_provenance": "auto", "_category_rule_id": "r-auto"}),
        ("p-excl",
         {"id": "p-excl", "title": "Excluded Sock", "google_product_category": ""},
         {"id": "p-excl", "title": "Excluded Sock", "google_product_category": "",
          "_category_provenance": "excluded", "_category_rule_id": "r-excl"}),
        ("p-none",
         {"id": "p-none", "title": "Naked Hat"},
         {"id": "p-none", "title": "Naked Hat"}),
        ("p-removed",
         {"id": "p-removed", "title": "Gone"},
         {"id": "p-removed", "title": "Gone"}),
    ]
    async with factory() as session, session.begin():
        run = IngestionRun(feed_source_id=feed["id"], status="success",
                           started_at=datetime.now(timezone.utc))
        session.add(run)
        await session.flush()
        for pid, raw, processed in rows:
            status = "removed" if pid == "p-removed" else "active"
            session.add(StagingProduct(
                feed_source_id=feed["id"], ingestion_run_id=run.id, product_id=pid,
                content_hash="x", config_hash="x", status=status, excluded=False,
                raw_data=raw, processed_data=processed,
            ))
    return feed


class TestStats:
    async def test_buckets_and_rule_counts(self, app_factory):
        client = await admin_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client)
        resp = await client.get(f"/plugins/category/stats?feed_source_id={feed['id']}")
        assert resp.status_code == 200
        assert resp.json() == {
            "total": 4,
            "buckets": {"manual": 1, "auto": 1, "excluded": 1, "uncategorized": 1},
            "rules": {"r-auto": 1, "r-excl": 1},
        }

    async def test_unknown_feed_source_404(self, app_factory):
        client = await admin_client(app_factory)
        resp = await client.get("/plugins/category/stats?feed_source_id=99999")
        assert resp.status_code == 404


class TestMatches:
    async def test_paged_matches_with_titles(self, app_factory):
        client = await admin_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client)
        resp = await client.get(
            f"/plugins/category/matches?feed_source_id={feed['id']}"
            f"&rule_id=r-auto&limit=50&offset=0"
        )
        assert resp.json() == {
            "total": 1,
            "items": [{"product_id": "p-auto", "title": "Auto Shoe"}],
        }

    async def test_unknown_rule_matches_nothing(self, app_factory):
        client = await admin_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client)
        resp = await client.get(
            f"/plugins/category/matches?feed_source_id={feed['id']}"
            f"&rule_id=r-none&limit=50&offset=0"
        )
        assert resp.json() == {"total": 0, "items": []}


class TestProductRoute:
    async def test_product_state(self, app_factory):
        client = await admin_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client)
        resp = await client.get(
            f"/plugins/category/product?feed_source_id={feed['id']}&product_id=p-auto"
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "product_id": "p-auto", "title": "Auto Shoe", "provenance": "auto",
            "rule_id": "r-auto", "google_product_category": "166", "status": "active",
        }

    async def test_unknown_product_404(self, app_factory):
        client = await admin_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client)
        resp = await client.get(
            f"/plugins/category/product?feed_source_id={feed['id']}&product_id=nope"
        )
        assert resp.status_code == 404


class TestCrossTenant:
    async def test_scoped_user_gets_404_on_foreign_feed_source(self, app_factory):
        app, factory = app_factory
        admin = await admin_client(app_factory)
        feed = await _setup_feed(factory, admin)
        other = (await admin.post("/clients", json={"name": "Other"})).json()
        async with factory() as session, session.begin():
            from app.models.user_client import UserClient

            bob = User(
                username="bob", password_hash=hash_password("bob-pass"), role="user"
            )
            session.add(bob)
            await session.flush()
            session.add(UserClient(user_id=bob.id, client_id=other["id"]))
        bob_client = await login(app, "bob", "bob-pass")
        resp = await bob_client.get(
            f"/plugins/category/stats?feed_source_id={feed['id']}"
        )
        assert resp.status_code == 404
```

Verify the `UserClient` import path against `backend/tests/test_scope_enforcement.py` (it may be re-exported from `app.models`) and adjust before running.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest tests/test_category_stats.py -v`
Expected: FAIL — stats/matches/product return 404 (routes not registered)

- [ ] **Step 3: Implement** — inside `register_routes`, extend the local import block:

```python
        from sqlalchemy import func, select

        from app.access import ensure_feed_source_access
        from app.db.engine import get_db_session
        from app.models.feed_source import FeedSource
        from app.models.staging import StagingProduct
```

and append these handlers + registrations after the fetch handler:

```python
        async def stats(feed_source_id, user=Depends(get_current_user),
                        db_session=Depends(get_db_session)):
            if db_session is None:
                raise HTTPException(status_code=503, detail="database unavailable")
            await ensure_feed_source_access(db_session, user, feed_source_id)
            provenance_col = StagingProduct.processed_data["_category_provenance"].astext
            rule_col = StagingProduct.processed_data["_category_rule_id"].astext
            buckets = {"manual": 0, "auto": 0, "excluded": 0, "uncategorized": 0}
            rules: dict[str, int] = {}
            total = 0
            async with db_session.begin():
                if await db_session.get(FeedSource, feed_source_id) is None:
                    raise HTTPException(status_code=404, detail="feed source not found")
                base_where = (
                    StagingProduct.feed_source_id == feed_source_id,
                    StagingProduct.status == "active",
                    StagingProduct.excluded.is_(False),
                )
                for count, provenance in (await db_session.execute(
                    select(func.count(), provenance_col)
                    .where(*base_where)
                    .group_by(provenance_col)
                )).all():
                    total += count
                    key = provenance or "uncategorized"
                    if key in buckets:
                        buckets[key] += count
                for count, rule_id in (await db_session.execute(
                    select(func.count(), rule_col)
                    .where(*base_where, rule_col.is_not(None))
                    .group_by(rule_col)
                )).all():
                    rules[rule_id] = count
            return {"total": total, "buckets": buckets, "rules": rules}

        stats.__annotations__.update({
            "feed_source_id": int, "user": CurrentUser, "return": dict[str, Any],
        })
        router.get("/stats", response_model=None)(stats)

        async def matches(feed_source_id, rule_id,
                          limit=Query(default=50, ge=1, le=200),
                          offset=Query(default=0, ge=0),
                          user=Depends(get_current_user),
                          db_session=Depends(get_db_session)):
            if db_session is None:
                raise HTTPException(status_code=503, detail="database unavailable")
            await ensure_feed_source_access(db_session, user, feed_source_id)
            rule_col = StagingProduct.processed_data["_category_rule_id"].astext
            title_col = func.coalesce(
                StagingProduct.processed_data["title"].astext,
                StagingProduct.raw_data["title"].astext,
            ).label("title")
            where = (
                StagingProduct.feed_source_id == feed_source_id,
                StagingProduct.status == "active",
                StagingProduct.excluded.is_(False),
                rule_col == rule_id,
            )
            async with db_session.begin():
                if await db_session.get(FeedSource, feed_source_id) is None:
                    raise HTTPException(status_code=404, detail="feed source not found")
                total = int((await db_session.execute(
                    select(func.count()).select_from(StagingProduct).where(*where)
                )).scalar() or 0)
                rows = (await db_session.execute(
                    select(StagingProduct.product_id, title_col)
                    .where(*where)
                    .order_by(StagingProduct.product_id)
                    .limit(limit)
                    .offset(offset)
                )).all()
            return {
                "total": total,
                "items": [
                    {"product_id": row.product_id, "title": row.title} for row in rows
                ],
            }

        matches.__annotations__.update({
            "feed_source_id": int, "rule_id": str, "limit": int, "offset": int,
            "user": CurrentUser, "return": dict[str, Any],
        })
        router.get("/matches", response_model=None)(matches)

        async def product_state(feed_source_id, product_id,
                                user=Depends(get_current_user),
                                db_session=Depends(get_db_session)):
            if db_session is None:
                raise HTTPException(status_code=503, detail="database unavailable")
            await ensure_feed_source_access(db_session, user, feed_source_id)
            provenance_col = StagingProduct.processed_data["_category_provenance"].astext
            rule_col = StagingProduct.processed_data["_category_rule_id"].astext
            category_col = func.coalesce(
                StagingProduct.processed_data["google_product_category"].astext,
                StagingProduct.raw_data["google_product_category"].astext,
            ).label("category")
            title_col = func.coalesce(
                StagingProduct.processed_data["title"].astext,
                StagingProduct.raw_data["title"].astext,
            ).label("title")
            async with db_session.begin():
                if await db_session.get(FeedSource, feed_source_id) is None:
                    raise HTTPException(status_code=404, detail="feed source not found")
                row = (await db_session.execute(
                    select(
                        provenance_col, rule_col, category_col, title_col,
                        StagingProduct.status,
                    ).where(
                        StagingProduct.feed_source_id == feed_source_id,
                        StagingProduct.product_id == product_id,
                        StagingProduct.status == "active",
                        StagingProduct.excluded.is_(False),
                    )
                )).first()
                if row is None:
                    raise HTTPException(status_code=404, detail="product not found")
            return {
                "product_id": product_id,
                "title": row.title,
                "provenance": row[0],
                "rule_id": row[1],
                "google_product_category": row.category,
                "status": row.status,
            }

        product_state.__annotations__.update({
            "feed_source_id": int, "product_id": str, "user": CurrentUser,
            "return": dict[str, Any],
        })
        router.get("/product", response_model=None)(product_state)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest tests/test_category_stats.py tests/test_category_routes.py -v`
Expected: PASS

- [ ] **Step 5: Update `backend/docs/api.md`** — add the Category plugin route block to the plugin-routes section, mirroring how custom_labels/filter preview routes are documented. All under `/plugins/category`: `POST /validate` (draft rule validation, 422 `{"errors"}`), `GET /taxonomy/languages`, `GET /taxonomy/search` (query params `language,q,limit,offset`), `GET /taxonomy/validate`, `POST /taxonomy/fetch` (de-DE only; 502 upstream, 500 unwritable), `GET /stats`, `GET /matches`, `GET /product` (all feed-source-scoped routes: 404 on unknown or foreign feed source).

- [ ] **Step 6: Commit**

```bash
cd /home/ozon/gmc_feed_master
git add plugins/core/category/plugin.py backend/tests/test_category_stats.py backend/docs/api.md
git commit -m "feat(category): stats/matches/product routes with cross-tenant guard"
```

---

### Task 6: Backend gate + decisions entry

**Files:**
- Modify: `docs/decisions.md` (2026-09-09 entry)
- Verify only: everything from Tasks 1–5

**Interfaces:**
- Produces: green full backend suite + the decisions record (needed by Tasks 7+ as the authority for the architecture choices).

- [ ] **Step 1: Run the full backend suite**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest -n auto`
Expected: PASS — baseline was 924; category tests add to the count.

- [ ] **Step 2: Lint and typecheck**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run ruff check . && uv run mypy .`
Expected: ruff — zero new issues in touched files; mypy — no new errors vs the 42-error baseline.

- [ ] **Step 3: Record the decisions** — append to `docs/decisions.md` under `## 2026-09-09` (follow the file's existing entry format):

```markdown
### Category plugin (M12) architecture decisions

- **Taxonomy storage is file-based, not PluginData:** the shipped en-US CSV
  (moved from the repo root, operator-provided `cbb1867`) plus the fetched
  de-DE CSV live in `plugins/core/category/` (fetched file gitignored,
  atomic temp+replace write). Rationale: the taxonomy is UI-facing data only
  (`process()` writes IDs and never consults it); storing it as global
  PluginData would push ~5.6k entries into every run's resolved_data and
  trigger pointless full reprocessing on every fetch (config_hash includes
  resolved data) while never changing feed output.
- **One merged ID-keyed index with per-language paths** (operator decision):
  `{id -> {lang -> path}}`; fetched languages merge by ID. v1 languages:
  en-US (shipped, git-updated) + de-DE (fetched from Google's official .txt,
  converted to the house CSV format before persisting).
- **`_category_rule_id` second sidecar:** spec §5.9 names only
  `_category_provenance`; the spec's UI mandates per-rule match counts and a
  matched-products modal, which need the matched rule id on staged products.
  Both sidecars are `_`-prefixed (stripped from content_hash, never rendered
  to XML) — a spec-consistent extension, documented in data-model.md.
- **Draft validation route `POST /plugins/category/validate`:** the platform
  runs `validate_config` only on pipeline-instance configs (pipeline.py:91-95)
  and in the contract suite — not on the generic scoped-config PUT (which
  validates against `config_schema` via jsonschema only). The Rules tab calls
  the validate route before saving; jsonschema remains the generic backstop.
- **Stats are stored-sidecar, "as of last run"** (operator decision): SQL
  GROUP BY over `processed_data->>'_category_provenance'` /
  `->>'_category_rule_id'`; live draft evaluation is a follow-up cycle
  (Labelizer precedent).
```

- [ ] **Step 4: Commit**

```bash
cd /home/ozon/gmc_feed_master
git add docs/decisions.md
git commit -m "docs: record Category plugin (M12) architecture decisions"
```


---

### Task 7: Frontend API layer

**Files:**
- Create: `frontend/src/features/category/types.ts`
- Create: `frontend/src/features/category/scope.ts`
- Create: `frontend/src/features/category/hooks.ts`
- Modify: `frontend/src/api/queryKeys.ts` (add `category` group)
- Create: `frontend/public/locales/en/category.json`, `frontend/public/locales/de/category.json`
- Modify: `frontend/public/locales/en/common.json` + `frontend/public/locales/de/common.json` (`pluginNames.category`)
- Modify: `frontend/src/components/PluginIconMap.ts` (sitemap)
- Test: `frontend/src/features/category/scope.test.ts`, `frontend/src/components/PluginIconMap.test.ts` (create if absent)

**Interfaces:**
- Consumes: `apiGet`/`apiPost` (`frontend/src/api/client.ts`), `queryKeys`, `PluginScope` (`frontend/src/api/hooks.ts:370`).
- Produces:
  - `types.ts`: `CategoryOperator`, `CategoryRule`, `Tier`, `ScopedCategoryRule`, `CategoryStats`, `CategoryMatch`, `TaxonomyEntry`, `CategoryProductState`
  - `hooks.ts`: `useCategoryStats(feedSourceId?)`, `useCategoryMatches(feedSourceId, ruleId, limit, offset)`, `useCategoryProductState(feedSourceId, productId?)`, `useCategoryLanguages()`, `useFetchCategoryLanguage()`, `useValidateCategoryRules()`
  - `scope.ts`: `editableTier(scope: PluginScope): Tier`, `mergeRules(globalRules: CategoryRule[], clientRules: CategoryRule[]): ScopedCategoryRule[]`

- [ ] **Step 1: Write the failing tests**

`frontend/src/features/category/scope.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { editableTier, mergeRules } from './scope';
import type { CategoryRule } from './types';

const g1: CategoryRule = {
  id: 'g1', source_field: 'product_type', operator: 'eq',
  source_value: 'Shoes', taxonomy_id: '166',
};
const g2: CategoryRule = {
  id: 'g2', source_field: 'product_type', operator: 'eq',
  source_value: 'Boots', taxonomy_id: '53',
};

describe('editableTier', () => {
  it('client scope when clientId present', () => {
    expect(editableTier({ clientId: 1 })).toBe('client');
  });
  it('global scope otherwise', () => {
    expect(editableTier({})).toBe('global');
    expect(editableTier({ feedSourceId: 3 })).toBe('global');
  });
});

describe('mergeRules', () => {
  it('client overrides same id in place, appends unseen', () => {
    const client: CategoryRule[] = [
      { ...g1, taxonomy_id: '999' },
      { id: 'c1', source_field: 'product_type', operator: 'ne', source_value: 'Socks', taxonomy_id: '166' },
    ];
    const merged = mergeRules([g1, g2], client);
    expect(merged.map((r) => [r.id, r.origin])).toEqual([
      ['g1', 'client'],
      ['g2', 'global'],
      ['c1', 'client'],
    ]);
    expect(merged[0].taxonomy_id).toBe('999');
  });
  it('empty tiers', () => {
    expect(mergeRules([], [])).toEqual([]);
    expect(mergeRules([g1], []).map((r) => r.origin)).toEqual(['global']);
  });
});
```

`frontend/src/components/PluginIconMap.test.ts` (create; if one already exists, add the sitemap case to it):

```ts
import { describe, expect, it } from 'vitest';
import { getPluginIcon } from './PluginIconMap';

describe('getPluginIcon', () => {
  it('maps sitemap and keeps circle fallback for unknown names', () => {
    expect(getPluginIcon('sitemap')).toBeDefined();
    expect(getPluginIcon('sitemap')).not.toEqual(getPluginIcon('unknown-icon-name'));
    expect(getPluginIcon('unknown-icon-name')).toEqual(getPluginIcon(undefined));
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run src/features/category/scope.test.ts`
Expected: FAIL — cannot resolve `./scope`

- [ ] **Step 3: Implement**

`frontend/src/features/category/types.ts`:

```ts
export type CategoryOperator = 'eq' | 'ne' | 'contains' | 'regex' | 'in';

export type CategoryRule = {
  id: string;
  source_field: string;
  operator: CategoryOperator;
  source_value: string | string[];
  taxonomy_id: string;
  is_excluded?: boolean;
};

export type Tier = 'global' | 'client';

export type ScopedCategoryRule = CategoryRule & { origin: Tier };

export type CategoryStats = {
  total: number;
  buckets: { manual: number; auto: number; excluded: number; uncategorized: number };
  rules: Record<string, number>;
};

export type CategoryMatch = { product_id: string; title: string | null };

export type TaxonomyEntry = { id: string; path: string };

export type CategoryProductState = {
  product_id: string;
  title: string | null;
  provenance: 'manual' | 'auto' | 'excluded' | null;
  rule_id: string | null;
  google_product_category: string | null;
  status: string;
};
```

`frontend/src/features/category/scope.ts`:

```ts
import type { PluginScope } from '../../api/hooks';
import type { CategoryRule, ScopedCategoryRule, Tier } from './types';

export function editableTier(scope: PluginScope): Tier {
  return scope.clientId !== undefined ? 'client' : 'global';
}

export function mergeRules(
  globalRules: CategoryRule[],
  clientRules: CategoryRule[],
): ScopedCategoryRule[] {
  const merged: ScopedCategoryRule[] = globalRules.map((rule) => ({ ...rule, origin: 'global' }));
  const byId = new Map(merged.map((rule, index) => [rule.id, index]));
  for (const rule of clientRules) {
    const index = byId.get(rule.id);
    if (index === undefined) {
      merged.push({ ...rule, origin: 'client' });
      byId.set(rule.id, merged.length - 1);
    } else {
      merged[index] = { ...rule, origin: 'client' };
    }
  }
  return merged;
}
```

`frontend/src/api/queryKeys.ts` — add after `pluginData`:

```ts
  category: {
    stats: (feedSourceId: number | string) =>
      ['feed-source', feedSourceId, 'category-stats'] as const,
    matches: (feedSourceId: number | string, ruleId: string, limit: number, offset: number) =>
      ['feed-source', feedSourceId, 'category-matches', ruleId, { limit, offset }] as const,
    product: (feedSourceId: number | string, productId: string) =>
      ['feed-source', feedSourceId, 'category-product', productId] as const,
    languages: ['category', 'taxonomy-languages'] as const,
  },
```

`frontend/src/features/category/hooks.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from '../../api/client';
import { queryKeys } from '../../api/queryKeys';
import type {
  CategoryMatch, CategoryProductState, CategoryRule, CategoryStats, TaxonomyEntry,
} from './types';

export function useCategoryStats(feedSourceId: number | string | undefined) {
  return useQuery({
    queryKey: queryKeys.category.stats(feedSourceId ?? 0),
    queryFn: () =>
      apiGet<CategoryStats>(`/plugins/category/stats?feed_source_id=${feedSourceId}`),
    enabled: Boolean(feedSourceId),
  });
}

export function useCategoryMatches(
  feedSourceId: number | string,
  ruleId: string,
  limit: number,
  offset: number,
) {
  return useQuery({
    queryKey: queryKeys.category.matches(feedSourceId, ruleId, limit, offset),
    queryFn: () =>
      apiGet<{ total: number; items: CategoryMatch[] }>(
        `/plugins/category/matches?feed_source_id=${feedSourceId}` +
          `&rule_id=${encodeURIComponent(ruleId)}&limit=${limit}&offset=${offset}`,
      ),
    enabled: Boolean(feedSourceId) && Boolean(ruleId),
  });
}

export function useCategoryProductState(
  feedSourceId: number | string,
  productId: string | undefined,
) {
  return useQuery({
    queryKey: queryKeys.category.product(feedSourceId, productId ?? ''),
    queryFn: () =>
      apiGet<CategoryProductState>(
        `/plugins/category/product?feed_source_id=${feedSourceId}` +
          `&product_id=${encodeURIComponent(productId ?? '')}`,
      ),
    enabled: Boolean(feedSourceId) && Boolean(productId),
  });
}

export function useCategoryLanguages() {
  return useQuery({
    queryKey: queryKeys.category.languages,
    queryFn: () => apiGet<{ languages: string[] }>('/plugins/category/taxonomy/languages'),
  });
}

export function useFetchCategoryLanguage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (language: string) =>
      apiPost<{ status: string; language: string; entries: number }>(
        '/plugins/category/taxonomy/fetch',
        { language },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.category.languages });
    },
  });
}

export function useValidateCategoryRules() {
  return useMutation({
    mutationFn: (rules: CategoryRule[]) =>
      apiPost<{ status: string }>('/plugins/category/validate', { rules }),
  });
}
```

`frontend/src/components/PluginIconMap.ts` — add `IconSitemap` to the import and `'sitemap': IconSitemap,` to the map (verify the icon exists in the installed `@tabler/icons-react` export map first; if missing, use `IconCategory2` and record the deviation).

`frontend/public/locales/en/common.json` — add `"category": "Category"` inside `pluginNames`.
`frontend/public/locales/de/common.json` — add `"category": "Kategorie"` inside `pluginNames`.

`frontend/public/locales/en/category.json`:

```json
{
  "title": "Category",
  "language": "Taxonomy language",
  "fetchLanguage": "Fetch de-DE taxonomy",
  "fetchLanguagePending": "Fetching…",
  "fetchLanguageFailed": "Could not fetch the taxonomy from Google.",
  "tabs": {
    "dashboard": "Dashboard",
    "rules": "Rules",
    "manual": "Manual categorization",
    "ai": "AI",
    "uncategorized": "Uncategorized"
  },
  "placeholders": {
    "aiDisabled": "AI-assisted categorization is not part of v1.",
    "uncategorizedDisabled": "The uncategorized worklist ships in a follow-up release.",
    "generateDisabled": "Generate is not part of v1.",
    "copyDisabled": "Copy rules is not part of v1.",
    "bulkDeleteDisabled": "Bulk delete is not part of v1."
  },
  "dashboard": {
    "feedSource": "Feed source",
    "noFeedSources": "This client has no feed sources yet.",
    "noProducts": "No staged products yet — run the pipeline first.",
    "asOfLastRun": "Counts reflect the last pipeline run.",
    "total": "Total staged products",
    "buckets": {
      "manual": "Manual",
      "auto": "Auto (rules)",
      "excluded": "Excluded",
      "uncategorized": "Uncategorized"
    },
    "progress": "{{labeled}} of {{total}} categorized"
  },
  "rules": {
    "add": "Add rule",
    "empty": "No rules yet. Add your first rule.",
    "reset": "Reset",
    "save": "Save",
    "saved": "Rules saved.",
    "saveFailed": "Could not save rules.",
    "validateFailed": "The draft has errors.",
    "confirmLeave": "You have unsaved changes. Leave anyway?",
    "confirmLeaveTitle": "Unsaved changes",
    "delete": "Delete rule",
    "deleteConfirmTitle": "Delete rule",
    "deleteConfirmBody": "Delete rule {{id}}? Products categorized by it become uncategorized on the next run.",
    "matchesCount_one": "{{count}} match",
    "matchesCount_other": "{{count}} matches",
    "showMatches": "Show matched products",
    "inherited": "Inherited",
    "override": "Override at client level",
    "sourceField": "Source field",
    "operator": "Operator",
    "sourceValue": "Source value",
    "sourceValueIn": "Values (one per line)",
    "taxonomy": "Google category",
    "excluded": "Excluded (no category)",
    "operators": {
      "eq": "equals",
      "ne": "not equals",
      "contains": "contains",
      "regex": "regex",
      "in": "one of"
    }
  },
  "matches": {
    "modalTitle": "Products matched by rule {{id}}",
    "loadMore": "Load more",
    "empty": "No staged products matched this rule yet.",
    "stale": "Counts are as of the last pipeline run."
  },
  "manual": {
    "productId": "Product ID",
    "lookup": "Look up",
    "notFound": "Product not found in this feed source.",
    "empty": "Enter a product ID to categorize it manually.",
    "needsClient": "Manual categorization needs a client context.",
    "selectFeedSource": "Select a feed source first.",
    "provenanceLabel": "Provenance",
    "categoryLabel": "Current category",
    "assignmentLabel": "Manual assignment",
    "none": "none",
    "assign": "Assign category",
    "unassign": "Remove assignment",
    "saved": "Assignments saved.",
    "saveFailed": "Could not save assignments.",
    "provenance": {
      "manual": "Manual",
      "auto": "Auto (rule {{rule}})",
      "excluded": "Excluded (rule {{rule}})",
      "null": "Uncategorized"
    }
  },
  "taxonomy": {
    "search": "Search category",
    "noResults": "No matching category."
  }
}
```

`frontend/public/locales/de/category.json` — identical key tree with German values, e.g.:

```json
{
  "title": "Kategorie",
  "language": "Taxonomie-Sprache",
  "fetchLanguage": "de-DE-Taxonomie abrufen",
  "fetchLanguagePending": "Wird abgerufen…",
  "fetchLanguageFailed": "Die Taxonomie konnte nicht von Google abgerufen werden.",
  "tabs": {
    "dashboard": "Dashboard",
    "rules": "Regeln",
    "manual": "Manuelle Kategorisierung",
    "ai": "KI",
    "uncategorized": "Nicht kategorisiert"
  },
  "placeholders": {
    "aiDisabled": "KI-gestützte Kategorisierung ist nicht Teil von v1.",
    "uncategorizedDisabled": "Die Arbeitliste für nicht kategorisierte Produkte folgt in einem späteren Release.",
    "generateDisabled": "Generieren ist nicht Teil von v1.",
    "copyDisabled": "Regeln kopieren ist nicht Teil von v1.",
    "bulkDeleteDisabled": "Mehrfaches Löschen ist nicht Teil von v1."
  },
  "dashboard": {
    "feedSource": "Feed-Quelle",
    "noFeedSources": "Dieser Mandant hat noch keine Feed-Quellen.",
    "noProducts": "Noch keine bereitgestellten Produkte — zuerst die Pipeline ausführen.",
    "asOfLastRun": "Die Zahlen beziehen sich auf den letzten Pipeline-Lauf.",
    "total": "Bereitgestellte Produkte gesamt",
    "buckets": {
      "manual": "Manuell",
      "auto": "Automatisch (Regeln)",
      "excluded": "Ausgeschlossen",
      "uncategorized": "Nicht kategorisiert"
    },
    "progress": "{{labeled}} von {{total}} kategorisiert"
  },
  "rules": {
    "add": "Regel hinzufügen",
    "empty": "Noch keine Regeln. Fügen Sie die erste Regel hinzu.",
    "reset": "Zurücksetzen",
    "save": "Speichern",
    "saved": "Regeln gespeichert.",
    "saveFailed": "Regeln konnten nicht gespeichert werden.",
    "validateFailed": "Der Entwurf enthält Fehler.",
    "confirmLeave": "Es gibt ungespeicherte Änderungen. Trotzdem verlassen?",
    "confirmLeaveTitle": "Ungespeicherte Änderungen",
    "delete": "Regel löschen",
    "deleteConfirmTitle": "Regel löschen",
    "deleteConfirmBody": "Regel {{id}} löschen? Davon kategorisierte Produkte werden beim nächsten Lauf nicht kategorisiert.",
    "matchesCount_one": "{{count}} Treffer",
    "matchesCount_other": "{{count}} Treffer",
    "showMatches": "Zugeordnete Produkte anzeigen",
    "inherited": "Geerbt",
    "override": "Auf Mandantenebene überschreiben",
    "sourceField": "Quellfeld",
    "operator": "Operator",
    "sourceValue": "Quellwert",
    "sourceValueIn": "Werte (einer pro Zeile)",
    "taxonomy": "Google-Kategorie",
    "excluded": "Ausgeschlossen (keine Kategorie)",
    "operators": {
      "eq": "gleich",
      "ne": "ungleich",
      "contains": "enthält",
      "regex": "Regex",
      "in": "einer von"
    }
  },
  "matches": {
    "modalTitle": "Von Regel {{id}} zugeordnete Produkte",
    "loadMore": "Mehr laden",
    "empty": "Noch keine bereitgestellten Produkte entsprechen dieser Regel.",
    "stale": "Die Zahlen beziehen sich auf den letzten Pipeline-Lauf."
  },
  "manual": {
    "productId": "Produkt-ID",
    "lookup": "Nachschlagen",
    "notFound": "Produkt in dieser Feed-Quelle nicht gefunden.",
    "empty": "Geben Sie eine Produkt-ID ein, um sie manuell zu kategorisieren.",
    "needsClient": "Die manuelle Kategorisierung benötigt einen Mandanten-Kontext.",
    "selectFeedSource": "Wählen Sie zuerst eine Feed-Quelle.",
    "provenanceLabel": "Herkunft",
    "categoryLabel": "Aktuelle Kategorie",
    "assignmentLabel": "Manuelle Zuordnung",
    "none": "keine",
    "assign": "Kategorie zuordnen",
    "unassign": "Zuordnung entfernen",
    "saved": "Zuordnungen gespeichert.",
    "saveFailed": "Zuordnungen konnten nicht gespeichert werden.",
    "provenance": {
      "manual": "Manuell",
      "auto": "Automatisch (Regel {{rule}})",
      "excluded": "Ausgeschlossen (Regel {{rule}})",
      "null": "Nicht kategorisiert"
    }
  },
  "taxonomy": {
    "search": "Kategorie suchen",
    "noResults": "Keine passende Kategorie."
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run && npm run typecheck`
Expected: PASS (scope tests, icon test, i18n parity, typecheck)

- [ ] **Step 5: Commit**

```bash
cd /home/ozon/gmc_feed_master
git add frontend/src/features/category frontend/src/api/queryKeys.ts frontend/public/locales frontend/src/components/PluginIconMap.ts frontend/src/components/PluginIconMap.test.ts
git commit -m "feat(frontend): category API layer — types, hooks, scope helpers, i18n, icon"
```


---

### Task 8: CategoryUI shell + Dashboard tab

**Files:**
- Create: `frontend/src/features/category/CategoryUI.tsx`
- Create: `frontend/src/features/category/DashboardTab.tsx`
- Create: `plugins/core/category/frontend/component.tsx` (stub)
- Modify: `frontend/src/features/plugin/customComponents.ts` (registry entry)
- Modify: `plugins/core/category/plugin.json` (add `frontend` section)
- Test: `frontend/src/features/category/CategoryUI.test.tsx`

**Interfaces:**
- Consumes: Task 7 hooks/types/i18n; `CustomComponentProps` = `{ pluginId: string; scope: PluginScope }` (`frontend/src/features/plugin/customComponents.ts`); `useDashboardSummary` (hooks.ts:81); `ErrorState/LoadingState/EmptyState` (`src/components/StateViews`); Mantine `Tabs/Select/Tooltip/Badge/Paper/Progress/Group/Stack/Text`.
- Produces: `CategoryUI` default-exported via the stub and registered as `CUSTOM_COMPONENTS.category`; `DashboardTab({ clientId, feedSourceId, onSelectFeedSource })`; the shell keeps page-level state `feedSourceId` + `language` passed to all three tabs (Task 9/10 consume them via props `{ pluginId, scope, language, feedSourceId }`).

- [ ] **Step 1: Write the failing tests** `frontend/src/features/category/CategoryUI.test.tsx`

First read `frontend/src/test/fetch.ts` to learn the exact stubbing helper and mirror the URL stubbing style used in `frontend/src/features/dashboard/DashboardPage.test.tsx:188` (fetch mock keyed by URL). The test below assumes a `stubFetch` returning a `vi.fn()`-style mock whose `mock.calls` are recorded URLs — adapt names to the real helper.

```tsx
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { notifications } from '../../app/notifications';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { CategoryUI } from './CategoryUI';

describe('CategoryUI shell', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    notifications.clean();
  });

  it('renders tabs with AI and Uncategorized disabled placeholders', async () => {
    const fetchMock = stubFetch([
      { match: '/plugins/category/taxonomy/languages', body: { languages: ['en-US'] } },
      { match: '/plugins/category/config', body: { rules: [] } },
      { match: '/plugins/category/data', body: { assignments: {} } },
      { match: '/dashboard/summary', body: { clients: [] } },
    ]);
    render(<CategoryUI pluginId="category" scope={{ clientId: 1 }} />);
    expect(await screen.findByRole('tab', { name: /Dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Rules/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Manual categorization/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /^AI$/ })).toHaveAttribute('disabled');
    expect(screen.getByRole('tab', { name: /Uncategorized/i })).toHaveAttribute('disabled');
    expect(fetchMock.calls.join(' ').includes('/plugins/category/stats')).toBe(false);
  });

  it('dashboard shows the four buckets for the selected feed source', async () => {
    stubFetch([
      { match: '/plugins/category/taxonomy/languages', body: { languages: ['en-US'] } },
      { match: '/plugins/category/config', body: { rules: [] } },
      { match: '/plugins/category/data', body: { assignments: {} } },
      {
        match: '/dashboard/summary',
        body: {
          clients: [
            {
              id: 1, name: 'Acme', status: 'active',
              feed_sources: [{ id: 7, name: 'DE', last_run_status: 'success' }],
            },
          ],
        },
      },
      {
        match: '/plugins/category/stats?feed_source_id=7',
        body: {
          total: 10,
          buckets: { manual: 2, auto: 5, excluded: 1, uncategorized: 2 },
          rules: {},
        },
      },
    ]);
    render(<CategoryUI pluginId="category" scope={{ clientId: 1 }} />);
    await waitFor(() => expect(screen.getByText('10')).toBeInTheDocument());
    expect(screen.getByText(/Manual/)).toBeInTheDocument();
    expect(screen.getByText(/Auto \(rules\)/)).toBeInTheDocument();
    expect(screen.getByText(/Excluded/)).toBeInTheDocument();
    expect(screen.getByText(/Uncategorized/)).toBeInTheDocument();
    expect(screen.getByText(/7 of 10 categorized/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run src/features/category/CategoryUI.test.tsx`
Expected: FAIL — cannot resolve `./CategoryUI`

- [ ] **Step 3: Implement**

`plugins/core/category/frontend/component.tsx`:

```tsx
export { default } from '../../../../frontend/src/features/category/CategoryUI';
```

`frontend/src/features/category/DashboardTab.tsx`:

```tsx
import { Group, Paper, Progress, Select, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useDashboardSummary } from '../../api/hooks';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { useCategoryStats } from './hooks';

const BUCKET_KEYS = ['manual', 'auto', 'excluded', 'uncategorized'] as const;

export function DashboardTab({
  clientId,
  feedSourceId,
  onSelectFeedSource,
}: {
  clientId: number | undefined;
  feedSourceId: number | undefined;
  onSelectFeedSource: (id: number) => void;
}) {
  const { t } = useTranslation('category');
  const summary = useDashboardSummary();
  const stats = useCategoryStats(feedSourceId);

  const client = summary.data?.clients?.find((c) => c.id === clientId);
  const feedSources = client?.feed_sources ?? [];

  if (clientId === undefined) {
    return <EmptyState>{t('manual.needsClient')}</EmptyState>;
  }
  if (summary.isLoading) return <LoadingState />;
  if (summary.isError) return <ErrorState onRetry={() => void summary.refetch()} />;
  if (feedSources.length === 0) return <EmptyState>{t('dashboard.noFeedSources')}</EmptyState>;

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Select
          label={t('dashboard.feedSource')}
          w={280}
          data={feedSources.map((feed) => ({ value: String(feed.id), label: feed.name }))}
          value={feedSourceId !== undefined ? String(feedSourceId) : null}
          onChange={(value) => value && onSelectFeedSource(Number(value))}
        />
        <Text size="xs" c="dimmed">{t('dashboard.asOfLastRun')}</Text>
      </Group>
      {stats.isLoading && <LoadingState />}
      {stats.isError && <ErrorState onRetry={() => void stats.refetch()} />}
      {stats.data && stats.data.total === 0 && (
        <EmptyState>{t('dashboard.noProducts')}</EmptyState>
      )}
      {stats.data && stats.data.total > 0 && (
        <Stack gap="xs">
          <Text size="sm" c="dimmed">
            {t('dashboard.progress', {
              labeled: stats.data.total - stats.data.buckets.uncategorized,
              total: stats.data.total,
            })}
          </Text>
          <Progress
            value={
              ((stats.data.total - stats.data.buckets.uncategorized) / stats.data.total) * 100
            }
            size="lg"
          />
          <Group gap="md" mt="xs" align="flex-start">
            {BUCKET_KEYS.map((bucket) => (
              <Paper withBorder p="sm" key={bucket}>
                <Stack gap={2}>
                  <Text size="xs" c="dimmed">{t(`dashboard.buckets.${bucket}`)}</Text>
                  <Text fw={700} fz="lg">{stats.data!.buckets[bucket]}</Text>
                </Stack>
              </Paper>
            ))}
            <Paper withBorder p="sm">
              <Stack gap={2}>
                <Text size="xs" c="dimmed">{t('dashboard.total')}</Text>
                <Text fw={700} fz="lg">{stats.data.total}</Text>
              </Stack>
            </Paper>
          </Group>
        </Stack>
      )}
    </Stack>
  );
}
```

`frontend/src/features/category/CategoryUI.tsx`:

```tsx
import { useState } from 'react';
import { Badge, Group, Select, Stack, Tabs, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useCategoryLanguages, useFetchCategoryLanguage } from './hooks';
import { editableTier } from './scope';
import { DashboardTab } from './DashboardTab';
import { RulesTab } from './RulesTab';
import { ManualTab } from './ManualTab';

export default function CategoryUI({
  pluginId,
  scope,
}: {
  pluginId: string;
  scope: { clientId?: number; feedSourceId?: number };
}) {
  const { t } = useTranslation('category');
  const tier = editableTier(scope);
  const [feedSourceId, setFeedSourceId] = useState<number | undefined>(undefined);
  const [language, setLanguage] = useState('en-US');
  const languages = useCategoryLanguages();
  const fetchLanguage = useFetchCategoryLanguage();
  const available = languages.data?.languages ?? ['en-US'];
  const deMissing = !available.includes('de-DE');

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Badge variant="light" color="gray">{tier}</Badge>
        <Group gap="xs">
          <Select
            label={t('language')}
            w={200}
            data={available.map((code) => ({ value: code, label: code }))}
            value={available.includes(language) ? language : available[0]}
            onChange={(value) => value && setLanguage(value)}
          />
          {deMissing && (
            <Select
              placeholder={t('fetchLanguage')}
              w={220}
              data={[{ value: 'de-DE', label: 'de-DE' }]}
              value={null}
              onChange={(value) =>
                value && fetchLanguage.mutate(value, {
                  onSuccess: () => setLanguage(value),
                })
              }
            />
          )}
        </Group>
      </Group>
      <Tabs defaultValue="dashboard">
        <Tabs.List>
          <Tabs.Tab value="dashboard">{t('tabs.dashboard')}</Tabs.Tab>
          <Tabs.Tab value="rules">{t('tabs.rules')}</Tabs.Tab>
          <Tabs.Tab value="manual">{t('tabs.manual')}</Tabs.Tab>
          <Tooltip label={t('placeholders.aiDisabled')} position="bottom">
            <Tabs.Tab value="ai" disabled>{t('tabs.ai')}</Tabs.Tab>
          </Tooltip>
          <Tooltip label={t('placeholders.uncategorizedDisabled')} position="bottom">
            <Tabs.Tab value="uncategorized" disabled>{t('tabs.uncategorized')}</Tabs.Tab>
          </Tooltip>
        </Tabs.List>
        <Tabs.Panel value="dashboard" pt="md">
          <DashboardTab
            clientId={scope.clientId}
            feedSourceId={feedSourceId}
            onSelectFeedSource={setFeedSourceId}
          />
        </Tabs.Panel>
        <Tabs.Panel value="rules" pt="md">
          <RulesTab
            pluginId={pluginId}
            scope={scope}
            language={language}
            feedSourceId={feedSourceId}
          />
        </Tabs.Panel>
        <Tabs.Panel value="manual" pt="md">
          <ManualTab
            pluginId={pluginId}
            scope={scope}
            language={language}
            feedSourceId={feedSourceId}
          />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
```

Minimal placeholders so the shell compiles (Task 9/10 replace them) — `frontend/src/features/category/RulesTab.tsx`:

```tsx
export function RulesTab(_props: {
  pluginId: string;
  scope: unknown;
  language: string;
  feedSourceId: number | undefined;
}) {
  return null;
}
```

`frontend/src/features/category/ManualTab.tsx` — same shape, `return null`.

`frontend/src/features/plugin/customComponents.ts` — add the import and entry:

```ts
import CategoryUI from '../category/CategoryUI';

export const CUSTOM_COMPONENTS: Record<string, ComponentType<CustomComponentProps>> = {
  rules: RulesUI,
  filter: FilterUI,
  custom_labels: LabelizerPage,
  category: CategoryUI,
};
```

`plugins/core/category/plugin.json` — add after `data_schema`:

```json
  "frontend": {
    "menu_item": "Category",
    "icon": "sitemap",
    "component": "component.tsx"
  }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run src/features/category/ && npm run typecheck`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/ozon/gmc_feed_master
git add plugins/core/category frontend/src/features/category frontend/src/features/plugin/customComponents.ts
git commit -m "feat(frontend): CategoryUI shell, dashboard tab, nav registration"
```


---

### Task 9: Rules tab (dnd editor, autocomplete, badges, matches modal, dirty guard)

**Files:**
- Replace: `frontend/src/features/category/RulesTab.tsx` (full implementation)
- Create: `frontend/src/features/category/TaxonomyCombobox.tsx`
- Create: `frontend/src/features/category/MatchesModal.tsx`
- Create: `frontend/src/features/category/rulesDnd.ts`
- Test: `frontend/src/features/category/rulesDnd.test.ts`, `frontend/src/features/category/RulesTab.test.tsx`

**Interfaces:**
- Consumes: Task 7 hooks + `mergeRules`/`editableTier`; Task 8 shell props `{ pluginId, scope, language, feedSourceId }`; generic `usePluginConfig(pluginId, scope?, enabled?)` / `useSavePluginConfig(pluginId, scope?)` (hooks.ts:381-402); `useRegistryAttributes` (hooks.ts:133); `useBlocker` + `ConfirmModal` + `ScopeBadge` + `notifyApiError`/`notifySuccess`; dnd-kit (`DndContext, PointerSensor, closestCenter, useSensor, useSensors` + `SortableContext, verticalListSortingStrategy, useSortable` — see `frontend/src/features/customLabels/CustomLabelsUI.tsx:8-11` and `SortableRuleRow.tsx`).
- Produces: `RulesTab({ pluginId, scope, language, feedSourceId })`; `TaxonomyCombobox({ language, value, onChange })`; `MatchesModal({ feedSourceId, ruleId, opened, onClose })`; `applyRulesDragEnd(rules: ScopedCategoryRule[], activeId: string | null, overIndex: number | null): ScopedCategoryRule[]` (returns the SAME array when nothing to do).

- [ ] **Step 1: Write the failing tests**

`frontend/src/features/category/rulesDnd.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { applyRulesDragEnd } from './rulesDnd';
import type { ScopedCategoryRule } from './types';

const rule = (id: string): ScopedCategoryRule => ({
  id, source_field: 'product_type', operator: 'eq', source_value: 'x',
  taxonomy_id: '1', origin: 'client',
});

describe('applyRulesDragEnd', () => {
  it('reorders within the list', () => {
    const rules = [rule('a'), rule('b'), rule('c')];
    expect(applyRulesDragEnd(rules, 'c', 0).map((r) => r.id)).toEqual(['c', 'a', 'b']);
  });
  it('returns the same array when active or over is missing', () => {
    const rules = [rule('a'), rule('b')];
    expect(applyRulesDragEnd(rules, null, 0)).toBe(rules);
    expect(applyRulesDragEnd(rules, 'a', null)).toBe(rules);
    expect(applyRulesDragEnd(rules, 'zzz', 0)).toBe(rules);
  });
  it('does not mutate the input', () => {
    const rules = [rule('a'), rule('b')];
    applyRulesDragEnd(rules, 'b', 0);
    expect(rules.map((r) => r.id)).toEqual(['a', 'b']);
  });
});
```

`frontend/src/features/category/RulesTab.test.tsx` — cases (adapt stubbing to the real fetch helper per Task 8; wrap in the repo's QueryClient test wrapper as `usePreview.test.tsx` does):

1. renders merged view at client tier: stub `/plugins/category/config` (global URL) returning one global rule and `/plugins/category/config?client_id=1` returning one client rule → both render, the global-origin card is read-only with an Inherited badge.
2. "Add rule" appends an editable rule with `source_field: 'product_type'`, `operator: 'eq'`.
3. Save order: clicking Save first POSTs `/plugins/category/validate` and only PUTs `{ rules: [...] }` to `/plugins/category/config?client_id=1` after a 200; success toast shows.
4. Validate 422 (stub errors array): error summary surfaces via notifications; NO PUT happens.
5. Dirty guard: with a modified draft, navigating away via `useBlocker` opens the ConfirmModal (test via `createMemoryRouter` + `RouterProvider`, per the M10-d lesson).
6. Per-rule match badge: stub the stats endpoint → badge shows "2 matches" (en locale pluralization); "Show matched products" opens the modal with the matched product list.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run src/features/category/`
Expected: FAIL (placeholder RulesTab renders nothing)

- [ ] **Step 3: Implement**

`frontend/src/features/category/rulesDnd.ts`:

```ts
import type { ScopedCategoryRule } from './types';

export function applyRulesDragEnd(
  rules: ScopedCategoryRule[],
  activeId: string | null,
  overIndex: number | null,
): ScopedCategoryRule[] {
  if (activeId === null || overIndex === null) return rules;
  const from = rules.findIndex((rule) => rule.id === activeId);
  if (from === -1 || from === overIndex) return rules;
  const next = [...rules];
  const [moved] = next.splice(from, 1);
  next.splice(overIndex, 0, moved);
  return next;
}
```

`frontend/src/features/category/TaxonomyCombobox.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Select } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { apiGet } from '../../api/client';
import type { TaxonomyEntry } from './types';

const DEBOUNCE_MS = 300;

export function TaxonomyCombobox({
  language,
  value,
  onChange,
}: {
  language: string;
  value: string | null;
  onChange: (taxonomyId: string | null) => void;
}) {
  const { t } = useTranslation('category');
  const [query, setQuery] = useState('');
  const [entries, setEntries] = useState<TaxonomyEntry[]>([]);

  useEffect(() => {
    if (!query.trim()) {
      setEntries([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      void apiGet<{ items: TaxonomyEntry[] }>(
        `/plugins/category/taxonomy/search?language=${language}` +
          `&q=${encodeURIComponent(query)}&limit=50&offset=0`,
      )
        .catch(() => ({ items: [] as TaxonomyEntry[] }))
        .then((result) => {
          if (!cancelled) setEntries(result.items);
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, language]);

  return (
    <Select
      label={t('rules.taxonomy')}
      searchable
      clearable
      data={entries.map((entry) => ({
        value: entry.id,
        label: `${entry.id} — ${entry.path}`,
      }))}
      value={value}
      searchValue={query}
      onSearchChange={setQuery}
      onChange={(next) => onChange(next)}
      placeholder={t('taxonomy.search')}
      nothingFoundMessage={t('taxonomy.noResults')}
    />
  );
}
```

`frontend/src/features/category/MatchesModal.tsx`:

```tsx
import { useState } from 'react';
import { Badge, Button, Group, List, Modal, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useCategoryMatches } from './hooks';

const PAGE_SIZE = 50;

export function MatchesModal({
  feedSourceId,
  ruleId,
  opened,
  onClose,
}: {
  feedSourceId: number | undefined;
  ruleId: string;
  opened: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation('category');
  const [offset, setOffset] = useState(0);
  const query = useCategoryMatches(feedSourceId ?? 0, ruleId, PAGE_SIZE, offset);

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('matches.modalTitle', { id: ruleId })}
      size="lg"
    >
      <Stack gap="sm">
        <Text size="xs" c="dimmed">{t('matches.stale')}</Text>
        {query.isLoading && <Text c="dimmed">{t('matches.stale')}</Text>}
        {query.data && query.data.items.length === 0 && (
          <Text c="dimmed">{t('matches.empty')}</Text>
        )}
        {query.data && query.data.items.length > 0 && (
          <List>
            {query.data.items.map((item) => (
              <List.Item key={item.product_id}>
                <Group gap="xs">
                  <Badge variant="light">{item.product_id}</Badge>
                  <Text size="sm">{item.title ?? ''}</Text>
                </Group>
              </List.Item>
            ))}
          </List>
        )}
        {query.data && offset + PAGE_SIZE < query.data.total && (
          <Button variant="subtle" onClick={() => setOffset(offset + PAGE_SIZE)}>
            {t('matches.loadMore')}
          </Button>
        )}
      </Stack>
    </Modal>
  );
}
```

`frontend/src/features/category/RulesTab.tsx` — replace the placeholder. Read `frontend/src/features/customLabels/SortableRuleRow.tsx` first and mirror its `useSortable` drag-handle wiring for `SortableRuleRow`; keep every i18n key from Task 7 (no new keys):

```tsx
import { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon, Badge, Button, Card, Group, Select, Stack, Switch, Text,
  Textarea, TextInput, Title,
} from '@mantine/core';
import { IconGripVertical, IconTrash } from '@tabler/icons-react';
import {
  DndContext, PointerSensor, closestCenter, useSensor, useSensors,
} from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { useBlocker } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  usePluginConfig, useRegistryAttributes, useSavePluginConfig, type PluginScope,
} from '../../api/hooks';
import { ConfirmModal } from '../../components/ConfirmModal';
import { ScopeBadge } from '../../components/ScopeBadge';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { notifyApiError, notifySuccess } from '../../app/notifications';
import { useCategoryStats, useValidateCategoryRules } from './hooks';
import { MatchesModal } from './MatchesModal';
import { TaxonomyCombobox } from './TaxonomyCombobox';
import { applyRulesDragEnd } from './rulesDnd';
import { editableTier, mergeRules } from './scope';
import type { CategoryOperator, CategoryRule, ScopedCategoryRule } from './types';

const OPERATORS: CategoryOperator[] = ['eq', 'ne', 'contains', 'regex', 'in'];

function rulesOf(payload: unknown): CategoryRule[] {
  return (payload as { rules?: CategoryRule[] } | undefined)?.rules ?? [];
}

function newRuleId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `r_${Math.random().toString(36).slice(2)}`;
}

export function RulesTab({
  pluginId,
  scope,
  language,
  feedSourceId,
}: {
  pluginId: string;
  scope: PluginScope;
  language: string;
  feedSourceId: number | undefined;
}) {
  const { t } = useTranslation('category');
  const tier = editableTier(scope);
  const globalConfig = usePluginConfig(pluginId, {});
  const clientConfig = usePluginConfig(
    pluginId, scope.clientId !== undefined ? { clientId: scope.clientId } : {},
  );
  const save = useSavePluginConfig(
    pluginId, scope.clientId !== undefined ? { clientId: scope.clientId } : {},
  );
  const validate = useValidateCategoryRules();
  const stats = useCategoryStats(feedSourceId);
  const registry = useRegistryAttributes();

  const [draft, setDraft] = useState<ScopedCategoryRule[] | null>(null);
  const [matchesRule, setMatchesRule] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const sensors = useSensors(useSensor(PointerSensor));

  const baseline = useMemo(
    () => mergeRules(
      rulesOf(globalConfig.data),
      scope.clientId !== undefined ? rulesOf(clientConfig.data) : [],
    ),
    [globalConfig.data, clientConfig.data, scope.clientId],
  );

  useEffect(() => {
    if (draft === null && !globalConfig.isLoading && !clientConfig.isLoading) {
      setDraft(baseline);
    }
  }, [baseline, globalConfig.isLoading, clientConfig.isLoading, draft]);

  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(baseline);
  const blocker = useBlocker(dirty);

  if (draft === null) {
    if (globalConfig.isLoading || clientConfig.isLoading) return <LoadingState />;
    if (globalConfig.isError || clientConfig.isError) {
      return (
        <ErrorState
          onRetry={() => {
            void globalConfig.refetch();
            void clientConfig.refetch();
          }}
        />
      );
    }
  }

  const editableRules = (draft ?? []).filter((rule) => rule.origin === tier);

  function updateRule(id: string, patch: Partial<CategoryRule>) {
    setDraft((current) =>
      (current ?? []).map((rule) => (rule.id === id ? { ...rule, ...patch } : rule)),
    );
  }

  function addRule() {
    setDraft((current) => [
      ...(current ?? []),
      {
        id: newRuleId(), source_field: 'product_type', operator: 'eq',
        source_value: '', taxonomy_id: '', is_excluded: false, origin: tier,
      },
    ]);
  }

  function saveRules() {
    const payload: CategoryRule[] = editableRules.map(({ origin: _origin, ...rule }) => rule);
    validate.mutate(payload, {
      onSuccess: () => {
        save.mutate(
          { rules: payload },
          {
            onSuccess: () => notifySuccess(t('rules.saved')),
            onError: (error) => notifyApiError(error, t('rules.saveFailed')),
          },
        );
      },
      onError: (error) => notifyApiError(error, t('rules.validateFailed')),
    });
  }

  return (
    <Stack gap="md">
      {blocker.state === 'blocked' && (
        <ConfirmModal
          opened
          title={t('rules.confirmLeaveTitle')}
          body={t('rules.confirmLeave')}
          onConfirm={blocker.proceed}
          onCancel={blocker.reset}
        />
      )}
      <Group justify="space-between">
        <Title order={4}>{t('tabs.rules')}</Title>
        <Group>
          <Button variant="default" disabled={!dirty} onClick={() => setDraft(baseline)}>
            {t('rules.reset')}
          </Button>
          <Button disabled={!dirty} loading={save.isPending} onClick={saveRules}>
            {t('rules.save')}
          </Button>
          <Button variant="light" onClick={addRule}>{t('rules.add')}</Button>
        </Group>
      </Group>
      {(draft ?? []).length === 0 && <EmptyState>{t('rules.empty')}</EmptyState>}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={(event) => {
          const overIndex = event.over
            ? (draft ?? []).findIndex((rule) => rule.id === event.over!.id)
            : null;
          setDraft((current) =>
            applyRulesDragEnd(current ?? [], String(event.active.id), overIndex),
          );
        }}
      >
        <SortableContext
          items={(draft ?? []).map((rule) => rule.id)}
          strategy={verticalListSortingStrategy}
        >
          <Stack gap="sm">
            {(draft ?? []).map((rule) => (
              <RuleCardView
                key={rule.id}
                rule={rule}
                editable={rule.origin === tier}
                matchCount={stats.data?.rules?.[rule.id]}
                language={language}
                sourceFieldOptions={
                  registry.data?.map((attribute) => ({
                    value: attribute.name,
                    label: attribute.name,
                  })) ?? []
                }
                onUpdate={(patch) => updateRule(rule.id, patch)}
                onShowMatches={() => setMatchesRule(rule.id)}
                onDelete={() => setDeleting(rule.id)}
              />
            ))}
          </Stack>
        </SortableContext>
      </DndContext>
      {matchesRule !== null && (
        <MatchesModal
          feedSourceId={feedSourceId}
          ruleId={matchesRule}
          opened
          onClose={() => setMatchesRule(null)}
        />
      )}
      <ConfirmModal
        opened={deleting !== null}
        title={t('rules.deleteConfirmTitle')}
        body={t('rules.deleteConfirmBody', { id: deleting ?? '' })}
        onConfirm={() => {
          setDraft((current) => (current ?? []).filter((rule) => rule.id !== deleting));
          setDeleting(null);
        }}
        onCancel={() => setDeleting(null)}
      />
    </Stack>
  );
}
```

`RuleCardView` lives in the same file. It mirrors `customLabels/SortableRuleRow.tsx` for the `useSortable` drag handle (`listeners` spread on the `IconGripVertical` action icon, `attributes`, `transform`/`transition` on the Card) and renders, per rule:

- header row: drag handle + rule id + `ScopeBadge` with `t('rules.inherited')` when `!editable`, match-count `Badge` (`t('rules.matchesCount', { count })`, i18n plural keys) + "show matches" `ActionIcon` (only when `matchCount !== undefined`), delete `ActionIcon` (`IconTrash`, disabled when `!editable`);
- fields (all `disabled={!editable}`): `Select` source_field (`sourceFieldOptions`), `Select` operator (`OPERATORS.map(op => ({ value: op, label: t(`rules.operators.${op}`) }))`), value input — `Textarea` (3 rows, `t('rules.sourceValueIn')` label) when `operator === 'in'` with newline-split/join conversion, else `TextInput` (`t('rules.sourceValue')` label); `Switch` is_excluded (`t('rules.excluded')` label); `TaxonomyCombobox` (disabled when `rule.is_excluded`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run src/features/category/ && npm run typecheck`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/ozon/gmc_feed_master
git add frontend/src/features/category
git commit -m "feat(frontend): category rules tab — dnd editor, autocomplete, matches, dirty guard"
```


---

### Task 10: Manual Categorization tab

**Files:**
- Replace: `frontend/src/features/category/ManualTab.tsx` (full implementation)
- Test: `frontend/src/features/category/ManualTab.test.tsx`

**Interfaces:**
- Consumes: Task 7 `useCategoryProductState` + types; Task 9 `TaxonomyCombobox`; Task 8 shell props `{ pluginId, scope, language, feedSourceId }`; generic `usePluginData(pluginId, scope?, enabled?)` / `useSavePluginData(pluginId, scope?)` (hooks.ts:404-422); `notifyApiError`/`notifySuccess`.
- Produces: `ManualTab({ pluginId, scope, language, feedSourceId })` — read-modify-write of the `assignments` map through the generic data endpoint (client tier only).

- [ ] **Step 1: Write the failing tests** `frontend/src/features/category/ManualTab.test.tsx`

Cases (adapt to the real fetch-stub helper as in Tasks 8–9):

1. global scope (no `clientId`) renders the needs-client hint and issues no `/plugins/category/data` request;
2. product lookup: enter id + Look up (requires `feedSourceId` — stub the product endpoint) → renders title, provenance badge (e.g. "Auto (rule r-auto)"), current category;
3. assign: pick a taxonomy entry (stub `/plugins/category/taxonomy/search`), click Assign → `PUT /plugins/category/data?client_id=1` with body `{"assignments":{"p1":"166"}}`, success toast;
4. unassign: existing assignment renders the assignment badge + Remove button → PUT with the product removed from the map;
5. no feed source selected → Look up disabled with the `manual.selectFeedSource` hint;
6. save failure (stub PUT 500) → error toast.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run src/features/category/ManualTab.test.tsx`
Expected: FAIL (placeholder renders null)

- [ ] **Step 3: Implement** `frontend/src/features/category/ManualTab.tsx`:

```tsx
import { useState } from 'react';
import { Badge, Button, Group, Paper, Stack, Text, TextInput, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { usePluginData, useSavePluginData, type PluginScope } from '../../api/hooks';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { notifyApiError, notifySuccess } from '../../app/notifications';
import { useCategoryProductState } from './hooks';
import { TaxonomyCombobox } from './TaxonomyCombobox';

function assignmentsOf(payload: unknown): Record<string, string> {
  return (payload as { assignments?: Record<string, string> } | undefined)?.assignments ?? {};
}

export function ManualTab({
  pluginId,
  scope,
  language,
  feedSourceId,
}: {
  pluginId: string;
  scope: PluginScope;
  language: string;
  feedSourceId: number | undefined;
}) {
  const { t } = useTranslation('category');
  const clientId = scope.clientId;
  const dataScope = clientId !== undefined ? { clientId } : {};
  const data = usePluginData(pluginId, dataScope, clientId !== undefined);
  const save = useSavePluginData(pluginId, dataScope);
  const [productIdInput, setProductIdInput] = useState('');
  const [productId, setProductId] = useState<string | undefined>(undefined);
  const [pendingTaxonomy, setPendingTaxonomy] = useState<string | null>(null);
  const product = useCategoryProductState(feedSourceId ?? 0, productId);

  if (clientId === undefined) {
    return <EmptyState>{t('manual.needsClient')}</EmptyState>;
  }
  if (data.isLoading) return <LoadingState />;
  if (data.isError) return <ErrorState onRetry={() => void data.refetch()} />;

  const assignments = assignmentsOf(data.data);
  const currentAssignment = productId ? assignments[productId] : undefined;

  function persist(next: Record<string, string>) {
    save.mutate(
      { assignments: next },
      {
        onSuccess: () => notifySuccess(t('manual.saved')),
        onError: (error) => notifyApiError(error, t('manual.saveFailed')),
      },
    );
  }

  return (
    <Stack gap="md">
      <Title order={4}>{t('tabs.manual')}</Title>
      <Group align="flex-end">
        <TextInput
          label={t('manual.productId')}
          value={productIdInput}
          onChange={(event) => setProductIdInput(event.currentTarget.value)}
          w={280}
        />
        <Button
          disabled={feedSourceId === undefined || !productIdInput}
          onClick={() => setProductId(productIdInput || undefined)}
        >
          {t('manual.lookup')}
        </Button>
        {feedSourceId === undefined && (
          <Text size="xs" c="dimmed">{t('manual.selectFeedSource')}</Text>
        )}
      </Group>
      {productId && product.isError && (
        <Text c="red" size="sm">{t('manual.notFound')}</Text>
      )}
      {productId && product.data && (
        <Paper withBorder p="md">
          <Stack gap="xs">
            <Text fw={600}>{product.data.title ?? product.data.product_id}</Text>
            <Group gap="xs">
              <Text size="sm" c="dimmed">{t('manual.provenanceLabel')}</Text>
              <Badge variant="light">
                {product.data.provenance
                  ? t(`manual.provenance.${product.data.provenance}`, {
                      rule: product.data.rule_id ?? '',
                    })
                  : t('manual.provenance.null')}
              </Badge>
            </Group>
            <Group gap="xs">
              <Text size="sm" c="dimmed">{t('manual.categoryLabel')}</Text>
              <Text size="sm">
                {product.data.google_product_category || t('manual.none')}
              </Text>
            </Group>
            {currentAssignment !== undefined && (
              <Group gap="xs">
                <Text size="sm" c="dimmed">{t('manual.assignmentLabel')}</Text>
                <Badge color="green" variant="light">{currentAssignment}</Badge>
                <Button
                  size="xs"
                  color="red"
                  variant="light"
                  loading={save.isPending}
                  onClick={() => {
                    const next = { ...assignments };
                    delete next[productId];
                    persist(next);
                  }}
                >
                  {t('manual.unassign')}
                </Button>
              </Group>
            )}
            <Group grow align="flex-start">
              <TaxonomyCombobox
                language={language}
                value={pendingTaxonomy}
                onChange={setPendingTaxonomy}
              />
              <Button
                mt={22}
                disabled={!pendingTaxonomy}
                loading={save.isPending}
                onClick={() =>
                  persist({ ...assignments, [productId]: pendingTaxonomy ?? '' })
                }
              >
                {t('manual.assign')}
              </Button>
            </Group>
          </Stack>
        </Paper>
      )}
      {!productId && <EmptyState>{t('manual.empty')}</EmptyState>}
    </Stack>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run src/features/category/ && npm run typecheck`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/ozon/gmc_feed_master
git add frontend/src/features/category
git commit -m "feat(frontend): category manual-categorization tab"
```

---

### Task 11: Final gates + docs + TODO bookkeeping

**Files:**
- Modify: `frontend/docs/plugin-uis.md` (Category row: stub path + feature dir)
- Modify: `TODO.md` (cycle log + close 5.1 + 8.1 answered)
- Verify only: full gates

**Interfaces:**
- Consumes: everything.
- Produces: green full-stack gates + updated docs/backlog.

- [ ] **Step 1: Full frontend gate**

Run: `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run && npm run typecheck && npm run build`
Expected: all PASS, no chunk-size warnings.

- [ ] **Step 2: Full backend gate**

Run: `cd /home/ozon/gmc_feed_master/backend && uv run pytest -n auto && uv run ruff check . && uv run mypy .`
Expected: PASS / zero-new / baseline-held.

- [ ] **Step 3: Update `frontend/docs/plugin-uis.md`**

- Category row in "Core Plugin UIs (MVP)" — change `Custom (`Editor.tsx`)` to `Custom (`component.tsx` stub → `frontend/src/features/category/CategoryUI`)`.
- Add a short "Category" section after the Filter reference: tabs (Dashboard / Rules / Manual Categorization; AI + Uncategorized disabled placeholders), taxonomy language selector (en-US shipped, de-DE fetched via `POST /plugins/category/taxonomy/fetch`), tier semantics (config global+client with union-by-id merge view, Inherited badges; assignments client-only), per-rule match badges + matches modal (as-of-last-run), dirty-state guard via `useBlocker` + ConfirmModal.

- [ ] **Step 4: Update `TODO.md`**

- Mark 5.1 complete with a Done entry (Category UI shipped — the last core plugin UI; Labelizer/Rules/Filter UIs already existed).
- Mark 8.1 answered: owner picked the Category plugin as the next milestone (2026-09-09 brainstorming; spec `docs/superpowers/specs/2026-09-09-category-plugin-design.md`, plan this file). M12+ roadmap: supplemental feeds remain the open candidate.
- Append a cycle-log entry under "## Cycle log" (2026-09-09, branch `m12-category`): one line per task as executed, gate numbers (backend test count, ruff, mypy baseline, frontend test count, typecheck, build), deviations, head commit.

- [ ] **Step 5: Commit**

```bash
cd /home/ozon/gmc_feed_master
git add frontend/docs/plugin-uis.md TODO.md
git commit -m "docs: category cycle bookkeeping — plugin-uis, TODO cycle log"
```

- [ ] **Step 6: Final whole-branch review + merge**

Request the final whole-branch review (superpowers:requesting-code-review): reviewer re-verifies gates first-hand, checks spec-vs-plan conformance (all §1–§7 items), flags Critical/Important findings for pre-merge fixes. After approval: fast-forward merge `m12-category` → `main`, run the full gates on merged main, record head commit in the TODO cycle-log line.

---

## Plan self-review checklist (controller: verify before dispatch)

- Spec coverage: §1 manifest/scopes (T1), §2 taxonomy (T1/T4), §3 processing (T2/T3), §4 routes (T4/T5), §5 UI (T7-T10), §6 gates/docs (T6/T11), §7 out-of-scope honored (no live preview, no AI tabs beyond placeholders, de-DE only).
- Interface consistency: `taxonomy_index`/`_taxonomy_directory`/`_fetch_url` seams (T1→T4); `compile_rule`/`apply_category` (T2→T3); route paths match hooks.ts URLs exactly (T4/T5→T7); `ScopedCategoryRule`/`mergeRules` (T7→T8/T9); tab props `{ pluginId, scope, language, feedSourceId }` (T8→T9/T10).
- Known risks to watch in reviews: (1) the `__annotations__` patching is load-bearing — Task 4 Step 5 guards it; (2) `taxonomy_validate` answers path in the first available language, not the UI-selected one — search endpoint is the UI's display source; (3) draft save writes ONLY the editable tier's rules (inherited rules are never rewritten into the client tier) — the merge view is display-only; (4) `usePluginConfig` at the global route passes `{}` scope → URL without query params matches the global GET (`/plugins/category/config`).
