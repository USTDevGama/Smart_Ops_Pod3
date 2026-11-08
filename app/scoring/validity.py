"""Rule-based validity of each client message, from what the chat saved.

A client message is valid when all of these hold:
    - it is not empty and it has a recorded escalation level inside the persona's ladder
    - the level moved by at most one step from the previous client message
    - it is not a near-copy of an earlier client message
    - it shares at least one meaningful word with the persona's concerns, the project proposal or
      the trainee's resume (skipped when there is no reference text)

These are shallow text rules, so the confidence formula gives them the smallest weight. They say
nothing about the trainee.
"""

from dataclasses import dataclass

from app.scoring.text import content_words

MAX_STEP_CHANGE = 1
NEAR_COPY = 0.85


@dataclass(frozen=True)
class ClientMessage:
    number: int  # the exchange number, as in `Transcript`
    text: str
    level: int | None  # the escalation level saved with the message


def question_validity(
    messages: list[ClientMessage], max_step: int, reference_text: str
) -> dict[int, bool]:
    reference = content_words(reference_text)
    seen: list[set[str]] = []
    previous_level: int | None = None
    result: dict[int, bool] = {}

    for message in messages:
        words = content_words(message.text)
        valid = bool(message.text.strip())
        valid &= message.level is not None and 1 <= message.level <= max_step
        if valid and previous_level is not None:
            valid = abs(message.level - previous_level) <= MAX_STEP_CHANGE
        valid &= not any(_similarity(words, earlier) >= NEAR_COPY for earlier in seen)
        if reference:
            valid &= bool(words & reference)

        result[message.number] = valid
        seen.append(words)
        if message.level is not None:
            previous_level = message.level
    return result


def _similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
