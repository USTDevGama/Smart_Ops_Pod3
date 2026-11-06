"""Reads a Word file with python-docx into markdown: its paragraphs and tables, in document order.

Headings become `#` lines, list items become `-` lines, and tables become markdown tables. Word
files have no pages. Text boxes, headers, footers and footnotes are not read. Pictures are ignored.
"""

import logging
import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.ingest.errors import ExtractionError
from app.ingest.tables import table_markdown

log = logging.getLogger(__name__)

_HEADING = re.compile(r"Heading (\d)")


def docx_markdown(path: Path) -> str:
    try:
        document = Document(str(path))
        parts: list[str] = []
        # The body holds paragraphs and tables mixed together; walking it keeps their order.
        for child in document.element.body.iterchildren():
            if child.tag == qn("w:p"):
                text = _paragraph_markdown(Paragraph(child, document))
            elif child.tag == qn("w:tbl"):
                text = table_markdown(_rows(Table(child, document)))
            else:
                continue
            if text:
                parts.append(text)
        return "\n\n".join(parts)
    except Exception as exc:
        # Log the exception type only: its message can echo file content.
        log.warning("python-docx failed on the file: %s", type(exc).__name__)
        raise ExtractionError("the file could not be read") from None


def _paragraph_markdown(paragraph: Paragraph) -> str:
    text = paragraph.text.strip()
    if not text:
        return ""
    style = paragraph.style.name if paragraph.style is not None else ""
    if style == "Title":
        return f"# {text}"
    heading = _HEADING.fullmatch(style)
    if heading:
        return f"{'#' * int(heading.group(1))} {text}"
    if style.startswith("List") or _has_numbering(paragraph):
        return f"- {text}"
    return text


def _has_numbering(paragraph: Paragraph) -> bool:
    properties = paragraph._p.find(qn("w:pPr"))
    return properties is not None and properties.find(qn("w:numPr")) is not None


def _rows(table: Table) -> list[list[str]]:
    rows = []
    for row in table.rows:
        seen: set[int] = set()
        cells = []
        for cell in row.cells:
            # A merged cell is returned once per column it spans; keep it once.
            if id(cell._tc) not in seen:
                seen.add(id(cell._tc))
                cells.append(cell.text)
        rows.append(cells)
    return rows
