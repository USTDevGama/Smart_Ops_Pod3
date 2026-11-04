import shutil
from types import SimpleNamespace

import pytest
from docling_core.types.doc import BoundingBox, CoordOrigin

from app.ingest import extract
from app.ingest.extract import ExtractionError, OcrUnavailable, _ocr_status, extract_blocks
from app.schemas.enums import FileType, SegmentKind
from tests.ingest_fixtures import make_docx, make_pdf, make_scanned_pdf

# Native files need no OCR, so these run with OCR off and without the tesseract binary.
NATIVE = {"ocr_enabled": False, "ocr_lang": "eng"}
HAS_TESSERACT = shutil.which("tesseract") is not None
NO_TESSERACT = "no-such-tesseract-binary"  # a command that is certainly not installed
TESSERACT_MISSING = {
    "ocr_enabled": True,
    "ocr_lang": "eng",
    "ocr_engine": "tesseract",
    "tesseract_cmd": NO_TESSERACT,
}


def test_txt_is_split_into_paragraphs_on_page_one(tmp_path):
    path = tmp_path / "plan.txt"
    path.write_bytes(b"Budget is 400000.\n\nTimeline is six months.\n")
    blocks = extract_blocks(path, FileType.TXT, **NATIVE)
    assert [(b.page, b.kind, b.text) for b in blocks] == [
        (1, SegmentKind.TEXT, "Budget is 400000."),
        (1, SegmentKind.TEXT, "Timeline is six months."),
    ]


def test_docx_text_and_headings_are_read(tmp_path):
    path = tmp_path / "plan.docx"
    path.write_bytes(make_docx([("Budget", "The total budget is 400000."), ("", "No risks.")]))
    blocks = extract_blocks(path, FileType.DOCX, **NATIVE)
    texts = " | ".join(b.text for b in blocks)
    assert "The total budget is 400000." in texts
    assert "No risks." in texts
    assert {b.page for b in blocks} == {1}  # DOCX has no pages
    assert all(b.kind is SegmentKind.TEXT for b in blocks)


def test_native_pdf_text_is_read_with_its_page(tmp_path):
    path = tmp_path / "plan.pdf"
    path.write_bytes(make_pdf(["Budget is 400000 dollars.", "Timeline is six months."]))
    blocks = extract_blocks(path, FileType.PDF, **NATIVE)
    text = " ".join(b.text for b in blocks)
    assert "400000" in text and "six months" in text
    assert {b.page for b in blocks} == {1}
    assert all(b.kind is SegmentKind.TEXT and b.ocr_confidence is None for b in blocks)


