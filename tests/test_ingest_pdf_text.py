import logging

import pytest

from app.ingest.errors import ExtractionError
from app.ingest.pdf_text import NO_TEXT_LAYER, pdf_markdown
from tests.ingest_fixtures import make_pdf_with_scanned_page, make_scanned_pdf, make_text_pdf


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_paragraphs_and_pages_are_read_in_order(tmp_path):
    path = write(
        tmp_path,
        "plan.pdf",
        make_text_pdf(
            [
                [
                    "Summary",
                    "",
                    "The budget is 400000 dollars.",
                    "It covers six months.",
                    "",
                    "Risks",
                ],
                ["Page two holds the timeline."],
            ]
        ),
    )

    assert pdf_markdown(path) == (
        "<!-- page 1 -->\n\nSummary\n\nThe budget is 400000 dollars. It covers six months.\n\n"
        "Risks\n\n<!-- page 2 -->\n\nPage two holds the timeline."
    )


def test_a_ruled_table_becomes_markdown_in_reading_order(tmp_path):
    path = write(
        tmp_path,
        "plan.pdf",
        make_text_pdf(
            [["Options compared"]], table=[["Option", "Cost"], ["A", "100"], ["B", "200"]]
        ),
    )

    assert pdf_markdown(path) == (
        "<!-- page 1 -->\n\nOptions compared\n\n"
        "| Option | Cost |\n|---|---|\n| A | 100 |\n| B | 200 |"
    )


def test_table_cells_are_not_repeated_as_paragraph_text(tmp_path):
    path = write(
        tmp_path, "plan.pdf", make_text_pdf([["Intro."]], table=[["Option", "Cost"], ["A", "100"]])
    )
    markdown = pdf_markdown(path)
    assert markdown.startswith("<!-- page 1 -->\n\nIntro.")
    assert markdown.count("Option") == 1


def test_a_short_page_is_still_read(tmp_path):
    path = write(tmp_path, "plan.pdf", make_text_pdf([["Appendix A"]]))
    assert pdf_markdown(path) == "<!-- page 1 -->\n\nAppendix A"


def test_page_numbers_stay_true_when_a_page_in_between_is_blank(tmp_path):
    path = write(tmp_path, "plan.pdf", make_text_pdf([["First page."], [], ["Third page."]]))
    assert pdf_markdown(path) == (
        "<!-- page 1 -->\n\nFirst page.\n\n<!-- page 3 -->\n\nThird page."
    )


def test_a_blank_pdf_gives_an_empty_string_and_is_not_called_a_scan(tmp_path):
    assert pdf_markdown(write(tmp_path, "blank.pdf", make_text_pdf([[]]))) == ""


def test_a_scanned_pdf_is_refused_with_a_clear_message(tmp_path):
    path = write(tmp_path, "scan.pdf", make_scanned_pdf("Budget is 400000 dollars"))
    with pytest.raises(ExtractionError) as info:
        pdf_markdown(path)
    assert str(info.value) == NO_TEXT_LAYER
    assert "400000" not in str(info.value)


def test_a_scanned_page_among_text_pages_is_skipped_and_logged(tmp_path, caplog):
    path = write(
        tmp_path,
        "plan.pdf",
        make_pdf_with_scanned_page(["Page one has real text in it."], "Page two is a picture"),
    )

    with caplog.at_level(logging.WARNING):
        markdown = pdf_markdown(path)  # does not raise: the document has text

    assert markdown == "<!-- page 1 -->\n\nPage one has real text in it."
    assert "1 page(s) have no text layer" in caplog.text
    assert "Page two" not in caplog.text  # counts only, never the content


def test_a_blank_page_among_text_pages_is_not_reported_as_a_scan(tmp_path, caplog):
    path = write(tmp_path, "plan.pdf", make_text_pdf([["Page one has real text in it."], []]))
    with caplog.at_level(logging.WARNING):
        markdown = pdf_markdown(path)
    assert markdown == "<!-- page 1 -->\n\nPage one has real text in it."
    assert "no text layer" not in caplog.text


def test_corrupt_pdf_gives_the_fixed_message(tmp_path):
    path = write(tmp_path, "broken.pdf", b"%PDF-1.4\nSECRET PROPOSAL TEXT that is not really a pdf")
    with pytest.raises(ExtractionError) as info:
        pdf_markdown(path)
    assert str(info.value) == "the file could not be read"
    assert "SECRET" not in str(info.value)
