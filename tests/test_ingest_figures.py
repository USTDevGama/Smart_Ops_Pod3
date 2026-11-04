from types import SimpleNamespace

import pytest

from app.ingest.chunk import RawBlock, to_segments
from app.ingest.extract import extract_blocks
from app.ingest.figures import figure_description, figure_label, figure_text, looks_like_caption
from app.schemas.enums import FileType, SegmentKind
from tests.ingest_fixtures import make_chart_png, make_docx, make_pdf

# OCR off: the figure paths are what is under test, not scanned pages.
OPTIONS = {"ocr_enabled": False, "ocr_lang": "eng"}
CAPTION = "Figure 1: Budget by quarter"


def prediction(name, confidence):
    return SimpleNamespace(class_name=name, confidence=confidence)


def picture(predictions=None, description=None):
    classification = SimpleNamespace(predictions=predictions) if predictions is not None else None
    described = SimpleNamespace(text=description) if description is not None else None
    return SimpleNamespace(
        meta=SimpleNamespace(classification=classification, description=described)
    )


# --- pure formatting -------------------------------------------------------------------------


def test_figure_text_has_caption_and_marked_ocr_text():
    text = figure_text("bar chart", CAPTION, ["Q1", "100"], None)
    assert text.splitlines() == [
        "[Figure, bar chart]",
        f"Caption: {CAPTION}",
        "Text read inside the figure (by OCR, may be incomplete): Q1 | 100",
    ]


def test_description_is_always_marked_unverified():
    text = figure_text(None, "", [], "A chart of sales.")
    assert "Machine-generated description (unverified, may be wrong): A chart of sales." in text


def test_label_only_figure_says_nothing_could_be_read():
    assert figure_text("flow chart", "", [], None) == (
        "[Figure, flow chart]\nNo text could be read from this figure."
    )


def test_nothing_known_gives_no_text():
    assert figure_text(None, "", [], None) is None


def test_label_needs_confidence():
    assert figure_label(picture([prediction("bar_chart", 0.9), prediction("table", 0.1)])) == (
        "bar chart"
    )
    assert figure_label(picture([prediction("bar_chart", 0.3)])) is None
    assert figure_label(picture(predictions=None)) is None
    assert figure_label(SimpleNamespace(meta=None)) is None


def test_description_is_read_from_meta():
    assert figure_description(picture(description=" Some text. ")) == "Some text."
    assert figure_description(picture()) is None
    assert figure_description(SimpleNamespace(meta=None)) is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Figure 1: Budget", True),
        ("  fig. 2 - Timeline", True),
        ("FIGURE 12", True),
        ("The figure below shows", False),
        ("Figures are shown later", False),
    ],
)
def test_caption_detection(text, expected):
    assert looks_like_caption(text) is expected


def test_figures_are_never_merged_into_one_segment():
    figure = lambda text: RawBlock(1, SegmentKind.FIGURE, text)  # noqa: E731
    drafts = to_segments([figure("[Figure] one"), figure("[Figure] two")], 1000)
    assert [d.text for d in drafts] == ["[Figure] one", "[Figure] two"]
    assert [d.kind for d in drafts] == [SegmentKind.FIGURE, SegmentKind.FIGURE]


def test_text_next_to_a_figure_stays_separate():
    drafts = to_segments(
        [
            RawBlock(1, SegmentKind.TEXT, "Before."),
            RawBlock(1, SegmentKind.FIGURE, "[Figure] x"),
            RawBlock(1, SegmentKind.TEXT, "After."),
        ],
        1000,
    )
    assert [d.kind for d in drafts] == [SegmentKind.TEXT, SegmentKind.FIGURE, SegmentKind.TEXT]


# --- real Docling on files with a figure -----------------------------------------------------


@pytest.fixture(scope="module")
def pdf_with_figure(tmp_path_factory):
    path = tmp_path_factory.mktemp("figs") / "plan.pdf"
    path.write_bytes(make_pdf(["Our budget is shown below."], make_chart_png(), CAPTION))
    return path


@pytest.fixture(scope="module")
def docx_with_figure(tmp_path_factory):
    path = tmp_path_factory.mktemp("figs") / "plan.docx"
    path.write_bytes(
        make_docx([("Budget", "Our budget is shown below.")], make_chart_png(), CAPTION)
    )
    return path


def figure_blocks(blocks):
    return [b for b in blocks if b.kind is SegmentKind.FIGURE]


def test_pdf_figure_becomes_one_block_with_caption_and_type(pdf_with_figure):
    blocks = extract_blocks(pdf_with_figure, FileType.PDF, **OPTIONS)

    (figure,) = figure_blocks(blocks)
    assert figure.page == 1
    assert figure.text.startswith("[Figure, bar chart]")
    assert f"Caption: {CAPTION}" in figure.text
    # The caption is part of the figure, not repeated as its own paragraph.
    assert [b.text for b in blocks if b.kind is SegmentKind.TEXT] == ["Our budget is shown below."]


def test_text_inside_a_pdf_figure_is_read_when_ocr_is_on(pdf_with_figure):
    blocks = extract_blocks(
        pdf_with_figure, FileType.PDF, ocr_enabled=True, ocr_lang="eng", ocr_engine="rapidocr"
    )

    (figure,) = figure_blocks(blocks)
    assert "Text read inside the figure (by OCR, may be incomplete):" in figure.text
    assert "Q1" in figure.text
    assert figure.ocr_confidence is not None and 0 < figure.ocr_confidence <= 1


def test_pdf_figure_has_no_model_description_by_default(pdf_with_figure):
    (figure,) = figure_blocks(extract_blocks(pdf_with_figure, FileType.PDF, **OPTIONS))
    assert "Machine-generated" not in figure.text


def test_docx_caption_in_the_next_paragraph_is_attached_to_the_figure(docx_with_figure):
    blocks = extract_blocks(docx_with_figure, FileType.DOCX, **OPTIONS)

    (figure,) = figure_blocks(blocks)
    assert figure.text.startswith("[Figure, bar chart]")
    assert f"Caption: {CAPTION}" in figure.text
    assert CAPTION not in " ".join(b.text for b in blocks if b.kind is SegmentKind.TEXT)


def test_figures_off_leaves_no_figure_blocks_and_keeps_the_caption_as_text(pdf_with_figure):
    blocks = extract_blocks(pdf_with_figure, FileType.PDF, figures=False, **OPTIONS)
    assert figure_blocks(blocks) == []
    assert CAPTION in " ".join(b.text for b in blocks)
