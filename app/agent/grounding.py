"""Checks on what the model returns, so nothing ungrounded gets saved (BRD BR-12).

The model is allowed to judge and to write. Everything it points at is checked against the real
thing: a quote must be inside the trainee's answer, a checklist number must be a real checklist
item, a citation must be a real proposal chunk. Anything else is dropped or the call is repaired.
Also here: neutralising our own wrapper tags in untrusted text.
"""

import re
from uuid import UUID

# Tags the prompts use to mark untrusted text as data. Untrusted text must not be able to close
# one of them and start writing "instructions".
WRAPPER_TAGS = ("trainee_answer", "transcript", "proposal_brief")
_TAG = re.compile(r"<\s*/?\s*(?:" + "|".join(WRAPPER_TAGS) + r")\b[^>]*>", re.IGNORECASE)
_QUOTE_EDGES = " \t\r\n\"'“”‘’.…"


def neutralize(text: str) -> str:
    """Remove our wrapper tags from untrusted text before it goes into a prompt."""
    return _TAG.sub("[removed]", text)


def snap_quote(answer: str, quote: str) -> str | None:
    """The exact words of `answer` that `quote` points at, or None if it is not really there.

    Matching ignores case and differences in spacing, and the model's own surrounding quote marks
    and "...". What is returned is always copied from `answer`, so a later check that looks for
    the quote word for word in the stored message will find it.
    """
    words = quote.strip(_QUOTE_EDGES).split()
    if len(" ".join(words)) < 2:
        return None
    match = re.search(r"\s+".join(re.escape(w) for w in words), answer, flags=re.IGNORECASE)
    return match.group(0) if match else None


def map_checklist(numbers: list[int], open_items: list[str]) -> list[str]:
    """Turn the item numbers the model returned into the real checklist texts.

    Numbers outside the list are ignored, so the model cannot invent an item or claim one that
    was already met.
    """
    met: list[str] = []
    for number in numbers:
        if 1 <= number <= len(open_items) and open_items[number - 1] not in met:
            met.append(open_items[number - 1])
    return met


def map_cites(labels: list[str], table: dict[str, list[UUID]]) -> list[UUID]:
    """Turn brief item labels ("B1") into the proposal chunk ids behind them. Unknown ones drop."""
    refs: list[UUID] = []
    for label in labels:
        for segment_id in table.get(str(label).strip().upper(), []):
            if segment_id not in refs:
                refs.append(segment_id)
    return refs
