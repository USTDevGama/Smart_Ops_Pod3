"""Where uploaded files live. A local folder now; S3 or Azure Blob later behind the same methods."""

import uuid
from pathlib import Path
from typing import Protocol

from app.config import get_settings


class BlobStore(Protocol):
    def save(self, data: bytes, suffix: str, name: str | None = None) -> str: ...

    def read(self, uri: str) -> bytes: ...

    def delete(self, uri: str) -> None: ...

    def exists(self, uri: str) -> bool: ...


class LocalBlobStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def save(self, data: bytes, suffix: str, name: str | None = None) -> str:
        """Store `data`. A given `name` (like "reports/<id>/report.pdf") is the uri and is
        overwritten on a second save, so a retried job leaves one file; otherwise a random name."""
        uri = name or f"{uuid.uuid4().hex}{suffix}"
        path = self._path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return uri

    def read(self, uri: str) -> bytes:
        return self._path(uri).read_bytes()

    def delete(self, uri: str) -> None:
        self._path(uri).unlink(missing_ok=True)

    def exists(self, uri: str) -> bool:
        return self._path(uri).is_file()

    def _path(self, uri: str) -> Path:
        path = (self.root / uri).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("blob uri escapes the storage folder")
        return path


def get_blob_store() -> BlobStore:
    return LocalBlobStore(get_settings().blob_dir)
