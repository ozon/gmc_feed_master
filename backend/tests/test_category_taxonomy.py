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
            cp.parse_taxonomy_csv("1,,,,,,")

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
