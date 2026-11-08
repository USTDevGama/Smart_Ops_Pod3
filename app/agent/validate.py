"""Checks on what the model returns (BRD BR-12), and cleaning of text that goes into a prompt.

The model is allowed to judge and to write. Everything it points at is checked against the real
thing: a quote must be inside the trainee's answer, a checklist number must be a real item of the
scenario, the level must be one the service will store as it is. A check that fails raises
`MalformedReply`; the engine then retries once and otherwise gives up. Nothing is "fixed up" by
inventing content, least of all evidence.
"""

import math
import re

from app.agent.errors import MalformedReply

MAX_REPLY_CHARS = 1000

_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
# The prompts mark data with <<<BEGIN:name>>> ... <<<END:name>>>. Untrusted text must not be able
# to write such a marker, so any run of three or more angle brackets is removed from it first.
_FENCE_BRACKETS = re.compile(r"[<＜]{3,}|[>＞]{3,}")
_QUOTE_EDGES = " \t\r\n\"'“”‘’.…"


def neutralize(text: str) -> str:
    """Remove anything that could pose as one of our data markers from untrusted text."""
    return _FENCE_BRACKETS.sub("[removed]", text)


def snap_quote(answer: str, quote: str) -> str | None:
    """The exact words of `answer` that `quote` points at, or None if they are not really there.

    Matching ignores case and differences in spacing, and the model's own surrounding quote marks
    and "...". What is returned is always copied from `answer`, so it is a true substring and a
    later word-for-word check against the stored message passes.
    """
    words = quote.strip(_QUOTE_EDGES).split()
    if len(" ".join(words)) < 2:
        return None
    match = re.search(r"\s+".join(re.escape(w) for w in words), answer, flags=re.IGNORECASE)
    if match is None or match.group(0) not in answer:
        return None
    return match.group(0)


def map_checklist(numbers: list[int], items: list[str], already_met: set[str]) -> list[str]:
    """Turn the item numbers the model returned into the scenario's real checklist texts.

    Numbers are positions (from 1) in the scenario's own list. Numbers outside it are ignored,
    and so are items an earlier answer already met, so the model can neither invent an item nor
    claim one twice.
    """
    met: list[str] = []
    for number in numbers:
        if 1 <= number <= len(items):
            item = items[number - 1]
            if item not in already_met and item not in met:
                met.append(item)
    return met


def unit(value: float) -> float:
    """A score clamped into 0..1. Not a number at all (NaN, infinity) is malformed."""
    value = float(value)
    if not math.isfinite(value):
        raise MalformedReply("bad_number")
    return max(0.0, min(1.0, value))


def check_level(proposed: int, low: int, high: int) -> int:
    """The proposed level must be one the service will keep as it is (see `legal_levels`)."""
    if not low <= proposed <= high:
        raise MalformedReply("level_out_of_range")
    return proposed


def tidy_reply(text: str, persona_name: str) -> str:
    """The client's line, ready to save: no data markers, no 'Name:' label, a sane length."""
    text = neutralize(text).strip()
    label = rf"^(?:client|stakeholder|{re.escape(persona_name)})\s*:\s*"
    text = re.sub(label, "", text, flags=re.IGNORECASE)
    text = " ".join(text.split())
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1].strip()
    if not text:
        raise MalformedReply("empty_reply")
    if text[0] in "{[":  # the model nested JSON inside the reply
        raise MalformedReply("reply_not_text")
    if len(text) > MAX_REPLY_CHARS:
        cut = text[:MAX_REPLY_CHARS]
        ends = [m.end() for m in _SENTENCE_END.finditer(cut)]
        text = cut[: ends[-1]] if ends else cut.rstrip()
    return text
