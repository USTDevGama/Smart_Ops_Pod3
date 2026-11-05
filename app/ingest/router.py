"""Profile endpoints (upload, status, delete). Reading the file is the worker's job."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Paging, can_see, get_db, paging, require_role
from app.db import models as m
from app.ingest.uploads import read_upload
from app.schemas.enums import FileType, IngestStatus, Role
from app.storage import BlobStore, get_blob_store
from app.workers.dispatch import enqueue_profile_ingest

router = APIRouter(prefix="/api/v1", tags=["profiles"])

# Built once at module level (ruff B008).
any_user = require_role(Role.TRAINEE, Role.ADMIN)


class ProfileOut(BaseModel):
    id: UUID
    filename: str
    file_type: FileType
    status: IngestStatus
    error: str | None
    created_at: datetime
    owner_ref: str


class ProfileDetail(ProfileOut):
    content: dict | None  # what the pipeline extracted; empty until ready


def _owned(db: Session, profile_id: UUID, user: CurrentUser) -> m.Profile:
    profile = db.get(m.Profile, profile_id)
    if profile is None or not can_see(user, profile.owner_ref):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "profile not found")
    return profile


@router.post("/profiles", response_model=ProfileDetail, status_code=202)
def upload_profile(
    response: Response,
    file: UploadFile,
    user: CurrentUser = Depends(any_user),
    db: Session = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
):
    """Save the file, queue the ingest job, return 202. Poll GET /profiles/{id} until ready."""
    upload = read_upload(file)
    same = db.scalar(
        select(m.Profile).where(
            m.Profile.owner_ref == user.user_ref,
            m.Profile.sha256 == upload.sha256,
            m.Profile.status != IngestStatus.FAILED,
        )
    )
    if same is not None:  # the same file again: reuse the earlier one
        response.status_code = status.HTTP_200_OK
        return same

    profile = m.Profile(
        owner_ref=user.user_ref,
        filename=upload.filename,
        file_type=upload.file_type,
        sha256=upload.sha256,
        blob_uri=store.save(upload.data, f".{upload.file_type.value}"),
        status=IngestStatus.QUEUED,
    )
    db.add(profile)
    db.commit()
    enqueue_profile_ingest(profile.id)
    db.refresh(profile)
    return profile


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
    return _owned(db, profile_id, user)


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
    uri = profile.blob_uri
    db.delete(profile)
    db.commit()
    store.delete(uri)
    return Response(status_code=204)
