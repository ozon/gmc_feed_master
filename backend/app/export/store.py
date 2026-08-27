from __future__ import annotations

import os
from pathlib import Path


def _atomic_write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path


class ExportFileStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def published_path(self, feed_source_id: int) -> Path:
        return self._root / "published" / f"{feed_source_id}.xml"

    def version_path(self, feed_source_id: int, version_number: int) -> Path:
        return self._root / "versions" / str(feed_source_id) / f"{version_number}.xml"

    def write_version(self, feed_source_id: int, version_number: int, data: bytes) -> Path:
        return _atomic_write(self.version_path(feed_source_id, version_number), data)

    def publish(self, feed_source_id: int, data: bytes) -> Path:
        return _atomic_write(self.published_path(feed_source_id), data)

    def published_exists(self, feed_source_id: int) -> bool:
        return self.published_path(feed_source_id).is_file()

    def read_version(self, feed_source_id: int, version_number: int) -> bytes | None:
        path = self.version_path(feed_source_id, version_number)
        if not path.is_file():
            return None
        return path.read_bytes()

    def delete_version_file(self, feed_source_id: int, version_number: int) -> None:
        self.version_path(feed_source_id, version_number).unlink(missing_ok=True)
