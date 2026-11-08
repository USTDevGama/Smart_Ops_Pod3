"""Made-up contexts for the agent tests.

Everything here is our own invention. The program's seed pack and the architect's sample files are
confidential and this repo may be public, so none of their text is used in tests.
"""

from app.agent.engine import ContextTurn, SessionContext
from app.schemas import Evaluation, PersonaConfig, ScenarioConfig
from app.schemas.enums import TurnRole
from tests.conftest import load_sample

DEMAND = {
    "text": (
        "PROPOSAL: Warehouse picking dashboard (made-up)\n\n"
        "The fixed price is INR 18 lakh against an approved budget of INR 19 lakh, excluding "
        "GST. Go-live is in 10 weeks. The dashboard will significantly reduce picking errors.\n\n"
        "Assumptions: the client IT team gives database access in week 1. Acceptance: the "
        "dashboard loads in a reasonable time. Support ends 30 days after go-live."
    )
}

PROFILE = {
    "text": (
        "PROFILE: Sample Trainee (made-up)\n\n"
        "Backend engineer, three years of Java. Led a billing service rewrite; one service "
        "shipped two weeks late.\n\n"
        "Contact: trainee@example.com, +00 00000 00000, https://example.com/trainee"
    )
}

STRONG = "The supplier now commits to 9 June, and we will cover the cost of the delay ourselves."
VAGUE = "We are looking at options and will update you."


def persona(**extra) -> PersonaConfig:
    return PersonaConfig.model_validate(load_sample("personas/ms_verma_strict.json") | extra)


def scenarios() -> list[ScenarioConfig]:
    raw = load_sample("scenarios/vendor_delay.json")["scenarios"][0]
    vendor = ScenarioConfig.model_validate(raw)
    scope = ScenarioConfig(
        id="SR-01",
        title="Extra feature at no cost",
        situation="The client wants one more feature without paying for it.",
        client_objections=["It is a small change, surely.", "Show me the effort estimate."],
        good_answer_contains=["acknowledges the need", "explains the trade-off", "offers options"],
    )
    return [vendor, scope]


def ev(quality: float = 0.5, met=(), evasive: bool = False, composure: float = 0.9) -> Evaluation:
    return Evaluation(
        answer_quality=quality,
        checklist_met=list(met),
        evasive=evasive,
        composure=composure,
        quote="x",
        proposed_level=1,
    )


def client(text: str, level: int = 1) -> ContextTurn:
    return ContextTurn(role=TurnRole.PERSONA, content=text, escalation_level=level)


def trainee(text: str, evaluation: Evaluation | None = None) -> ContextTurn:
    return ContextTurn(role=TurnRole.TRAINEE, content=text, evaluation=evaluation or ev())


def ctx(
    *, level: int = 1, turns=None, persona_=None, scenario_list=None, **extra
) -> SessionContext:
    """A session at the start (one client message) unless `turns` says otherwise."""
    turns = [client("When were you going to tell me?")] if turns is None else list(turns)
    return SessionContext(
        persona=persona_ or persona(),
        demand=extra.pop("demand", DEMAND),
        profile=extra.pop("profile", PROFILE),
        scenarios=scenario_list or scenarios(),
        turns=turns,
        level=level,
        turns_used=sum(1 for t in turns if t.role == TurnRole.TRAINEE),
        **extra,
    )


def turn_json(**over) -> dict:
    """A valid model answer for `respond`, with any field overridden."""
    base = {
        "scenario_id": "VD-01",
        "addressed": "gave a date",
        "avoided": "who pays",
        "answer_quality": 0.8,
        "evasive": False,
        "composure": 0.9,
        "checklist_met": [2],
        "quote": "commits to 9 June",
        "proposed_level": 1,
        "reply": "Who pays for the delay, exactly?",
    }
    return base | over


def opening_json(**over) -> dict:
    return {"scenario_id": "VD-01", "reply": "When were you going to tell me?"} | over
