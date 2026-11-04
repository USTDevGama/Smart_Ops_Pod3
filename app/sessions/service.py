"""Chat logic: start a session, take a turn, end a session. No web code in here."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.engine import ContextTurn, SessionContext, TurnEngine
from app.api.admin_config import latest_published
from app.api.deps import CurrentUser, can_see
from app.db import models as m
from app.schemas import Brief, Evaluation, PersonaConfig, ScenarioConfig, TurnOutput
from app.schemas.enums import (
    ConfigKind,
    EndReason,
    ProposalStatus,
    Role,
    SessionStatus,
    TurnRole,
)
from app.sessions.hooks import on_session_ended
from app.sessions.limits import allowed_turns, clamp_level


class Loaded:
    """A session with its settings and turns, read once per request."""

    def __init__(self, db: Session, session: m.RoleplaySession):
        self.session = session
        self.persona_version = db.get(m.ConfigVersion, session.persona_version_id)
        self.scenario_version = db.get(m.ConfigVersion, session.scenario_version_id)
        self.persona = PersonaConfig.model_validate(self.persona_version.config)
        self.scenario = ScenarioConfig.model_validate(self.scenario_version.config)
        self.turns = list(
            db.scalars(select(m.Turn).where(m.Turn.session_id == session.id).order_by(m.Turn.idx))
        )
        self.brief: Brief | None = None
        self.segment_ids: set[str] = set()
        if session.proposal_id:
            proposal = db.get(m.Proposal, session.proposal_id)
            if proposal and proposal.brief:
                self.brief = Brief.model_validate(proposal.brief)
            self.segment_ids = {
                str(i)
                for i in db.scalars(
                    select(m.ProposalSegment.id).where(
                        m.ProposalSegment.proposal_id == session.proposal_id
                    )
                )
            }

    @property
    def trainee_turns(self) -> list[m.Turn]:
        return [t for t in self.turns if t.role == TurnRole.TRAINEE]

    @property
    def level(self) -> int:
        levels = [t.escalation_level for t in self.turns if t.escalation_level]
        return levels[-1] if levels else 1

    @property
    def open_checklist(self) -> list[str]:
        met: set[str] = set()
        for turn in self.trainee_turns:
            if turn.evaluation:
                met.update(turn.evaluation.get("checklist_met", []))
        return [i for i in self.scenario.good_answer_contains if i not in met]

    def context(self) -> SessionContext:
        return SessionContext(
            persona=self.persona,
            scenario=self.scenario,
            brief=self.brief,
            turns=[
                ContextTurn(
                    role=t.role,
                    content=t.content,
                    escalation_level=t.escalation_level,
                    evaluation=Evaluation.model_validate(t.evaluation) if t.evaluation else None,
                )
                for t in self.turns
            ],
            level=self.level,
            open_checklist=self.open_checklist,
            turns_used=len(self.trainee_turns),
        )


def get_visible(db: Session, session_id: UUID, user: CurrentUser) -> m.RoleplaySession:
    row = db.get(m.RoleplaySession, session_id)
    if row is None or not can_see(user, row.trainee_ref):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return row


def _ask_engine(call: Callable[..., TurnOutput], *args) -> TurnOutput:
    try:
        return call(*args)
    except Exception:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "the client could not reply") from None


def _real_refs(refs, valid: set[str]) -> list[str]:
    """Keep only citations that point at real chunks of this session's proposal."""
    return [str(r) for r in refs if str(r) in valid]


