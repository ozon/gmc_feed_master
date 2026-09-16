from __future__ import annotations

from app.ai.taxonomy import TAXONOMY_CSV, known_taxonomy_ids


def test_taxonomy_csv_exists() -> None:
    assert TAXONOMY_CSV.exists(), f"missing {TAXONOMY_CSV}"


def test_known_ids_non_empty_and_integer() -> None:
    ids = known_taxonomy_ids()
    assert len(ids) > 1000
    assert all(isinstance(i, int) for i in ids)


def test_known_id_from_google_taxonomy() -> None:
    assert 2271 in known_taxonomy_ids()


def test_unknown_id_is_absent() -> None:
    assert 999999999 not in known_taxonomy_ids()


def test_result_is_cached() -> None:
    assert known_taxonomy_ids() is known_taxonomy_ids()
