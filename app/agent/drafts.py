"""What the model is asked to return. These are drafts: the engine checks and converts them.

They are looser than the shared `TurnOutput` (app/schemas/conversation.py) on purpose:
- checklist items are numbers that code maps back to the real text, so the model never has to
  copy a long sentence exactly;
- numbers are clamped by code, so a model that says 1.2 does not break the turn;
- `addressed` and `avoided` are a thinking aid: writing down what the answer did and did not
  answer, before scoring it, keeps the judgement and the next question tied to what was said.
  They are not saved and not shown to anyone.

Field order matters: models write JSON in the order of the schema, so the reasoning comes first
and the reply last.
"""

from pydantic import BaseModel, ConfigDict, Field


class OpeningDraft(BaseModel):
    """The first client message, and the scenario it was built on."""

    model_config = ConfigDict(extra="ignore")

    scenario_id: str
    reply: str


class TurnDraft(BaseModel):
    """One call per turn: a judgement of the trainee's answer plus the client's reply."""

    model_config = ConfigDict(extra="ignore")

    scenario_id: str = ""  # the scenario this conversation is in (checked against the dataset)
    addressed: str = ""  # one line: what the answer actually answered (thinking aid, not saved)
    avoided: str = ""  # one line: what it dodged or left open (thinking aid, not saved)
    answer_quality: float
    evasive: bool = False
    composure: float = 1.0
    checklist_met: list[int] = Field(default_factory=list)  # positions in the scenario's list
    quote: str  # copied word for word from the trainee's answer
    proposed_level: int  # the level the reply is written at; the service clamps it
    reply: str
