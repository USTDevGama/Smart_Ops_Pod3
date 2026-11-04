import pytest

from app.ingest.chunk import RawBlock, to_segments
from app.schemas.enums import SegmentKind


def text(page, body, kind=SegmentKind.TEXT, conf=None):
    return RawBlock(page=page, kind=kind, text=body, ocr_confidence=conf)


def test_empty_input_gives_no_segments():
    assert to_segments([], 100) == []
    assert to_segments([text(1, "   \n  ")], 100) == []


def test_neighbouring_blocks_on_one_page_are_merged_in_order():
    drafts = to_segments([text(1, "First."), text(1, "Second.")], 100)
    assert [(d.seq, d.page, d.text) for d in drafts] == [(0, 1, "First.\n\nSecond.")]


def test_page_and_kind_changes_start_a_new_segment():
    drafts = to_segments(
        [
            text(1, "Page one."),
            text(2, "Page two."),
            text(2, "Scanned line.", kind=SegmentKind.OCR, conf=0.8),
            text(2, "Back to text."),
        ],
        100,
    )
    assert [(d.seq, d.page, d.kind) for d in drafts] == [
        (0, 1, SegmentKind.TEXT),
        (1, 2, SegmentKind.TEXT),
        (2, 2, SegmentKind.OCR),
        (3, 2, SegmentKind.TEXT),
    ]


def test_segments_respect_max_chars():
    body = " ".join(f"word{i}" for i in range(60))
    drafts = to_segments([text(1, body)], 80)
    assert len(drafts) > 1
    assert all(len(d.text) <= 80 for d in drafts)
    assert " ".join(d.text for d in drafts).split() == body.split()


def test_a_word_longer_than_max_is_hard_cut():
    drafts = to_segments([text(1, "x" * 250)], 100)
    assert [len(d.text) for d in drafts] == [100, 100, 50]


def test_whitespace_is_normalised_and_blank_blocks_dropped():
    drafts = to_segments([text(1, "  lots\t\tof   space  "), text(1, "   ")], 100)
    assert [d.text for d in drafts] == ["lots of space"]


def test_ocr_confidence_is_the_mean_of_its_pieces():
    drafts = to_segments(
        [
            text(3, "line a", kind=SegmentKind.OCR, conf=0.9),
            text(3, "line b", kind=SegmentKind.OCR, conf=0.5),
        ],
        100,
    )
    assert len(drafts) == 1
    assert drafts[0].ocr_confidence == pytest.approx(0.7)


def test_native_text_has_no_confidence():
    assert to_segments([text(1, "plain")], 100)[0].ocr_confidence is None
