"""Code-only markers for each trainee answer, compared with what the scoring model cited.

Each marker is set from the answer text, the evaluation the agent saved for that answer, and the
trainee's resume and the project proposal. They never change a score. `build_assessment` only
checks whether the model's evidence agrees with them to set the confidence. They are cheap text
rules, so a missed marker lowers confidence; it does not mean the answer was bad.

Markers (one per criterion in `app/scoring/rubric.py`):
    has_specifics   C1  a concrete figure or date, not evasive, answer quality at least 0.5
    kept_composure  C2  composure at least 0.6 and no over-promising words
    grounded        C3  no experience claim with a figure that is in neither document, and either
                        the answer uses words from the documents or it admits a limit
    has_commitment  C4  a first-person commitment or ownership phrase, not evasive
"""

import re
from dataclasses import dataclass

from app.schemas.conversation import Evaluation
from app.scoring.text import content_words

SPECIFIC = "has_specifics"
COMPOSED = "kept_composure"
GROUNDED = "grounded"
COMMITS = "has_commitment"

MIN_QUALITY = 0.5
MIN_COMPOSURE = 0.6
MIN_SHARED_WORDS = 2

_FIGURE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_DATE_WORD = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today|"
    r"jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sep(t(ember)?)?|"
    r"oct(ober)?|nov(ember)?|dec(ember)?)\b",
    re.IGNORECASE,
)
_OVER_PROMISE = re.compile(
    r"\b(guarantee[sd]?|100\s?%|definitely|absolutely|zero risk|no risk|without fail|"
    r"i promise|never fail)",
    re.IGNORECASE,
)
_COMMITMENT = re.compile(
    r"\b(i will|i'll|we will|we'll|i am going to|i commit|i can commit|i take responsibility|"
    r"my responsibility|i own this|from now on|i should have)\b",
    re.IGNORECASE,
)
_ADMITS_LIMIT = re.compile(
    r"\b(i don't know|i do not know|not sure|not certain|can't confirm|cannot confirm|"
    r"i'll confirm|i will confirm|i haven't|i have not|limited experience|don't have)\b",
    re.IGNORECASE,
)
_EXPERIENCE_CUE = re.compile(
    r"\b(i have|i've|i led|i built|i delivered|i managed|i worked|years?|previously|my last|"
    r"in my)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class AnswerInput:
    """One trainee answer with the client message it replied to."""

    number: int  # the exchange number, as in `Transcript`
    client_text: str
    text: str
    evaluation: Evaluation | None


def answer_signals(answer: AnswerInput, reference_text: str) -> set[str]:
    signals: set[str] = set()
    evaluation = answer.evaluation
    text = answer.text

    concrete = bool(_FIGURE.search(text) or _DATE_WORD.search(text))
    if concrete and (
        evaluation is None
        or (not evaluation.evasive and evaluation.answer_quality >= MIN_QUALITY)
    ):
        signals.add(SPECIFIC)

    if (
        evaluation is not None
        and evaluation.composure >= MIN_COMPOSURE
        and not _OVER_PROMISE.search(text)
    ):
        signals.add(COMPOSED)

    if reference_text and _grounded(answer, reference_text):
        signals.add(GROUNDED)

    if _COMMITMENT.search(text) and (evaluation is None or not evaluation.evasive):
        signals.add(COMMITS)

    return signals


def trainee_signals(answers: list[AnswerInput], reference_text: str) -> dict[int, set[str]]:
    return {answer.number: answer_signals(answer, reference_text) for answer in answers}


def _grounded(answer: AnswerInput, reference_text: str) -> bool:
    known = _figures(reference_text) | _figures(answer.client_text)
    for sentence in _SENTENCE_END.split(answer.text):
        if _EXPERIENCE_CUE.search(sentence) and _figures(sentence) - known:
            return False  # an experience claim with a figure nobody gave us

    shared = content_words(answer.text) & content_words(reference_text)
    return len(shared) >= MIN_SHARED_WORDS or bool(_ADMITS_LIMIT.search(answer.text))


def _figures(text: str) -> set[str]:
    return {match.group().replace(",", "").rstrip(".") for match in _FIGURE.finditer(text)}
