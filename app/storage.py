"""Where uploaded files live. A local folder now; S3 or Azure Blob later behind the same methods."""

import uuid
from pathlib import Path
from typing import Protocol

from app.config import get_settings


class BlobStore(Protocol):
    def save(self, data: bytes, suffix: str) -> str: ...

    def read(self, uri: str) -> bytes: ...

    def delete(self, uri: str) -> None: ...


class LocalBlobStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def save(self, data: bytes, suffix: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}{suffix}"
        (self.root / name).write_bytes(data)
        return name

    def read(self, uri: str) -> bytes:
        return self._path(uri).read_bytes()

    def delete(self, uri: str) -> None:
        self._path(uri).unlink(missing_ok=True)

    def _path(self, uri: str) -> Path:
        path = (self.root / uri).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("blob uri escapes the storage folder")
        return path


def get_blob_store() -> BlobStore:
    return LocalBlobStore(get_settings().blob_dir)
