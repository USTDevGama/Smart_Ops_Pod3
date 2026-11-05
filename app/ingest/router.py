"""Profile endpoints (upload, status, chunks, delete). Reading the file is the worker's job."""

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
from app.schemas.enums import FileType, ProfileStatus, Role
from app.storage import BlobStore, get_blob_store
from app.workers.dispatch import enqueue_ingest

router = APIRouter(prefix="/api/v1", tags=["profiles"])

# Built once at module level (ruff B008).
any_user = require_role(Role.TRAINEE, Role.ADMIN)

_SUFFIX = {".pdf": FileType.PDF, ".docx": FileType.DOCX, ".txt": FileType.TXT}


class ProfileOut(BaseModel):
    id: UUID
    filename: str
    file_type: FileType
    status: ProfileStatus
    error: str | None
    created_at: datetime
    owner_ref: str


class ProfileDetail(ProfileOut):
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


def _owned(db: Session, profile_id: UUID, user: CurrentUser) -> m.Profile:
    profile = db.get(m.Profile, profile_id)
    if profile is None or not can_see(user, profile.owner_ref):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "profile not found")
    return profile


def _detail(db: Session, profile: m.Profile) -> ProfileDetail:
    count = db.scalar(
        select(func.count()).select_from(m.ProfileSegment).where(
            m.ProfileSegment.profile_id == profile.id
        )
    )
    return ProfileDetail(
        **ProfileOut.model_validate(profile, from_attributes=True).model_dump(),
        brief=profile.brief,
        segment_count=count or 0,
    )


@router.post("/profiles", response_model=ProfileDetail, status_code=202)
def upload_profile(
    response: Response,
    file: UploadFile,
    user: CurrentUser = Depends(any_user),
    db: Session = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
):
    """Save the file, queue the ingest job, return 202. Poll GET /profiles/{id} until ready."""
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
        select(m.Profile).where(
            m.Profile.owner_ref == user.user_ref,
            m.Profile.sha256 == sha,
            m.Profile.status != ProfileStatus.FAILED,
        )
    )
    if same is not None:  # the same file again: reuse the earlier one and its brief
        response.status_code = status.HTTP_200_OK
        return _detail(db, same)

    profile = m.Profile(
        owner_ref=user.user_ref,
        filename=filename,
        file_type=file_type,
        sha256=sha,
        blob_uri=store.save(data, f".{file_type.value}"),
        status=ProfileStatus.QUEUED,
    )
    db.add(profile)
    db.commit()
    enqueue_ingest(profile.id)
    db.refresh(profile)
    return _detail(db, profile)


@router.get("/profiles", response_model=list[ProfileOut])
def list_profiles(
    owner_ref: str | None = None,
    page: Paging = Depends(paging),
    user: CurrentUser = Depends(any_user),
    db: Session = Depends(get_db),
):
    query = select(m.Profile).order_by(m.Profile.created_at.desc())
    if user.role == Role.ADMIN:
        if owner_ref:
            query = query.where(m.Profile.owner_ref == owner_ref)
    else:
        query = query.where(m.Profile.owner_ref == user.user_ref)
    return db.scalars(query.limit(page.limit).offset(page.offset)).all()


@router.get("/profiles/{profile_id}", response_model=ProfileDetail)
def get_profile(
    profile_id: UUID, user: CurrentUser = Depends(any_user), db: Session = Depends(get_db)
):
    return _detail(db, _owned(db, profile_id, user))


@router.get("/profiles/{profile_id}/segments", response_model=list[Segment])
def list_segments(
    profile_id: UUID, user: CurrentUser = Depends(any_user), db: Session = Depends(get_db)
):
    """The numbered chunks, so the UI can show the text a persona question cites."""
    _owned(db, profile_id, user)
    return db.scalars(
        select(m.ProfileSegment)
        .where(m.ProfileSegment.profile_id == profile_id)
        .order_by(m.ProfileSegment.seq)
    ).all()


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(
    profile_id: UUID,
    user: CurrentUser = Depends(any_user),
    db: Session = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
):
    profile = _owned(db, profile_id, user)
    in_use = db.scalar(
        select(func.count()).select_from(m.RoleplaySession).where(
            m.RoleplaySession.profile_id == profile.id
        )
    )
    if in_use:
        raise HTTPException(status.HTTP_409_CONFLICT, "a session uses this profile")
    db.execute(delete(m.ProfileSegment).where(m.ProfileSegment.profile_id == profile.id))
    uri = profile.blob_uri
    db.delete(profile)
    db.commit()
    store.delete(uri)
    return Response(status_code=204)
