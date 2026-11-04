"""Reads an uploaded file into text blocks. PDF and DOCX go through Docling; TXT is read directly.

Each block knows its page and whether OCR produced it, so a citation can say "page 7" and a
low-quality scan can be flagged.
"""

import logging
import re
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import (
    ConvertPipelineOptions,
    OcrOptions,
    PdfPipelineOptions,
    RapidOcrOptions,
    TesseractCliOcrOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption, WordFormatOption
from docling_core.types.doc import (
    BoundingBox,
    CoordOrigin,
    DocItemLabel,
    PictureItem,
    TableItem,
    TextItem,
)

from app.ingest.chunk import RawBlock
from app.ingest.figures import figure_description, figure_label, figure_text, looks_like_caption
from app.schemas.enums import FileType, SegmentKind

log = logging.getLogger(__name__)

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
# A text item counts as OCR text when most of the area it covers was read by OCR.
_OCR_OVERLAP = 0.5

OcrEngine = Literal["tesseract", "rapidocr"]
# `ocr_lang` is a Tesseract code; RapidOCR names its languages in words.
_RAPIDOCR_LANGS = {"eng": "english"}


class ExtractionError(Exception):
    """The file could not be read. The message is fixed and never contains file text."""


class OcrUnavailable(Exception):
    """A file needs OCR but the OCR engine cannot run on this machine (no tesseract binary).

    Not the file's fault, so it is not an `ExtractionError`: the job is retried (and the row
    goes back to `queued`) instead of the upload being marked failed.
    """


def extract_blocks(
    path: Path,
    file_type: FileType,
    *,
    ocr_enabled: bool,
    ocr_lang: str,
    ocr_engine: OcrEngine = "rapidocr",
    tesseract_cmd: str = "tesseract",
    figures: bool = True,
    figure_descriptions: bool = False,
    debug_dir: Path | None = None,
) -> list[RawBlock]:
    # Plain text is read directly: it has no images, so OCR and Docling are never involved.
    if file_type is FileType.TXT:
        return _txt_blocks(path)
    return _docling_blocks(
        path,
        file_type,
        ocr_enabled=ocr_enabled,
        ocr_lang=ocr_lang,
        ocr_engine=ocr_engine,
        tesseract_cmd=tesseract_cmd,
        figures=figures,
        describe=figures and figure_descriptions,
        debug_dir=debug_dir,
    )


def _txt_blocks(path: Path) -> list[RawBlock]:
    text = path.read_bytes().decode("utf-8", errors="replace").strip()
    return [
        RawBlock(page=1, kind=SegmentKind.TEXT, text=p.strip())
        for p in _PARAGRAPH_BREAK.split(text)
    ]


def _ocr_options(engine: OcrEngine, lang: str, tesseract_cmd: str) -> OcrOptions:
    if engine == "tesseract":
        return TesseractCliOcrOptions(lang=[lang], tesseract_cmd=tesseract_cmd)
    # The torch backend: the default (onnxruntime) is not installed, and Docling already
    # depends on torch and caches RapidOCR's PyTorch weights.
    return RapidOcrOptions(backend="torch", lang=[_RAPIDOCR_LANGS.get(lang, lang)])


@lru_cache(maxsize=8)
def _converter(
    ocr_active: bool,
    engine: OcrEngine,
    ocr_lang: str,
    tesseract_cmd: str,
    figures: bool,
    describe: bool,
    keep_images: bool,
) -> DocumentConverter:
    """Built once per process: loading the Docling models is slow."""
    # generate_parsed_pages keeps the per-word cells (from_ocr, confidence) that _ocr_status
    # reads. Without it Docling drops them and every block would look like native text.
    pdf_options = PdfPipelineOptions(
        do_ocr=ocr_active,
        generate_parsed_pages=ocr_active or figures,
        do_picture_classification=figures,
        do_picture_description=describe,
        generate_picture_images=keep_images,
    )
    if ocr_active:
        pdf_options.ocr_options = _ocr_options(engine, ocr_lang, tesseract_cmd)
    # Word files go through a separate, simpler pipeline: it has no OCR, but it can still
    # classify and describe pictures.
    word_options = ConvertPipelineOptions(
        do_picture_classification=figures,
        do_picture_description=describe,
        generate_picture_images=keep_images,
    )
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
            InputFormat.DOCX: WordFormatOption(pipeline_options=word_options),
        }
    )


