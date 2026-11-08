"""A chat as numbered exchanges: the unit that scoring cites.

One exchange is a client question and the trainee's reply to it. Both carry the same number,
counted from 1. This is the numbering of `ScoringOutput` evidence, of the report (`app/reports`)
and of `ScoringValidationContext`. The last client message may have no reply yet.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from app.schemas.enums import TurnRole


class ScoringInputError(ValueError):
    """The chat cannot be scored (malformed order, or no trainee answer to score)."""


class Message(Protocol):
    """Anything shaped like a stored chat message (a `turn` row, a `ContextTurn`)."""

    role: TurnRole
    content: str


@dataclass(frozen=True)
class Exchange:
    number: int
    client: str
    trainee: str | None


@dataclass(frozen=True)
class Transcript:
    exchanges: tuple[Exchange, ...]

    @property
    def client_numbers(self) -> set[int]:
        return {exchange.number for exchange in self.exchanges}

    @property
    def trainee_numbers(self) -> set[int]:
        return {exchange.number for exchange in self.exchanges if exchange.trainee is not None}


def build_transcript(messages: Iterable[Message]) -> Transcript:
    """Group messages (oldest first) into exchanges: a client message opens one, a reply ends it."""
    exchanges: list[Exchange] = []
    for message in messages:
        if message.role == TurnRole.PERSONA:
            exchanges.append(Exchange(len(exchanges) + 1, message.content, None))
        elif not exchanges:
            raise ScoringInputError("the chat must start with a client message")
        elif exchanges[-1].trainee is not None:
            raise ScoringInputError("two trainee replies follow one client message")
        else:
            last = exchanges[-1]
            exchanges[-1] = Exchange(last.number, last.client, message.content)
    return Transcript(tuple(exchanges))
