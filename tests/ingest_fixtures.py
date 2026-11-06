"""Builds small, made-up proposal files in memory for the ingest tests. No real data."""

import io

from docx import Document
from PIL import Image, ImageDraw, ImageFont


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _assemble_pdf(objects: list[bytes]) -> bytes:
    """Number the objects 1.., then add the cross-reference table and trailer."""
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    out += f"startxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


def _table_ops(rows: list[list[str]]) -> list[str]:
    """Drawing operators for a ruled table: grid lines plus one text cell per entry."""
    left, top, col_width, row_height = 72, 480, 120, 24
    columns = max(len(row) for row in rows)
    ops = ["0.5 w"]
    for r in range(len(rows) + 1):
        y = top - r * row_height
        ops.append(f"{left} {y} m {left + columns * col_width} {y} l S")
    for c in range(columns + 1):
        x = left + c * col_width
        ops.append(f"{x} {top} m {x} {top - len(rows) * row_height} l S")
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            ops += [
                "BT",
                "/F1 10 Tf",
                f"{left + c * col_width + 4} {top - r * row_height - 16} Td",
                f"({_pdf_escape(cell)}) Tj",
                "ET",
            ]
    return ops


def make_text_pdf(pages: list[list[str]], table: list[list[str]] | None = None) -> bytes:
    """A multi-page PDF with a text layer and no images.

    An empty string leaves a blank line, which shows up as a paragraph break. `table` (rows of
    cells) is drawn with ruling lines under the text on the first page.
    """
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for index, lines in enumerate(pages):
        body = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
        body += [f"({_pdf_escape(line)}) Tj T*" for line in lines]
        body.append("ET")
        if table and index == 0:
            body += _table_ops(table)
        content = "\n".join(body).encode("ascii")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {5 + 2 * index} 0 R "
            f"/Resources << /Font << /F1 3 0 R >> >> >>".encode()
        )
        objects.append(
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        )
    return _assemble_pdf(objects)


def make_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with a text layer."""
    return make_text_pdf([lines])


def make_scanned_pdf(text: str) -> bytes:
    """A one-page PDF that is only a picture of the text: it has no text layer."""
    image = Image.new("RGB", (1200, 400), "white")
    ImageDraw.Draw(image).text((40, 150), text, fill="black", font=ImageFont.load_default(size=40))
    buffer = io.BytesIO()
    image.save(buffer, "PDF", resolution=150)
    return buffer.getvalue()


def make_pdf_with_scanned_page(text_lines: list[str], scanned_text: str) -> bytes:
    """Two pages: page 1 has a text layer, page 2 is only a picture of text."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(make_pdf(text_lines))
    document.import_pages(pdfium.PdfDocument(make_scanned_pdf(scanned_text)))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_docx(
    headings_and_paragraphs: list[tuple[str, str]], table: list[list[str]] | None = None
) -> bytes:
    """A DOCX with (heading, paragraph) pairs. An empty heading adds only the paragraph.

    With `table` (rows of cells) a table is added after them.
    """
    document = Document()
    for heading, paragraph in headings_and_paragraphs:
        if heading:
            document.add_heading(heading, level=2)
        document.add_paragraph(paragraph)
    if table:
        grid = document.add_table(rows=len(table), cols=max(len(row) for row in table))
        for r, row in enumerate(table):
            for c, cell in enumerate(row):
                grid.cell(r, c).text = cell
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