def _docling_blocks(
    path: Path,
    file_type: FileType,
    *,
    ocr_enabled: bool,
    ocr_lang: str,
    ocr_engine: OcrEngine,
    tesseract_cmd: str,
    figures: bool,
    describe: bool,
    debug_dir: Path | None,
) -> list[RawBlock]:
    # Docling refuses to convert any PDF, even one with a text layer, when Tesseract is the
    # engine and its binary is missing. So read without OCR instead, and only fail if the
    # file needed it. RapidOCR is pure Python and has no binary to miss.
    ocr_missing = ocr_enabled and ocr_engine == "tesseract" and shutil.which(tesseract_cmd) is None
    if ocr_missing:
        log.warning("OCR is enabled but %r was not found; reading without OCR", tesseract_cmd)
    try:
        converter = _converter(
            ocr_enabled and not ocr_missing,
            ocr_engine,
            ocr_lang,
            tesseract_cmd,
            figures,
            describe,
            debug_dir is not None,
        )
        result = converter.convert(str(path))
    except Exception as exc:
        # Log the exception type only: its message can echo file content.
        log.warning("docling failed on %s file: %s", file_type.value, type(exc).__name__)
        raise ExtractionError("the file could not be read") from None
    if result.status not in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS):
        raise ExtractionError("the file could not be read")

    doc = result.document
    pages = {page.page_no: page for page in result.pages}
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "docling.md").write_text(doc.export_to_markdown(), encoding="utf-8")

    blocks: list[RawBlock] = []
    figure_count = 0
    # The last figure that has no caption yet, and where its block sits in `blocks`.
    uncaptioned: tuple[int, _Figure] | None = None
    # Picture children (the caption and the text read inside a figure) are only visited when
    # figures are on, and are then folded into the figure's own block, not emitted separately.
    for item, _level in doc.iterate_items(traverse_pictures=figures):
        # DOCX has no pages, so everything is page 1 (the same convention as TXT).
        page_no = item.prov[0].page_no if item.prov and file_type is FileType.PDF else 1
        page = pages.get(page_no)
        if isinstance(item, PictureItem):
            if not figures:
                continue
            figure_count += 1
            figure = _read_figure(item, doc, page, page_no, describe)
            block = figure.block()
            if block is not None:
                blocks.append(block)
            uncaptioned = (len(blocks) - 1, figure) if block and not figure.caption else None
            if debug_dir is not None:
                _save_figure_image(item, doc, debug_dir, page_no, figure_count)
            continue
        if figures and _inside_picture(item):
            continue
        if isinstance(item, TableItem):
            text = item.export_to_markdown(doc=doc)
        elif isinstance(item, TextItem):
            text = item.text
        else:
            continue
        if not text.strip():
            continue
        if uncaptioned is not None:
            index, figure = uncaptioned
            uncaptioned = None  # only the paragraph right after the figure can be its caption
            if looks_like_caption(text) and page_no == figure.page:
                figure.caption = text.strip()
                blocks[index] = figure.block()
                continue
        kind, confidence = _ocr_status(item, page)
        blocks.append(RawBlock(page=page_no, kind=kind, text=text, ocr_confidence=confidence))
    if not blocks and ocr_missing and file_type is FileType.PDF:
        # An image-only PDF: the text would only have come from OCR.
        raise OcrUnavailable(f"OCR is enabled but {tesseract_cmd!r} was not found")
    return blocks


def _inside_picture(item) -> bool:
    parent = getattr(item, "parent", None)
    return parent is not None and parent.cref.startswith("#/pictures/")


@dataclass
class _Figure:
    """What was found for one figure. Kept apart from the block so a caption that turns up in
    the next paragraph (Word does not link it) can still be added."""

    page: int
    label: str | None
    caption: str
    inner_text: list[str]
    description: str | None
    confidence: float | None

    def block(self) -> RawBlock | None:
        text = figure_text(self.label, self.caption, self.inner_text, self.description)
        if text is None:
            return None
        return RawBlock(self.page, SegmentKind.FIGURE, text, self.confidence)


def _read_figure(item: PictureItem, doc, page, page_no: int, describe: bool) -> _Figure:
    inner_text: list[str] = []
    confidences: list[float] = []
    for ref in item.children:
        child = ref.resolve(doc)
        if not isinstance(child, TextItem) or child.label == DocItemLabel.CAPTION:
            continue  # the caption is read below, from the figure itself
        text = child.text.strip()
        if not text:
            continue
        inner_text.append(text)
        kind, confidence = _ocr_status(child, page)
        if kind is SegmentKind.OCR and confidence is not None:
            confidences.append(confidence)

    figure = _Figure(
        page=page_no,
        label=figure_label(item),
        caption=item.caption_text(doc).strip(),
        inner_text=inner_text,
        description=figure_description(item) if describe else None,
        confidence=sum(confidences) / len(confidences) if confidences else None,
    )
    # Counts and the figure type only: never the proposal's own text.
    log.info(
        "figure page=%s type=%s caption=%s inner_text_items=%d described=%s",
        page_no,
        figure.label,
        bool(figure.caption),
        len(inner_text),
        describe,
    )
    return figure


def _save_figure_image(item: PictureItem, doc, debug_dir: Path, page_no: int, number: int) -> None:
    image = item.get_image(doc)
    if image is not None:
        image.save(debug_dir / f"figure-{number}-page{page_no}.png")


def _ocr_status(item, page) -> tuple[SegmentKind, float | None]:
    """Mark an item as OCR text when the OCR-read cells over it are the majority."""
    if page is None or not page.cells or not item.prov:
        return SegmentKind.TEXT, None
    height = page.size.height
    box = _top_left(item.prov[0].bbox, height)
    covering = []
    for cell in page.cells:
        cell_box = _top_left(cell.rect.to_bounding_box(), height)
        area = cell_box.area()
        if area > 0 and box.intersection_area_with(cell_box) / area >= _OCR_OVERLAP:
            covering.append(cell)
    ocr_cells = [cell for cell in covering if cell.from_ocr]
    if not ocr_cells or len(ocr_cells) <= len(covering) - len(ocr_cells):
        return SegmentKind.TEXT, None
    scores = [cell.confidence for cell in ocr_cells if cell.confidence is not None]
    return SegmentKind.OCR, (sum(scores) / len(scores) if scores else None)


def _top_left(box: BoundingBox, page_height: float) -> BoundingBox:
    if box.coord_origin == CoordOrigin.TOPLEFT:
        return box
    return box.to_top_left_origin(page_height)
