"""Builds the DOCX and PDF versions of the made-up demand and profile samples from their TXT files.

Run: uv run python -m scripts.make_samples
The outputs are made-up text, committed so tests and demos need no tooling.
"""

import io
import re
from pathlib import Path

from docx import Document

from tests.ingest_fixtures import make_text_pdf

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
SOURCES = [SAMPLES / "demand" / "project_demand.txt", SAMPLES / "profiles" / "sample_resume.txt"]

_NUMBERED_HEADING = re.compile(r"\d+\. \S")


def _blocks(text: str) -> list[list[str]]:
    """The text as blocks of lines, split on blank lines."""
    return [block.splitlines() for block in re.split(r"\n\s*\n", text.strip())]


def _heading_and_body(index: int, lines: list[str]) -> tuple[str | None, list[str]]:
    """The first block's first line is the title; a numbered first line is a section heading."""
    if index == 0 or _NUMBERED_HEADING.match(lines[0]):
        return lines[0], lines[1:]
    return None, lines


def build_docx(blocks: list[list[str]]) -> bytes:
    document = Document()
    for index, lines in enumerate(blocks):
        heading, body = _heading_and_body(index, lines)
        if heading:
            document.add_heading(heading, level=0 if index == 0 else 1)
        if body:
            document.add_paragraph(" ".join(body))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def build_pdf(blocks: list[list[str]]) -> bytes:
    """One page. A blank line after each heading and each block gives the paragraph breaks."""
    lines: list[str] = []
    for index, block in enumerate(blocks):
        heading, body = _heading_and_body(index, block)
        if heading:
            lines += [heading, ""]
        lines += [*body, ""]
    return make_text_pdf([lines])


def main() -> None:
    for source in SOURCES:
        blocks = _blocks(source.read_text(encoding="utf-8"))
        source.with_suffix(".docx").write_bytes(build_docx(blocks))
        source.with_suffix(".pdf").write_bytes(build_pdf(blocks))
        print(f"wrote {source.with_suffix('.docx').name} and {source.with_suffix('.pdf').name}")


if __name__ == "__main__":
    main()
