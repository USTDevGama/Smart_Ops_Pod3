import io

import pytest
from docx import Document

from app.ingest.errors import ExtractionError
from app.ingest.extract import extract_markdown
from app.schemas.enums import FileType
from tests.ingest_fixtures import make_docx, make_pdf


def docx_bytes(document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# --- TXT -------------------------------------------------------------------------------------


def test_txt_keeps_paragraphs_separated_by_one_blank_line():
    data = b"Budget is 400000.\n\n\n\nTimeline is six months.\n"
    assert extract_markdown(data, FileType.TXT) == "Budget is 400000.\n\nTimeline is six months."


def test_txt_that_is_not_utf8_is_still_read():
    data = "Budget: 400,000 \x80 total".encode("latin-1")
    assert "400,000" in extract_markdown(data, FileType.TXT)


def test_blank_txt_gives_an_empty_string():
    assert extract_markdown(b"  \n\n  ", FileType.TXT) == ""


# --- DOCX ------------------------------------------------------------------------------------


def test_docx_headings_and_paragraphs_are_read_in_order_as_markdown():
    data = make_docx([("Budget", "The total budget is 400000."), ("", "No risks listed.")])
    assert extract_markdown(data, FileType.DOCX) == (
        "## Budget\n\nThe total budget is 400000.\n\nNo risks listed."
    )


def test_docx_list_items_become_markdown_bullets():
    document = Document()
    document.add_paragraph("Scope:")
    document.add_paragraph("Dashboard for 42 stores", style="List Bullet")
    document.add_paragraph("Training for 20 users", style="List Bullet")

    markdown = extract_markdown(docx_bytes(document), FileType.DOCX)

    assert markdown == "Scope:\n\n- Dashboard for 42 stores\n\n- Training for 20 users"


def test_docx_table_becomes_markdown_and_keeps_its_place():
    document = Document()
    document.add_paragraph("Before the table.")
    grid = document.add_table(rows=2, cols=2)
    for (r, c), text in {(0, 0): "Option", (0, 1): "Cost", (1, 0): "A", (1, 1): "100"}.items():
        grid.cell(r, c).text = text
    document.add_paragraph("After the table.")

    markdown = extract_markdown(docx_bytes(document), FileType.DOCX)

    assert markdown == (
        "Before the table.\n\n| Option | Cost |\n|---|---|\n| A | 100 |\n\nAfter the table."
    )


def test_docx_merged_cell_is_not_repeated():
    document = Document()
    grid = document.add_table(rows=2, cols=2)
    grid.cell(0, 0).merge(grid.cell(0, 1)).text = "Plan summary"
    grid.cell(1, 0).text = "A"
    grid.cell(1, 1).text = "100"

    markdown = extract_markdown(docx_bytes(document), FileType.DOCX)

    assert markdown.count("Plan summary") == 1


def test_docx_without_text_gives_an_empty_string():
    assert extract_markdown(docx_bytes(Document()), FileType.DOCX) == ""


def test_corrupt_docx_raises_a_fixed_safe_message():
    data = b"PK\x03\x04 SECRET PROPOSAL TEXT, not really a docx"
    with pytest.raises(ExtractionError) as info:
        extract_markdown(data, FileType.DOCX)
    assert str(info.value) == "the file could not be read"
    assert "SECRET" not in str(info.value)


# --- PDF goes to the pdfplumber reader (detailed tests in test_ingest_pdf_text.py) -----------


def test_pdf_text_is_read():
    data = make_pdf(["Budget is 400000 dollars.", "Six months."])
    assert "400000" in extract_markdown(data, FileType.PDF)
