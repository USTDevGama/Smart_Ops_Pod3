"""Report endpoints: is the report ready, make sure it is being made, and download it.

The report itself is written by the job that runs when a chat ends (`app/scoring/pipeline.py`:
files under `reports/<session_id>/` in blob storage). Nothing here scores or renders. It reads the
blob store and, when asked, sends that job again.

This module does not import the scoring or report packages, so the API process does not load the
PDF and Markdown libraries; `tests/test_api_reports.py` checks the file names below against the
pipeline's.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db, require_role
from app.config import get_settings
from app.db import models as m
from app.schemas.enums import Role, SessionStatus
from app.sessions.service import get_visible
from app.storage import BlobStore, get_blob_store
from app.workers.dispatch import send_assessment

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["reports"])

# Built once at module level (ruff B008).
any_user = require_role(Role.TRAINEE, Role.ADMIN)
admin_only = require_role(Role.ADMIN)

# format -> (file name under reports/<session_id>/, media type)
FORMATS = {
    "pdf": ("report.pdf", "application/pdf"),
    "html": ("report.html", "text/html; charset=utf-8"),
    "md": ("report.md", "text/markdown; charset=utf-8"),
}

# A chat that ended less than this long ago has a job queued or running (it is retried with growing
# delays), so asking again would pay for a second model call. After this, a missing report means
# the job was lost or gave up, and asking again sends it once more.
JOB_GRACE = timedelta(minutes=5)

NO_MODEL = (
    "a report needs a scoring model, and this server has none configured: set "
    "PODC_LLM_PROVIDER (and its keys) so the chat can be scored"
)

State = Literal["not_ended", "generating", "ready"]


class ReportStatus(BaseModel):
    session_id: UUID
    state: State  # not_ended -> generating -> ready
    model_configured: bool  # False: the fake model cannot score, so no report will appear
    can_download: bool  # admins only, and only once the report is ready
    formats: list[Literal["pdf", "html", "md"]]  # what can be downloaded now
    queued: bool | None = None  # POST only: whether a new job was sent


def _key(session_id: UUID | str, fmt: str) -> str:
    return f"reports/{session_id}/{FORMATS[fmt][0]}"


def _model_configured() -> bool:
    return get_settings().llm_provider != "fake"


def _status(session: m.RoleplaySession, store: BlobStore, user: CurrentUser) -> ReportStatus:
    if session.status != SessionStatus.ENDED:
        state: State = "not_ended"
    elif store.exists(_key(session.id, "pdf")):  # the last file the job writes
        state = "ready"
    else:
        state = "generating"
    can_download = state == "ready" and user.role == Role.ADMIN
    return ReportStatus(
        session_id=session.id,
        state=state,
        model_configured=_model_configured(),
        can_download=can_download,
        formats=[f for f in FORMATS if store.exists(_key(session.id, f))] if can_download else [],
    )


def _job_probably_running(session: m.RoleplaySession) -> bool:
    if get_settings().ingest_inline:  # no background job exists: the work is done in the request
        return False
    ended = session.ended_at
    if ended is None:
        return False
    if ended.tzinfo is None:  # SQLite hands back naive times
        ended = ended.replace(tzinfo=UTC)
    return datetime.now(UTC) - ended < JOB_GRACE


@router.get("/sessions/{session_id}/report", response_model=ReportStatus)
def report_status(
    session_id: UUID,
    user: CurrentUser = Depends(any_user),
    db: Session = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
):
    """Where the report is: `not_ended`, `generating` or `ready`. Visible to the chat's owner and
    admins; only admins are told they can download it."""
    return _status(get_visible(db, session_id, user), store, user)


@router.post("/sessions/{session_id}/report", response_model=ReportStatus, status_code=202)
def request_report(
    session_id: UUID,
    response: Response,
    user: CurrentUser = Depends(any_user),
    db: Session = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
):
    """Make sure the report is being generated. Safe to repeat: a ready report is left alone, and
    a job that is probably still running is not sent a second time."""
    session = get_visible(db, session_id, user)
    current = _status(session, store, user)
    if current.state == "not_ended":
        raise HTTPException(status.HTTP_409_CONFLICT, "the chat has not ended yet")
    if current.state == "ready":
        response.status_code = status.HTTP_200_OK
        return current.model_copy(update={"queued": False})
    if not current.model_configured:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_MODEL)
    if _job_probably_running(session):
        return current.model_copy(update={"queued": False})

    try:
        send_assessment(session.id)
    except Exception as exc:
        # The type only: the message of an unexpected error can echo conversation text.
        log.warning("report job for session %s failed to start: %s", session.id, type(exc).__name__)
        if get_settings().ingest_inline:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"the report could not be generated ({type(exc).__name__})",
            ) from None
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the report job could not be queued (is Redis running?)",
        ) from None

    after = _status(session, store, user).model_copy(update={"queued": True})
    if after.state == "ready":  # inline mode finishes the work inside this request
        response.status_code = status.HTTP_200_OK
    return after


@router.get("/admin/sessions/{session_id}/report/{fmt}")
def download_report(
    session_id: UUID,
    fmt: Literal["pdf", "html", "md"],
    _: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
):
    """Download one report file (admins only)."""
    if db.get(m.RoleplaySession, session_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    key = _key(session_id, fmt)
    if not store.exists(key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "the report is not ready")
    return Response(
        store.read(key),
        media_type=FORMATS[fmt][1],
        headers={
            "Content-Disposition": f'attachment; filename="report-{session_id}.{fmt}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
