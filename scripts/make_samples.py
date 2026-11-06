"""Builds the proposal sample files from samples/proposals/billing_migration.txt.

Run: uv run python -m scripts.make_samples
The outputs are made-up text, committed so tests and demos need no tooling.
"""

from pathlib import Path

from tests.ingest_fixtures import make_docx, make_text_pdf

PROPOSALS = Path(__file__).resolve().parent.parent / "samples" / "proposals"


def main() -> None:
    source = (PROPOSALS / "billing_migration.txt").read_text(encoding="utf-8")
    paragraphs = [p.strip() for p in source.split("\n\n") if p.strip()]

    (PROPOSALS / "billing_migration.docx").write_bytes(
        make_docx([("", paragraph) for paragraph in paragraphs])
    )
    # Blank lines are kept, so the PDF has the same paragraph breaks as the text file.
    (PROPOSALS / "billing_migration.pdf").write_bytes(make_text_pdf([source.splitlines()[:45]]))
    print(f"wrote samples to {PROPOSALS}")


if __name__ == "__main__":
    main()
