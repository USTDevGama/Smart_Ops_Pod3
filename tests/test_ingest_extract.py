import io

import pytest
from docx import Document

from app.ingest.errors import ExtractionError
from app.ingest.extract import extract_markdown
from app.schemas.enums import FileType
from tests.ingest_fixtures import make_docx, make_pdf


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return path


# --- TXT -------------------------------------------------------------------------------------


def test_txt_keeps_paragraphs_separated_by_one_blank_line(tmp_path):
    path = write(tmp_path, "plan.txt", b"Budget is 400000.\n\n\n\nTimeline is six months.\n")
    assert extract_markdown(path, FileType.TXT) == "Budget is 400000.\n\nTimeline is six months."


def test_txt_that_is_not_utf8_is_still_read(tmp_path):
    path = write(tmp_path, "plan.txt", "Budget: 400,000 \x80 total".encode("latin-1"))
    assert "400,000" in extract_markdown(path, FileType.TXT)


# --- DOCX ------------------------------------------------------------------------------------


def test_docx_headings_and_paragraphs_are_read_in_order_as_markdown(tmp_path):
    path = write(
        tmp_path,
        "plan.docx",
        make_docx([("Budget", "The total budget is 400000."), ("", "No risks listed.")]),
    )
    assert extract_markdown(path, FileType.DOCX) == (
        "## Budget\n\nThe total budget is 400000.\n\nNo risks listed."
    )


def test_docx_list_items_become_markdown_bullets(tmp_path):
    document = Document()
    document.add_paragraph("Scope:")
    document.add_paragraph("Dashboard for 42 stores", style="List Bullet")
    document.add_paragraph("Training for 20 users", style="List Bullet")
    buffer = io.BytesIO()
    document.save(buffer)

    markdown = extract_markdown(write(tmp_path, "plan.docx", buffer.getvalue()), FileType.DOCX)

    assert markdown == "Scope:\n\n- Dashboard for 42 stores\n\n- Training for 20 users"


def test_docx_table_becomes_markdown_and_keeps_its_place(tmp_path):
    document = Document()
    document.add_paragraph("Before the table.")
    grid = document.add_table(rows=2, cols=2)
    for (r, c), text in {(0, 0): "Option", (0, 1): "Cost", (1, 0): "A", (1, 1): "100"}.items():
        grid.cell(r, c).text = text
    document.add_paragraph("After the table.")
    buffer = io.BytesIO()
    document.save(buffer)

    markdown = extract_markdown(write(tmp_path, "plan.docx", buffer.getvalue()), FileType.DOCX)

    assert markdown == (
        "Before the table.\n\n| Option | Cost |\n|---|---|\n| A | 100 |\n\nAfter the table."
    )


def test_docx_merged_cell_is_not_repeated(tmp_path):
    document = Document()
    grid = document.add_table(rows=2, cols=2)
    grid.cell(0, 0).merge(grid.cell(0, 1)).text = "Plan summary"
    grid.cell(1, 0).text = "A"
    grid.cell(1, 1).text = "100"
    buffer = io.BytesIO()
    document.save(buffer)

    markdown = extract_markdown(write(tmp_path, "plan.docx", buffer.getvalue()), FileType.DOCX)

    assert markdown.count("Plan summary") == 1


def test_docx_without_text_gives_an_empty_string(tmp_path):
    buffer = io.BytesIO()
    Document().save(buffer)
    assert extract_markdown(write(tmp_path, "plan.docx", buffer.getvalue()), FileType.DOCX) == ""


def test_corrupt_docx_raises_a_fixed_safe_message(tmp_path):
    path = write(tmp_path, "broken.docx", b"PK\x03\x04 SECRET PROPOSAL TEXT, not really a docx")
    with pytest.raises(ExtractionError) as info:
        extract_markdown(path, FileType.DOCX)
    assert str(info.value) == "the file could not be read"
    assert "SECRET" not in str(info.value)


# --- PDF goes to the pdfplumber reader (detailed tests in test_ingest_pdf_text.py) -----------


def test_pdf_text_is_read(tmp_path):
    path = write(tmp_path, "plan.pdf", make_pdf(["Budget is 400000 dollars.", "Six months."]))
    assert "400000" in extract_markdown(path, FileType.PDF)
