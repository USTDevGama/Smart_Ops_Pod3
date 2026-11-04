"""Builds the proposal sample files from samples/proposals/billing_migration.txt.

Run: uv run python -m scripts.make_samples
The outputs are made-up text, committed so tests and demos need no tooling.
"""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from tests.ingest_fixtures import make_chart_png, make_docx, make_pdf

PROPOSALS = Path(__file__).resolve().parent.parent / "samples" / "proposals"


def main() -> None:
    source = (PROPOSALS / "billing_migration.txt").read_text(encoding="utf-8")
    paragraphs = [p.strip() for p in source.split("\n\n") if p.strip()]

    (PROPOSALS / "billing_migration.docx").write_bytes(
        make_docx([("", paragraph) for paragraph in paragraphs])
    )
    lines = [line for line in source.splitlines() if line.strip()]
    (PROPOSALS / "billing_migration.pdf").write_bytes(make_pdf(lines[:40]))

    # The same proposal with a budget chart and its caption, to exercise figure handling.
    chart = make_chart_png()
    caption = "Figure 1: Budget by quarter"
    (PROPOSALS / "billing_migration_with_figure.docx").write_bytes(
        make_docx([("", paragraph) for paragraph in paragraphs[:3]], chart, caption)
    )
    (PROPOSALS / "billing_migration_with_figure.pdf").write_bytes(
        make_pdf(lines[:6], chart, caption)
    )

    # A scanned page: the text exists only as pixels, so it needs OCR to read back.
    page = Image.new("RGB", (1275, 1650), "white")  # US Letter at 150 dpi
    draw = ImageDraw.Draw(page)
    font = ImageFont.load_default(size=28)
    y = 120
    for line in lines[:24]:
        draw.text((120, y), line[:90], fill="black", font=font)
        y += 48
    buffer = io.BytesIO()
    page.save(buffer, "PDF", resolution=150)
    (PROPOSALS / "billing_migration_scanned.pdf").write_bytes(buffer.getvalue())
    print(f"wrote samples to {PROPOSALS}")


if __name__ == "__main__":
    main()
