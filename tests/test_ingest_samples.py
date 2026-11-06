"""Every committed sample file is read, in every format it comes in. An explicit list, so a
teammate's untracked local files never matter."""

import pytest

from app.ingest.extract import extract_markdown
from app.schemas.enums import FileType
from tests.conftest import SAMPLES

# (file, a phrase that must come out of it)
SAMPLE_FILES = (
    [
        (f"demand/project_demand.{ext}", "invoicing release is due in ten days")
        for ext in ("txt", "docx", "pdf")
    ]
    + [
        (f"profiles/sample_resume.{ext}", "billing service rewrite")
        for ext in ("txt", "docx", "pdf")
    ]
    + [
        ("Sample_Proposal_Store_Inventory_Dashboard.docx", "Store Inventory Visibility Dashboard"),
    ]
)


@pytest.mark.parametrize(("relative", "phrase"), SAMPLE_FILES)
def test_every_sample_is_read(relative, phrase):
    path = SAMPLES / relative
    text = extract_markdown(path.read_bytes(), FileType(path.suffix[1:]))
    assert phrase in " ".join(text.split())


def test_the_store_inventory_sample_keeps_its_tables_and_numbers():
    path = SAMPLES / "Sample_Proposal_Store_Inventory_Dashboard.docx"
    text = extract_markdown(path.read_bytes(), FileType.DOCX)
    assert "# 1. Executive summary" in text
    assert "| Total (excluding GST) |" in text and "24.20" in text