def start_session(
    db: Session,
    engine: TurnEngine,
    user: CurrentUser,
    persona_key: str,
    scenario_key: str,
    proposal_id: UUID | None,
) -> Loaded:
    persona = latest_published(db, ConfigKind.PERSONA, persona_key)
    scenario = latest_published(db, ConfigKind.SCENARIO, scenario_key)
    if persona is None or scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no published persona or scenario")
    if proposal_id is not None:
        proposal = db.get(m.Proposal, proposal_id)
        if proposal is None or not can_see(user, proposal.owner_ref):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "proposal not found")
        if proposal.status != ProposalStatus.READY:
            raise HTTPException(status.HTTP_409_CONFLICT, "the proposal is not ready yet")

    session = m.RoleplaySession(
        trainee_ref=user.user_ref,
        proposal_id=proposal_id,
        persona_version_id=persona.id,
        scenario_version_id=scenario.id,
        status=SessionStatus.ACTIVE,
    )
    db.add(session)
    db.flush()
    loaded = Loaded(db, session)
    out = _ask_engine(engine.opening, loaded.context())  # on error the session is not saved
    db.add(
        m.Turn(
            session_id=session.id,
            idx=0,
            role=TurnRole.PERSONA,
            content=out.reply,
            escalation_level=1,
            refs=_real_refs(out.refs, loaded.segment_ids),
        )
    )
    db.commit()
    return Loaded(db, session)


class TurnResult:
    def __init__(self, trainee: m.Turn, persona: m.Turn, loaded: Loaded, replayed: bool):
        self.trainee, self.persona, self.replayed = trainee, persona, replayed
        self.session = loaded.session
        self.turns_used = len(loaded.trainee_turns)


def take_turn(
    db: Session, engine: TurnEngine, session: m.RoleplaySession, content: str, key: str
) -> TurnResult:
    loaded = Loaded(db, session)

    for turn in loaded.trainee_turns:  # the same message sent again: give back the stored reply
        if turn.idempotency_key == key:
            reply = next(t for t in loaded.turns if t.idx == turn.idx + 1)
            return TurnResult(turn, reply, loaded, replayed=True)

    if session.status != SessionStatus.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "the session has ended")

    out = _ask_engine(engine.respond, loaded.context(), content)  # on error nothing is saved

    idx = len(loaded.turns)
    level = clamp_level(loaded.level, out.evaluation.proposed_level, loaded.persona.max_step)
    trainee = m.Turn(
        session_id=session.id,
        idx=idx,
        role=TurnRole.TRAINEE,
        content=content,
        evaluation=out.evaluation.model_dump(mode="json"),
        idempotency_key=key,
    )
    persona = m.Turn(
        session_id=session.id,
        idx=idx + 1,
        role=TurnRole.PERSONA,
        content=out.reply,
        escalation_level=level,
        refs=_real_refs(out.refs, loaded.segment_ids),
    )
    db.add_all([trainee, persona])

    qualities = [t.evaluation["answer_quality"] for t in loaded.trainee_turns if t.evaluation]
    qualities.append(out.evaluation.answer_quality)
    used = len(loaded.trainee_turns) + 1
    still_open = [i for i in loaded.open_checklist if i not in out.evaluation.checklist_met]
    if used >= allowed_turns(loaded.persona, qualities):
        _mark_ended(session, EndReason.TURN_CAP)
    elif not still_open and used >= loaded.persona.min_turns:
        _mark_ended(session, EndReason.CONCERNS_RESOLVED)
    try:
        db.commit()
    except IntegrityError:  # two sends at the same moment: the database lets only one win
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "another message was saved first") from None
    if session.status == SessionStatus.ENDED:
        on_session_ended(session.id)
    return TurnResult(trainee, persona, Loaded(db, session), replayed=False)


def _mark_ended(session: m.RoleplaySession, reason: EndReason) -> None:
    session.status = SessionStatus.ENDED
    session.end_reason = reason
    session.ended_at = datetime.now(UTC)


def end_session(db: Session, session: m.RoleplaySession, user: CurrentUser) -> m.RoleplaySession:
    if session.status == SessionStatus.ACTIVE:
        by_admin = user.role == Role.ADMIN and user.user_ref != session.trainee_ref
        _mark_ended(session, EndReason.ADMIN_ENDED if by_admin else EndReason.TRAINEE_ENDED)
        db.commit()
        on_session_ended(session.id)
    return session
