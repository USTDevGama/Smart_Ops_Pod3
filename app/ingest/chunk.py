"""Turns extracted blocks into citable segments. Pure code: no parser, no database, no LLM."""

import re
from dataclasses import dataclass

from app.schemas.enums import SegmentKind

_SPACES = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class RawBlock:
    """One paragraph, heading, list item or table as the extractor read it."""

    page: int
    kind: SegmentKind
    text: str
    ocr_confidence: float | None = None


@dataclass(frozen=True)
class SegmentDraft:
    """A segment before it is stored as a `proposal_segment` row."""

    seq: int
    page: int
    kind: SegmentKind
    text: str
    ocr_confidence: float | None


def to_segments(blocks: list[RawBlock], max_chars: int) -> list[SegmentDraft]:
    """Merge neighbouring blocks from the same page and kind, up to `max_chars` each.

    A segment never spans two pages or two kinds, so its `page` and `kind` are exact, and a
    figure is never merged with another block. A block
    longer than `max_chars` is split at a space. Empty blocks are dropped. `seq` follows the
    reading order from 0.
    """
    pieces = [piece for block in blocks for piece in _pieces(block, max_chars)]

    groups: list[list[RawBlock]] = []
    for piece in pieces:
        if groups and _can_join(groups[-1], piece, max_chars):
            groups[-1].append(piece)
        else:
            groups.append([piece])

    return [_draft(seq, group) for seq, group in enumerate(groups)]


def _pieces(block: RawBlock, max_chars: int) -> list[RawBlock]:
    text = _BLANK_LINES.sub("\n\n", _SPACES.sub(" ", block.text)).strip()
    if not text:
        return []
    return [
        RawBlock(block.page, block.kind, part, block.ocr_confidence)
        for part in _split_long(text, max_chars)
    ]


def _split_long(text: str, max_chars: int) -> list[str]:
    parts: list[str] = []
    rest = text
    while len(rest) > max_chars:
        cut = rest.rfind(" ", 1, max_chars)
        if cut <= 0:
            cut = max_chars  # no space to break on: hard cut
        parts.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        parts.append(rest)
    return parts


def _can_join(group: list[RawBlock], piece: RawBlock, max_chars: int) -> bool:
    head = group[0]
    if head.page != piece.page or head.kind != piece.kind:
        return False
    if piece.kind is SegmentKind.FIGURE:
        return False  # one figure per segment, so "Figure 2" can be cited on its own
    joined_length = sum(len(p.text) for p in group) + 2 * len(group)  # "\n\n" between parts
    return joined_length + len(piece.text) <= max_chars


def _draft(seq: int, group: list[RawBlock]) -> SegmentDraft:
    confidences = [p.ocr_confidence for p in group if p.ocr_confidence is not None]
    return SegmentDraft(
        seq=seq,
        page=group[0].page,
        kind=group[0].kind,
        text="\n\n".join(p.text for p in group),
        ocr_confidence=sum(confidences) / len(confidences) if confidences else None,
    )
