"""The boundary between the chat service (ours) and the agent (Shubra's).

The service builds a `SessionContext` from the database and asks the engine for one reply. How the
engine produces it (a LangGraph graph, or one prompt plus one LLM call) is the agent owner's
choice and can change without touching the service. The engine only has to return `TurnOutput`
(app/schemas/conversation.py). The service enforces the hard rules around it (turn limit, one
step of escalation at a time). The agent chooses which scenario
to use and how tough to be; nobody configures that per session.
"""

from typing import Protocol

from pydantic import BaseModel, Field

from app.schemas import Evaluation, PersonaConfig, ScenarioConfig, TurnOutput
from app.schemas.enums import TurnRole


class ContextTurn(BaseModel):
    role: TurnRole
    content: str
    escalation_level: int | None = None  # persona turns
    evaluation: Evaluation | None = None  # trainee turns


class SessionContext(BaseModel):
    persona: PersonaConfig
    demand: dict | None = None  # the demand document as the pipeline extracted it (master data)
    profile: dict | None = None  # the trainee's resume as the pipeline extracted it
    scenarios: list[ScenarioConfig] = Field(default_factory=list)  # all of them: the agent picks
    turns: list[ContextTurn] = Field(default_factory=list)  # oldest first
    level: int = 1  # the client's current step
    turns_used: int = 0  # trainee messages so far


class TurnEngine(Protocol):
    def opening(self, ctx: SessionContext) -> TurnOutput:
        """The client's first message. `evaluation` is ignored for it."""
        ...

    def respond(self, ctx: SessionContext, answer: str) -> TurnOutput:
        """The client's reply to the trainee's latest answer, plus a judgement of that answer."""
        ...


def get_engine() -> TurnEngine:
    """The one place to switch to the real engine."""
    from app.agent.placeholder import PlaceholderEngine

    return PlaceholderEngine()
