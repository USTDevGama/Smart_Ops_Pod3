"""Checks on an uploaded file before anything parses it. Uploads are untrusted input."""

import io
import posixpath
import re
import zipfile

from app.schemas.enums import FileType

EXTENSIONS = {".pdf": FileType.PDF, ".docx": FileType.DOCX, ".txt": FileType.TXT}
MAX_NAME_CHARS = 255
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class UploadRejected(Exception):
    """The upload is refused. The message is short and safe to show the trainee."""


def file_type_for(filename: str) -> FileType:
    """Decide the type from the extension. The content is checked separately."""
    suffix = posixpath.splitext(filename.replace("\\", "/").lower())[1]
    try:
        return EXTENSIONS[suffix]
    except KeyError:
        raise UploadRejected("only PDF, DOCX and TXT files are accepted") from None


def check_size(data: bytes, max_bytes: int) -> None:
    if not data:
        raise UploadRejected("the file is empty")
    if len(data) > max_bytes:
        raise UploadRejected("the file is larger than the upload limit")


def check_content(data: bytes, file_type: FileType) -> None:
    """The bytes must match the claimed type, so a renamed file is refused."""
    if file_type is FileType.PDF:
        ok = data.startswith(b"%PDF-")
    elif file_type is FileType.DOCX:
        ok = _is_docx(data)
    else:
        # Plain text: no NUL bytes (a binary file would have them).
        ok = b"\x00" not in data
    if not ok:
        raise UploadRejected(f"the file content is not a valid {file_type.value.upper()}")


def _is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def display_name(filename: str | None) -> str:
    """A name for display only. It is never used as a file path."""
    base = posixpath.basename((filename or "").replace("\\", "/"))
    cleaned = _CONTROL_CHARS.sub("", base).strip()
    return (cleaned or "proposal")[:MAX_NAME_CHARS]
