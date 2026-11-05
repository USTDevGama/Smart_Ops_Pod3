"""Session and chat endpoints."""

import json
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.engine import TurnEngine, get_engine
from app.api.deps import CurrentUser, Paging, get_db, paging, require_role
from app.db import models as m
from app.schemas.enums import EndReason, Role, SessionStatus, TurnRole
from app.sessions import service
from app.sessions.service import Loaded

router = APIRouter(prefix="/api/v1", tags=["sessions"])

# Built once at module level (ruff B008).
any_user = require_role(Role.TRAINEE, Role.ADMIN)


class NewSession(BaseModel):
    persona_key: str
    profile_id: UUID  # the trainee's ready profile


class NewTurn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class VersionRef(BaseModel):
    key: str
    version_no: int


class TurnOut(BaseModel):
    id: UUID
    idx: int
    role: TurnRole
    content: str
    escalation_level: int | None
    created_at: datetime
    evaluation: dict | None = None  # admins only


class SessionOut(BaseModel):
    id: UUID
    trainee_ref: str
    profile_id: UUID | None
    persona: VersionRef
    demand_id: UUID | None
    status: SessionStatus
    end_reason: EndReason | None
    started_at: datetime
    ended_at: datetime | None
    level: int
    turns_used: int
    max_turns: int


class SessionDetail(SessionOut):
    turns: list[TurnOut]


def _turn_out(turn: m.Turn, user: CurrentUser) -> TurnOut:
    return TurnOut(
        id=turn.id,
        idx=turn.idx,
        role=turn.role,
        content=turn.content,
        escalation_level=turn.escalation_level,
        created_at=turn.created_at,
        evaluation=turn.evaluation if user.role == Role.ADMIN else None,
    )


def _session_fields(loaded: Loaded) -> dict:
    s = loaded.session
    return {
        "id": s.id,
        "trainee_ref": s.trainee_ref,
        "profile_id": s.profile_id,
        "persona": VersionRef(
            key=loaded.persona_version.key, version_no=loaded.persona_version.version_no
        ),
        "demand_id": s.demand_id,
        "status": s.status,
        "end_reason": s.end_reason,
        "started_at": s.started_at,
        "ended_at": s.ended_at,
        "level": loaded.level,
        "turns_used": len(loaded.trainee_turns),
        "max_turns": loaded.persona.max_turns,
    }


def _detail(loaded: Loaded, user: CurrentUser) -> SessionDetail:
    return SessionDetail(
        **_session_fields(loaded), turns=[_turn_out(t, user) for t in loaded.turns]
    )


@router.post("/sessions", response_model=SessionDetail, status_code=201)
def create_session(
    body: NewSession,
    user: CurrentUser = Depends(any_user),
    db: Session = Depends(get_db),
    engine: TurnEngine = Depends(get_engine),
):
    """Start a chat on a ready profile: pins the persona and demand, and the client speaks first."""
    loaded = service.start_session(db, engine, user, body.persona_key, body.profile_id)
    return _detail(loaded, user)


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    status: SessionStatus | None = None,
    trainee_ref: str | None = Query(default=None, description="admins only"),
    page: Paging = Depends(paging),
    user: CurrentUser = Depends(any_user),
    db: Session = Depends(get_db),
):
    query = select(m.RoleplaySession).order_by(m.RoleplaySession.started_at.desc())
    if user.role == Role.ADMIN:
        if trainee_ref:
            query = query.where(m.RoleplaySession.trainee_ref == trainee_ref)
    else:
        query = query.where(m.RoleplaySession.trainee_ref == user.user_ref)
    if status:
        query = query.where(m.RoleplaySession.status == status)
    rows = db.scalars(query.limit(page.limit).offset(page.offset)).all()
    return [SessionOut(**_session_fields(Loaded(db, row))) for row in rows]


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(
    session_id: UUID, user: CurrentUser = Depends(any_user), db: Session = Depends(get_db)
):
    return _detail(Loaded(db, service.get_visible(db, session_id, user)), user)


@router.post("/sessions/{session_id}/turns")
def send_turn(
    session_id: UUID,
    body: NewTurn,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100),
    user: CurrentUser = Depends(any_user),
    db: Session = Depends(get_db),
    engine: TurnEngine = Depends(get_engine),
):
    """Send a message. Returns a server-sent event stream: `message` (the reply), then `done`.

    Sending the same Idempotency-Key again returns the stored reply and saves nothing new.
    """
    session = service.get_visible(db, session_id, user)
    if session.trainee_ref != user.user_ref:  # even an admin cannot speak for a trainee
        raise HTTPException(404, "session not found")
    result = service.take_turn(db, engine, session, body.content.strip(), idempotency_key)

    def events():
        reply = _turn_out(result.persona, user).model_dump(mode="json")
        yield f"event: message\ndata: {json.dumps(reply)}\n\n"
        done = {
            "trainee_turn_id": str(result.trainee.id),
            "persona_turn_id": str(result.persona.id),
            "level": result.persona.escalation_level,
            "turns_used": result.turns_used,
            "ended": result.session.status == SessionStatus.ENDED,
            "end_reason": result.session.end_reason.value if result.session.end_reason else None,
            "replayed": result.replayed,
        }
        yield f"event: done\ndata: {json.dumps(done)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/sessions/{session_id}/end", response_model=SessionDetail)
def end_session(
    session_id: UUID, user: CurrentUser = Depends(any_user), db: Session = Depends(get_db)
):
    """End the chat. Harmless to repeat."""
    session = service.end_session(db, service.get_visible(db, session_id, user), user)
    return _detail(Loaded(db, session), user)
