"""Proposal endpoints (upload, status, chunks, delete). Reading the file is the worker's job."""

import hashlib
import os
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Paging, can_see, get_db, paging, require_role
from app.config import get_settings
from app.db import models as m
from app.schemas import Brief, Segment
from app.schemas.enums import FileType, ProposalStatus, Role
from app.storage import BlobStore, get_blob_store
from app.workers.dispatch import enqueue_ingest

router = APIRouter(prefix="/api/v1", tags=["proposals"])

# Built once at module level (ruff B008).
any_user = require_role(Role.TRAINEE, Role.ADMIN)

_SUFFIX = {".pdf": FileType.PDF, ".docx": FileType.DOCX, ".txt": FileType.TXT}


class ProposalOut(BaseModel):
    id: UUID
    filename: str
    file_type: FileType
    status: ProposalStatus
    error: str | None
    created_at: datetime
    owner_ref: str


class ProposalDetail(ProposalOut):
    brief: Brief | None
    segment_count: int


def detect_type(filename: str, data: bytes) -> FileType:
    """The extension AND the first bytes must agree, so a renamed file is refused."""
    file_type = _SUFFIX.get(os.path.splitext(filename)[1].lower())
    if file_type is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "only PDF, DOCX or TXT")
    if file_type == FileType.PDF:
        ok = data.startswith(b"%PDF-")
    elif file_type == FileType.DOCX:
        ok = data.startswith(b"PK\x03\x04")
    else:
        try:
            data.decode("utf-8")
            ok = b"\x00" not in data
        except UnicodeDecodeError:
            ok = False
    if not ok:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"the content is not a valid {file_type.value}"
        )
    return file_type


def _owned(db: Session, proposal_id: UUID, user: CurrentUser) -> m.Proposal:
    proposal = db.get(m.Proposal, proposal_id)
    if proposal is None or not can_see(user, proposal.owner_ref):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proposal not found")
    return proposal


def _detail(db: Session, proposal: m.Proposal) -> ProposalDetail:
    count = db.scalar(
        select(func.count()).select_from(m.ProposalSegment).where(
            m.ProposalSegment.proposal_id == proposal.id
        )
    )
    return ProposalDetail(
        **ProposalOut.model_validate(proposal, from_attributes=True).model_dump(),
        brief=proposal.brief,
        segment_count=count or 0,
    )


@router.post("/proposals", response_model=ProposalDetail, status_code=202)
def upload_proposal(
    response: Response,
    file: UploadFile,
    user: CurrentUser = Depends(any_user),
    db: Session = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
):
    """Save the file, queue the ingest job, return 202. Poll GET /proposals/{id} until ready."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "file is too large")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "file is empty")
    filename = os.path.basename(file.filename or "upload")[:255]
    file_type = detect_type(filename, data)
    sha = hashlib.sha256(data).hexdigest()

    same = db.scalar(
        select(m.Proposal).where(
            m.Proposal.owner_ref == user.user_ref,
            m.Proposal.sha256 == sha,
            m.Proposal.status != ProposalStatus.FAILED,
        )
    )
    if same is not None:  # the same file again: reuse the earlier one and its brief
        response.status_code = status.HTTP_200_OK
        return _detail(db, same)

    proposal = m.Proposal(
        owner_ref=user.user_ref,
        filename=filename,
        file_type=file_type,
        sha256=sha,
        blob_uri=store.save(data, f".{file_type.value}"),
        status=ProposalStatus.QUEUED,
    )
    db.add(proposal)
    db.commit()
    enqueue_ingest(proposal.id)
    db.refresh(proposal)
    return _detail(db, proposal)


@router.get("/proposals", response_model=list[ProposalOut])
def list_proposals(
    owner_ref: str | None = None,
    page: Paging = Depends(paging),
    user: CurrentUser = Depends(any_user),
    db: Session = Depends(get_db),
):
    query = select(m.Proposal).order_by(m.Proposal.created_at.desc())
    if user.role == Role.ADMIN:
        if owner_ref:
            query = query.where(m.Proposal.owner_ref == owner_ref)
    else:
        query = query.where(m.Proposal.owner_ref == user.user_ref)
    return db.scalars(query.limit(page.limit).offset(page.offset)).all()


@router.get("/proposals/{proposal_id}", response_model=ProposalDetail)
def get_proposal(
    proposal_id: UUID, user: CurrentUser = Depends(any_user), db: Session = Depends(get_db)
):
    return _detail(db, _owned(db, proposal_id, user))


@router.get("/proposals/{proposal_id}/segments", response_model=list[Segment])
def list_segments(
    proposal_id: UUID, user: CurrentUser = Depends(any_user), db: Session = Depends(get_db)
):
    """The numbered chunks, so the UI can show the text a persona question cites."""
    _owned(db, proposal_id, user)
    return db.scalars(
        select(m.ProposalSegment)
        .where(m.ProposalSegment.proposal_id == proposal_id)
        .order_by(m.ProposalSegment.seq)
    ).all()


@router.delete("/proposals/{proposal_id}", status_code=204)
def delete_proposal(
    proposal_id: UUID,
    user: CurrentUser = Depends(any_user),
    db: Session = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
):
    proposal = _owned(db, proposal_id, user)
    in_use = db.scalar(
        select(func.count()).select_from(m.RoleplaySession).where(
            m.RoleplaySession.proposal_id == proposal.id
        )
    )
    if in_use:
        raise HTTPException(status.HTTP_409_CONFLICT, "a session uses this proposal")
    db.execute(delete(m.ProposalSegment).where(m.ProposalSegment.proposal_id == proposal.id))
    uri = proposal.blob_uri
    db.delete(proposal)
    db.commit()
    store.delete(uri)
    return Response(status_code=204)
