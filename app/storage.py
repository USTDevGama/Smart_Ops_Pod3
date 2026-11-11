"""Where uploaded files live. A local folder now; S3 or Azure Blob later behind the same methods."""

import logging
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import get_settings

log = logging.getLogger(__name__)

# Where files go when the configured folder cannot be written (see `get_blob_store`).
FALLBACK_DIR_NAME = "podc-blobs"


class BlobStore(Protocol):
    def save(self, data: bytes, suffix: str = "", name: str | None = None) -> str: ...

    def read(self, uri: str) -> bytes: ...

    def delete(self, uri: str) -> None: ...

    def exists(self, uri: str) -> bool: ...


class LocalBlobStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def save(self, data: bytes, suffix: str = "", name: str | None = None) -> str:
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


@lru_cache
def _usable_root(configured: str) -> Path:
    """The configured folder if files can be written there, otherwise a folder in the system's
    temp directory. Checked once per folder, and the fallback is logged once."""
    folder = Path(configured)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".write-test-{uuid.uuid4().hex}"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        fallback = Path(tempfile.gettempdir()) / FALLBACK_DIR_NAME
        log.warning("blob folder %s cannot be written; using %s instead", folder, fallback)
        return fallback
    return folder


def get_blob_store() -> BlobStore:
    """The configured blob folder, or a temp folder when there is none that works, so uploads and
    reports are never lost to a missing or read-only folder. The temp folder is the same for every
    process on the machine, so the API and the worker still find each other's files."""
    return LocalBlobStore(_usable_root(get_settings().blob_dir))
