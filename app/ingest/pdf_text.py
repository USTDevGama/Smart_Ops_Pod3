"""Reads PDFs that have a text layer with pdfplumber.

Text only: no OCR, so a scanned page (text that exists only as pixels) is not read. Figures and
charts are not read either; the words in them are not part of the text layer. If a whole PDF has
no text layer it is refused with a clear message, so the trainee knows to upload a text-based PDF.
"""

import logging
from pathlib import Path

import pdfplumber

from app.ingest.errors import ExtractionError
from app.ingest.tables import table_markdown

log = logging.getLogger(__name__)

NO_TEXT_LAYER = "this PDF has no text layer (it looks like a scan): upload a text-based PDF"

# A page with fewer characters than this has no usable text layer.
MIN_PAGE_CHARS = 20
# An image covering at least this share of a page is a picture of the page, not a logo.
MIN_IMAGE_SHARE = 0.03
# A gap between two lines larger than this share of a line's height starts a new paragraph.
PARAGRAPH_GAP = 0.6


def pdf_markdown(path: Path) -> str:
    """The whole document as markdown, with a `<!-- page N -->` marker before each page's text.

    Paragraphs and tables stay in page order, one blank line apart. Pages with no text get no
    marker, but the numbers of the pages that do are their real page numbers.
    """
    scanned_pages = 0
    parts: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            for number, page in enumerate(pdf.pages, start=1):
                page_parts = _page_parts(page)
                if not page_parts and _looks_scanned(page):
                    scanned_pages += 1
                if page_parts:
                    parts.append(f"<!-- page {number} -->")
                    parts.extend(page_parts)
                _release(page)
    except Exception as exc:
        # Log the exception type only: its message can echo file content.
        log.warning("pdfplumber failed on the file: %s", type(exc).__name__)
        raise ExtractionError("the file could not be read") from None

    if scanned_pages:
        # Counts only, never the proposal's own text.
        log.warning("%d page(s) have no text layer and were skipped", scanned_pages)
        if not parts:
            raise ExtractionError(NO_TEXT_LAYER)
    return "\n\n".join(parts)


def _page_parts(page) -> list[str]:
    tables = page.find_tables()
    boxes = [table.bbox for table in tables]
    # (top of the item on the page, text): sorted at the end so tables stay in reading order.
    items: list[tuple[float, str]] = []

    for table in tables:
        markdown = table_markdown(table.extract())
        if markdown:
            items.append((table.bbox[1], markdown))

    outside = page.filter(lambda obj: not _inside_any(obj, boxes))
    items.extend(_paragraphs(outside.extract_text_lines(strip=True, return_chars=False)))

    return [text for _top, text in sorted(items, key=lambda item: item[0])]


def _paragraphs(lines: list[dict]) -> list[tuple[float, str]]:
    """Group text lines into paragraphs by the vertical gap between them."""
    paragraphs: list[tuple[float, str]] = []
    current: list[str] = []
    start = 0.0
    previous = None
    for line in lines:
        text = line["text"].strip()
        if not text:
            continue
        if previous is not None:
            height = max(previous["bottom"] - previous["top"], 1.0)
            if line["top"] - previous["bottom"] > PARAGRAPH_GAP * height:
                paragraphs.append((start, " ".join(current)))
                current = []
        if not current:
            start = line["top"]
        current.append(text)
        previous = line
    if current:
        paragraphs.append((start, " ".join(current)))
    return paragraphs


def _inside_any(obj: dict, boxes: list[tuple[float, float, float, float]]) -> bool:
    """Whether an object's centre falls inside any of the boxes (left, top, right, bottom)."""
    if "x0" not in obj or "top" not in obj:
        return False
    x = (obj["x0"] + obj["x1"]) / 2
    y = (obj["top"] + obj["bottom"]) / 2
    return any(left <= x <= right and top <= y <= bottom for left, top, right, bottom in boxes)


def _looks_scanned(page) -> bool:
    """No text layer, and a large image: the page is a picture of text."""
    return len(page.chars) < MIN_PAGE_CHARS and _image_share(page) >= MIN_IMAGE_SHARE


def _image_share(page) -> float:
    """The share of the page covered by images, counting only the part that is on the page."""
    page_area = page.width * page.height
    covered = 0.0
    for image in page.images:
        width = min(image["x1"], page.width) - max(image["x0"], 0)
        height = min(image["bottom"], page.height) - max(image["top"], 0)
        if width > 0 and height > 0:
            covered += width * height
    return covered / page_area if page_area else 0.0


def _release(page) -> None:
    """Drop the page's parsed objects so a long PDF does not hold every page in memory."""
    flush = getattr(page, "flush_cache", None)
    if flush is not None:
        flush()
