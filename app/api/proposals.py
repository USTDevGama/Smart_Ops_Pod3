"""Proposal upload, status and delete. Trainees own their proposals; admins can read any."""

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_role
from app.config import get_settings
from app.db.models import AppUser, AuditLog, Proposal, ProposalSegment, RoleplaySession
from app.db.session import get_session
from app.ingest.storage import BlobStore
from app.ingest.validate import (
    UploadRejected,
    check_content,
    check_size,
    display_name,
    file_type_for,
)
from app.schemas.enums import ProposalStatus, Role
from app.schemas.proposal import ProposalOut
from app.workers.tasks import ingest_proposal

router = APIRouter(prefix="/api/v1/proposals", tags=["proposals"])

MB = 1024 * 1024
TRAINEE_ONLY = require_role(Role.TRAINEE)
TRAINEE_OR_ADMIN = require_role(Role.TRAINEE, Role.ADMIN)


def blob_store() -> BlobStore:
    """A dependency so tests can point storage at a temporary folder."""
    return BlobStore(Path(get_settings().blob_dir))


@router.post("", status_code=202, response_model=ProposalOut)
def upload_proposal(
    file: UploadFile,
    user: CurrentUser = Depends(TRAINEE_ONLY),
    session: Session = Depends(get_session),
    store: BlobStore = Depends(blob_store),
) -> Proposal:
    """Save the file and queue ingestion. Returns 202 while the status is still `queued`."""
    limit = get_settings().max_upload_mb * MB
    try:
        name = display_name(file.filename)
        file_type = file_type_for(name)
        data = file.file.read(limit + 1)  # never read more than the limit plus one byte
        check_size(data, limit)
        check_content(data, file_type)
    except UploadRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    owner = _owner(session, user)
    proposal_id = uuid.uuid4()
    key = f"proposals/{proposal_id}/original.{file_type.value}"
    store.save(key, data)  # file first: a queued row must always have its file
    proposal = Proposal(
        id=proposal_id,
        owner_id=owner.id,
        filename=name,
        file_type=file_type,
        sha256=hashlib.sha256(data).hexdigest(),
        blob_uri=key,
        status=ProposalStatus.QUEUED,
    )
    session.add(proposal)
    session.add(
        AuditLog(
            actor_id=owner.id,
            action="proposal.upload",
            entity_type="proposal",
            entity_id=proposal_id,
            detail={"file_type": file_type.value, "bytes": len(data)},
        )
    )
    session.commit()
    # Only the id is sent. If this fails, the row stays queued and the sweeper re-sends it.
    ingest_proposal.delay(str(proposal_id))
    return proposal


@router.get("/{proposal_id}", response_model=ProposalOut)
def get_proposal(
    proposal_id: uuid.UUID,
    user: CurrentUser = Depends(TRAINEE_OR_ADMIN),
    session: Session = Depends(get_session),
) -> Proposal:
    return _visible(session, user, proposal_id)


@router.delete("/{proposal_id}", status_code=204)
def delete_proposal(
    proposal_id: uuid.UUID,
    user: CurrentUser = Depends(TRAINEE_ONLY),
    session: Session = Depends(get_session),
    store: BlobStore = Depends(blob_store),
) -> Response:
    proposal = _visible(session, user, proposal_id)
    # Sessions point at their proposal without a cascade, so a used proposal cannot be removed
    # here. The retention purge removes it once those sessions are purged.
    used = session.scalar(
        select(RoleplaySession.id).where(RoleplaySession.proposal_id == proposal.id).limit(1)
    )
    if used is not None:
        raise HTTPException(status_code=409, detail="a roleplay session already used this proposal")

    key = proposal.blob_uri
    session.execute(delete(ProposalSegment).where(ProposalSegment.proposal_id == proposal.id))
    session.add(
        AuditLog(
            actor_id=proposal.owner_id,
            action="proposal.delete",
            entity_type="proposal",
            entity_id=proposal.id,
        )
    )
    session.delete(proposal)
    session.commit()
    store.delete(key)
    return Response(status_code=204)


def _owner(session: Session, user: CurrentUser) -> AppUser:
    """The app_user row for this login, created on first upload."""
    owner = session.scalar(select(AppUser).where(AppUser.idp_sub == user.user_ref))
    if owner is None:
        owner = AppUser(idp_sub=user.user_ref)
        session.add(owner)
        session.flush()
    return owner


def _visible(session: Session, user: CurrentUser, proposal_id: uuid.UUID) -> Proposal:
    """A trainee gets 404 for someone else's proposal, so ids cannot be probed."""
    query = select(Proposal).where(Proposal.id == proposal_id)
    if user.role is not Role.ADMIN:
        query = query.join(AppUser, Proposal.owner_id == AppUser.id).where(
            AppUser.idp_sub == user.user_ref
        )
    proposal = session.scalar(query)
    if proposal is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return proposal
