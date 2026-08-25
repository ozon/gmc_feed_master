from app.ingest.report import IngestReport, RowError


def test_imports() -> None:
    assert IngestReport is not None
    assert RowError is not None
