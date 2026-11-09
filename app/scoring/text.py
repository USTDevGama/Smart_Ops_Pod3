"""Plain-text helpers shared by the signal and validity checks."""

import re

_WORD = re.compile(r"[a-z][a-z'-]{4,}")


def flatten_text(value: object) -> str:
    """All strings inside extracted JSON (a resume or the demand document), one per line."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(part for item in value.values() if (part := flatten_text(item)))
    if isinstance(value, (list, tuple)):
        return "\n".join(part for item in value if (part := flatten_text(item)))
    return str(value)


def content_words(text: str) -> set[str]:
    """Lowercase words of five or more letters: long enough to carry meaning, short to compare."""
    return set(_WORD.findall(text.lower()))