def test_corrupt_pdf_raises_a_fixed_safe_message(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\nSECRET PROPOSAL TEXT that is not really a pdf")
    with pytest.raises(ExtractionError) as info:
        extract_blocks(path, FileType.PDF, **NATIVE)
    assert str(info.value) == "the file could not be read"
    assert "SECRET" not in str(info.value)


def test_txt_never_uses_docling_or_ocr(tmp_path, monkeypatch):
    """Even with OCR on and no tesseract, a TXT file is read directly."""

    def forbidden(*args, **kwargs):
        raise AssertionError("TXT must not go through Docling")

    monkeypatch.setattr(extract, "_converter", forbidden)
    path = tmp_path / "plan.txt"
    path.write_bytes(b"Budget is 400000.")
    blocks = extract_blocks(path, FileType.TXT, **TESSERACT_MISSING)
    assert [b.text for b in blocks] == ["Budget is 400000."]


def test_native_pdf_is_still_read_when_ocr_is_on_but_tesseract_is_missing(tmp_path):
    path = tmp_path / "plan.pdf"
    path.write_bytes(make_pdf(["Budget is 400000 dollars."]))
    blocks = extract_blocks(path, FileType.PDF, **TESSERACT_MISSING)
    assert "400000" in " ".join(b.text for b in blocks)
    assert all(b.kind is SegmentKind.TEXT for b in blocks)


def test_scanned_pdf_without_tesseract_is_an_infrastructure_error_not_a_bad_file(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_scanned_pdf("Budget is 400000 dollars"))
    with pytest.raises(OcrUnavailable):
        extract_blocks(path, FileType.PDF, **TESSERACT_MISSING)


def test_scanned_pdf_with_ocr_switched_off_is_just_empty(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_scanned_pdf("Budget is 400000 dollars"))
    assert extract_blocks(path, FileType.PDF, **NATIVE) == []


def test_scanned_page_is_read_by_rapidocr_and_marked_as_ocr(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_scanned_pdf("Budget is 400000 dollars"))

    blocks = extract_blocks(
        path, FileType.PDF, ocr_enabled=True, ocr_lang="eng", ocr_engine="rapidocr"
    )

    assert blocks, "expected text from the scanned page"
    assert all(b.kind is SegmentKind.OCR for b in blocks)
    assert all(b.ocr_confidence is not None and 0 < b.ocr_confidence <= 1 for b in blocks)
    assert "400000" in " ".join(b.text for b in blocks)


def test_native_pdf_stays_text_when_rapidocr_is_on(tmp_path):
    path = tmp_path / "plan.pdf"
    path.write_bytes(make_pdf(["Budget is 400000 dollars."]))
    blocks = extract_blocks(
        path, FileType.PDF, ocr_enabled=True, ocr_lang="eng", ocr_engine="rapidocr"
    )
    assert "400000" in " ".join(b.text for b in blocks)
    assert all(b.kind is SegmentKind.TEXT and b.ocr_confidence is None for b in blocks)


@pytest.mark.skipif(not HAS_TESSERACT, reason="needs the tesseract binary (OCR)")
def test_scanned_page_is_read_by_tesseract(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_scanned_pdf("Budget is 400000 dollars"))

    blocks = extract_blocks(
        path, FileType.PDF, ocr_enabled=True, ocr_lang="eng", ocr_engine="tesseract"
    )
    ocr = [b for b in blocks if b.kind is SegmentKind.OCR]
    assert ocr, "expected at least one block read by OCR"
    assert all(b.ocr_confidence is None or 0 <= b.ocr_confidence <= 1 for b in ocr)


def _cell(left, top, right, bottom, from_ocr, confidence=None):
    box = BoundingBox(l=left, t=top, r=right, b=bottom, coord_origin=CoordOrigin.TOPLEFT)
    return SimpleNamespace(
        rect=SimpleNamespace(to_bounding_box=lambda: box),
        from_ocr=from_ocr,
        confidence=confidence,
    )


def _item(left, top, right, bottom, origin=CoordOrigin.TOPLEFT):
    bbox = BoundingBox(l=left, t=top, r=right, b=bottom, coord_origin=origin)
    return SimpleNamespace(prov=[SimpleNamespace(bbox=bbox)])


PAGE = SimpleNamespace(size=SimpleNamespace(height=100))


def test_item_over_ocr_cells_is_ocr_with_mean_confidence():
    page = SimpleNamespace(
        size=PAGE.size,
        cells=[_cell(0, 0, 10, 10, True, 0.9), _cell(10, 0, 20, 10, True, 0.7)],
    )
    assert _ocr_status(_item(0, 0, 20, 10), page) == (SegmentKind.OCR, pytest.approx(0.8))


def test_item_over_native_cells_is_text():
    page = SimpleNamespace(size=PAGE.size, cells=[_cell(0, 0, 10, 10, False)])
    assert _ocr_status(_item(0, 0, 10, 10), page) == (SegmentKind.TEXT, None)


def test_majority_decides_when_cells_are_mixed():
    page = SimpleNamespace(
        size=PAGE.size,
        cells=[_cell(0, 0, 10, 10, True, 0.9), _cell(0, 10, 10, 20, False)],
    )
    # One OCR cell and one native cell covering the item: not a majority, so it is text.
    assert _ocr_status(_item(0, 0, 10, 20), page)[0] is SegmentKind.TEXT


def test_bottom_left_coordinates_are_converted_before_comparing():
    page = SimpleNamespace(size=PAGE.size, cells=[_cell(0, 0, 10, 10, True, 0.6)])
    # In bottom-left origin the same box is t=100-0=100 .. b=100-10=90 on a 100-high page.
    bottom_left = _item(0, 100, 10, 90, origin=CoordOrigin.BOTTOMLEFT)
    assert _ocr_status(bottom_left, page) == (SegmentKind.OCR, pytest.approx(0.6))


def test_item_without_page_data_is_text():
    assert _ocr_status(_item(0, 0, 10, 10), None) == (SegmentKind.TEXT, None)
