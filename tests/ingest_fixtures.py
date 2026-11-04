"""Builds small, made-up proposal files in memory for the ingest tests. No real data."""

import io
import zlib

from docx import Document
from docx.shared import Inches
from PIL import Image, ImageDraw, ImageFont


def make_chart_png() -> bytes:
    """A made-up bar chart of budget by quarter. The numbers are drawn into the picture."""
    image = Image.new("RGB", (800, 500), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=30)
    draw.text((40, 20), "Budget by quarter (USD thousands)", fill="black", font=font)
    for index, (label, value) in enumerate([("Q1", 100), ("Q2", 180), ("Q3", 120)]):
        left = 80 + index * 230
        top = 440 - value * 2
        draw.rectangle([left, top, left + 140, 440], fill=(30, 110, 130))
        draw.text((left + 20, top - 40), str(value), fill="black", font=font)
        draw.text((left + 40, 450), label, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def make_pdf(
    lines: list[str], figure_png: bytes | None = None, caption: str | None = None
) -> bytes:
    """A one-page PDF with a text layer (no OCR needed to read it).

    With `figure_png` a picture is placed under the text, and `caption` is printed below it.
    """

    def escape(line: str) -> str:
        return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    body = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
    body += [f"({escape(line)}) Tj T*" for line in lines]
    body.append("ET")
    if figure_png is not None:
        body.append("q 400 0 0 250 72 250 cm /Im1 Do Q")
    if caption:
        body += ["BT", "/F1 10 Tf", "72 225 Td", f"({escape(caption)}) Tj", "ET"]
    content = "\n".join(body).encode("ascii")

    resources = b"/Font << /F1 5 0 R >>"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << "
        + resources
        + (b" /XObject << /Im1 6 0 R >>" if figure_png else b"")
        + b" >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    if figure_png is not None:
        picture = Image.open(io.BytesIO(figure_png)).convert("RGB")
        pixels = zlib.compress(picture.tobytes())
        objects.append(
            b"<< /Type /XObject /Subtype /Image /Width "
            + str(picture.width).encode()
            + b" /Height "
            + str(picture.height).encode()
            + b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length "
            + str(len(pixels)).encode()
            + b" >>\nstream\n"
            + pixels
            + b"\nendstream"
        )
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


def make_scanned_pdf(text: str) -> bytes:
    """A one-page PDF that is only a picture of the text, so reading it back needs OCR."""
    image = Image.new("RGB", (1200, 400), "white")
    # Large enough for OCR to read; Pillow's default bitmap font is far too small.
    ImageDraw.Draw(image).text((40, 150), text, fill="black", font=ImageFont.load_default(size=40))
    buffer = io.BytesIO()
    image.save(buffer, "PDF", resolution=150)
    return buffer.getvalue()


def make_docx(
    headings_and_paragraphs: list[tuple[str, str]],
    figure_png: bytes | None = None,
    caption: str | None = None,
) -> bytes:
    """A DOCX with (heading, paragraph) pairs. An empty heading adds only the paragraph.

    With `figure_png` a picture is added at the end, followed by `caption` if given.
    """
    document = Document()
    for heading, paragraph in headings_and_paragraphs:
        if heading:
            document.add_heading(heading, level=2)
        document.add_paragraph(paragraph)
    if figure_png is not None:
        document.add_picture(io.BytesIO(figure_png), width=Inches(5))
    if caption:
        document.add_paragraph(caption, style="Caption")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
