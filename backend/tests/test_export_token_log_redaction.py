import logging

from app.main import _ExportTokenRedactor, _install_export_token_log_redaction


def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:54321", "GET", path, "1.1", 200),
        exc_info=None,
    )


def test_export_token_redacted_in_access_record() -> None:
    record = _access_record("/export/secret-token-value.xml")
    assert _ExportTokenRedactor().filter(record) is True
    assert record.args[2] == "/export/[REDACTED]"
    assert "secret-token-value" not in record.getMessage()


def test_non_export_path_is_untouched() -> None:
    record = _access_record("/health")
    assert _ExportTokenRedactor().filter(record) is True
    assert record.args[2] == "/health"
    assert record.getMessage().endswith('GET /health HTTP/1.1" 200')


def test_redaction_preserves_five_tuple_for_uvicorn_formatter() -> None:
    record = _access_record("/export/abc123.xml")
    _ExportTokenRedactor().filter(record)
    client_addr, method, full_path, http_version, status_code = record.args
    assert client_addr == "127.0.0.1:54321"
    assert method == "GET"
    assert full_path == "/export/[REDACTED]"
    assert http_version == "1.1"
    assert status_code == 200


def test_non_tuple_args_are_left_alone() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="plain message",
        args=None,
        exc_info=None,
    )
    assert _ExportTokenRedactor().filter(record) is True
    assert record.args is None


def test_install_is_idempotent() -> None:
    logger = logging.getLogger("uvicorn.access")
    try:
        _install_export_token_log_redaction()
        first = sum(isinstance(f, _ExportTokenRedactor) for f in logger.filters)
        _install_export_token_log_redaction()
        second = sum(isinstance(f, _ExportTokenRedactor) for f in logger.filters)
        assert first == 1
        assert second == 1
    finally:
        logger.filters = [
            f for f in logger.filters if not isinstance(f, _ExportTokenRedactor)
        ]
