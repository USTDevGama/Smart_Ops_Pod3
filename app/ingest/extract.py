"""Reads an uploaded file into one markdown text.

TXT is read directly, PDF with pdfplumber and DOCX with python-docx. All three are text only:
there is no OCR, and figures are not read.
"""

import re

from app.ingest.docx_text import docx_markdown
from app.ingest.pdf_text import pdf_markdown
from app.schemas.enums import FileType

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def extract_markdown(data: bytes, file_type: FileType) -> str:
    if file_type is FileType.TXT:
        return _txt_markdown(data)
    if file_type is FileType.PDF:
        return pdf_markdown(data)
    return docx_markdown(data)


def _txt_markdown(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    return "\n\n".join(p.strip() for p in _PARAGRAPH_BREAK.split(text) if p.strip())
