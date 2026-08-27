from app.export.store import ExportFileStore


def test_write_version_creates_file_at_expected_path(tmp_path):
    store = ExportFileStore(tmp_path / "exports")
    path = store.write_version(7, 3, b"<xml/>")
    assert path == tmp_path / "exports" / "versions" / "7" / "3.xml"
    assert path.read_bytes() == b"<xml/>"


def test_publish_creates_file_at_expected_path(tmp_path):
    store = ExportFileStore(tmp_path / "exports")
    path = store.publish(7, b"<xml/>")
    assert path == tmp_path / "exports" / "published" / "7.xml"
    assert path.read_bytes() == b"<xml/>"


def test_writes_leave_no_temp_files(tmp_path):
    store = ExportFileStore(tmp_path / "exports")
    store.write_version(1, 1, b"a")
    store.publish(1, b"b")
    leftovers = [p.name for p in tmp_path.rglob("*") if p.is_file() and ".tmp" in p.name]
    assert leftovers == []


def test_publish_replaces_existing_atomically(tmp_path):
    store = ExportFileStore(tmp_path / "exports")
    store.publish(1, b"old")
    store.publish(1, b"new")
    assert store.published_path(1).read_bytes() == b"new"


def test_published_exists(tmp_path):
    store = ExportFileStore(tmp_path / "exports")
    assert store.published_exists(1) is False
    store.publish(1, b"x")
    assert store.published_exists(1) is True


def test_read_version_returns_bytes_or_none(tmp_path):
    store = ExportFileStore(tmp_path / "exports")
    assert store.read_version(1, 1) is None
    store.write_version(1, 1, b"data")
    assert store.read_version(1, 1) == b"data"


def test_delete_version_file_is_idempotent(tmp_path):
    store = ExportFileStore(tmp_path / "exports")
    store.delete_version_file(1, 1)
    store.write_version(1, 1, b"data")
    store.delete_version_file(1, 1)
    assert store.read_version(1, 1) is None
