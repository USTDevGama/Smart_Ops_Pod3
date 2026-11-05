"""What the model is asked to return. These are drafts: the engine checks and converts them.

They are deliberately looser than the shared `TurnOutput` (app/schemas/conversation.py):
- checklist items and proposal chunks are short labels (numbers, "B1") that code maps back to the
  real thing, so the model never has to copy a long id or a long sentence correctly;
- numbers are clamped by code, so a model that says 1.2 does not break the turn.
"""

from pydantic import BaseModel, ConfigDict, Field


class ReplyDraft(BaseModel):
    """The opening line, or a rewritten reply."""

    model_config = ConfigDict(extra="ignore")

    reply: str
    cites: list[str] = Field(default_factory=list)  # brief item labels such as "B1"


class TurnDraft(BaseModel):
    """One call per turn: a judgement of the trainee's answer plus the client's reply."""

    model_config = ConfigDict(extra="ignore")

    answer_quality: float
    checklist_met: list[int] = Field(default_factory=list)  # numbers from the open checklist
    evasive: bool = False
    composure: float = 1.0
    quote: str  # copied word for word from the trainee's answer
    proposed_level: int  # the level the reply was written at; code decides the real one
    reply: str
    cites: list[str] = Field(default_factory=list)
