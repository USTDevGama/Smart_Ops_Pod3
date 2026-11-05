"""Shared builders for the agent tests. Made-up data only (see samples/)."""

from uuid import UUID, uuid4

from app.agent.drafts import TurnDraft
from app.agent.engine import ContextTurn, SessionContext
from app.schemas import Brief, BriefItem, Evaluation, PersonaConfig, ScenarioConfig
from app.schemas.enums import TurnRole
from tests.conftest import load_sample

SEG_BUDGET: UUID = uuid4()
SEG_VENDOR: UUID = uuid4()


def persona(**extra) -> PersonaConfig:
    return PersonaConfig.model_validate(load_sample("personas/ms_verma_strict.json") | extra)


def scenario() -> ScenarioConfig:
    return ScenarioConfig.model_validate(load_sample("scenarios/vendor_delay.json")["scenarios"][0])


def brief() -> Brief:
    return Brief(
        summary="A six-month billing migration.",
        items=[
            BriefItem(
                kind="weak_point",
                text="The budget breakdown is deferred until after approval",
                segment_ids=[SEG_BUDGET],
            ),
            BriefItem(
                kind="risk",
                text="One payment vendor, contract not signed",
                segment_ids=[SEG_VENDOR],
            ),
        ],
    )


def evaluation(quality: float, *, evasive: bool = False, level: int = 1) -> Evaluation:
    return Evaluation(
        answer_quality=quality, evasive=evasive, quote="x", proposed_level=level
    )


def ctx(
    *,
    level: int = 1,
    turns: list[ContextTurn] | None = None,
    with_brief: bool = False,
    open_checklist: list[str] | None = None,
    **persona_extra,
) -> SessionContext:
    scene = scenario()
    turns = turns if turns is not None else [
        ContextTurn(role=TurnRole.PERSONA, content="When were you going to tell me?",
                    escalation_level=level)
    ]
    return SessionContext(
        persona=persona(**persona_extra),
        scenario=scene,
        brief=brief() if with_brief else None,
        turns=turns,
        level=level,
        open_checklist=scene.good_answer_contains if open_checklist is None else open_checklist,
        turns_used=sum(1 for t in turns if t.role == TurnRole.TRAINEE),
    )


def trainee_turn(text: str, quality: float, *, evasive: bool = False) -> ContextTurn:
    return ContextTurn(
        role=TurnRole.TRAINEE, content=text, evaluation=evaluation(quality, evasive=evasive)
    )


def persona_turn(text: str, level: int) -> ContextTurn:
    return ContextTurn(role=TurnRole.PERSONA, content=text, escalation_level=level)


def draft(**over) -> TurnDraft:
    """A model reply to a turn. Defaults: a weak answer, quote taken from the standard answer."""
    values = dict(
        answer_quality=0.2,
        checklist_met=[],
        evasive=False,
        composure=0.9,
        quote="looking at options",
        proposed_level=2,
        reply="Options is not a plan. Give me a date.",
        cites=[],
    )
    return TurnDraft(**(values | over))


WEAK_ANSWER = "We hit a snag and are looking at options. I will update you soon."
STRONG_ANSWER = (
    "I should have escalated on Monday. The supplier now commits to 9 June and we will cover "
    "the extra four days of testing ourselves."
)
