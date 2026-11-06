"""The checks every upload goes through (profile by a trainee, demand document by an admin)."""

import hashlib
import os
from typing import NamedTuple

from fastapi import HTTPException, UploadFile, status

from app.config import get_settings
from app.schemas.enums import FileType

_SUFFIX = {".pdf": FileType.PDF, ".docx": FileType.DOCX, ".txt": FileType.TXT}


class Upload(NamedTuple):
    filename: str
    data: bytes
    file_type: FileType
    sha256: str


def detect_type(filename: str, data: bytes) -> FileType:
    """The extension AND the first bytes must agree, so a renamed file is refused."""
    file_type = _SUFFIX.get(os.path.splitext(filename)[1].lower())
    if file_type is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "only PDF, DOCX or TXT")
    if file_type == FileType.PDF:
        ok = data.startswith(b"%PDF-")
    elif file_type == FileType.DOCX:
        ok = data.startswith(b"PK\x03\x04")
    else:
        try:
            data.decode("utf-8")
            ok = b"\x00" not in data
        except UnicodeDecodeError:
            ok = False
    if not ok:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"the content is not a valid {file_type.value}"
        )
    return file_type


def read_upload(file: UploadFile) -> Upload:
    """Read the file, refusing one that is too large, empty or not what its name says."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "file is too large")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "file is empty")
    filename = os.path.basename(file.filename or "upload")[:255]
    return Upload(filename, data, detect_type(filename, data), hashlib.sha256(data).hexdigest())
