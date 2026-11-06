"""Demand document endpoints. An admin uploads the project demand (master data, from the Gama
team); the pipeline reads it and the agent gets the result as it is. One demand serves everyone:
the most recently uploaded one that is ready."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Paging, get_db, paging, require_role
from app.db import models as m
from app.ingest.uploads import read_upload
from app.schemas.enums import FileType, IngestStatus, Role
from app.storage import BlobStore, get_blob_store
from app.workers.dispatch import enqueue_demand_ingest

router = APIRouter(prefix="/api/v1", tags=["demand"])

# Built once at module level (ruff B008).
admin_only = require_role(Role.ADMIN)


class DemandOut(BaseModel):
    id: UUID
    filename: str
    file_type: FileType
    status: IngestStatus
    error: str | None
    created_at: datetime
    uploaded_by: str


class DemandDetail(DemandOut):
    content: dict | None  # what the pipeline extracted; empty until ready


def current_demand(db: Session) -> m.DemandDocument | None:
    """The demand every new chat uses: the newest one that is ready."""
    return db.scalar(
        select(m.DemandDocument)
        .where(m.DemandDocument.status == IngestStatus.READY)
        .order_by(m.DemandDocument.created_at.desc())
    )


def _get(db: Session, demand_id: UUID) -> m.DemandDocument:
    demand = db.get(m.DemandDocument, demand_id)
    if demand is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "demand document not found")
    return demand


@router.post("/admin/demand", response_model=DemandDetail, status_code=202)
def upload_demand(
    response: Response,
    file: UploadFile,
    user: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
):
    """Save the file, queue the ingest job, return 202. Poll GET /admin/demand/{id}."""
    upload = read_upload(file)
    same = db.scalar(
        select(m.DemandDocument).where(
            m.DemandDocument.sha256 == upload.sha256,
            m.DemandDocument.status != IngestStatus.FAILED,
        )
    )
    if same is not None:  # the same file again: reuse the earlier one
        response.status_code = status.HTTP_200_OK
        return same

    demand = m.DemandDocument(
        uploaded_by=user.user_ref,
        filename=upload.filename,
        file_type=upload.file_type,
        sha256=upload.sha256,
        blob_uri=store.save(upload.data, f".{upload.file_type.value}"),
        status=IngestStatus.QUEUED,
    )
    db.add(demand)
    db.commit()
    enqueue_demand_ingest(demand.id)
    db.refresh(demand)
    return demand


@router.get("/admin/demand", response_model=list[DemandOut])
def list_demands(
    page: Paging = Depends(paging),
    _: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    query = select(m.DemandDocument).order_by(m.DemandDocument.created_at.desc())
    return db.scalars(query.limit(page.limit).offset(page.offset)).all()


@router.get("/admin/demand/{demand_id}", response_model=DemandDetail)
def get_demand(
    demand_id: UUID, _: CurrentUser = Depends(admin_only), db: Session = Depends(get_db)
):
    return _get(db, demand_id)


@router.delete("/admin/demand/{demand_id}", status_code=204)
def delete_demand(
    demand_id: UUID,
    _: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
):
    demand = _get(db, demand_id)
    in_use = db.scalar(
        select(func.count()).select_from(m.RoleplaySession).where(
            m.RoleplaySession.demand_id == demand.id
        )
    )
    if in_use:
        raise HTTPException(status.HTTP_409_CONFLICT, "a session uses this demand document")
    uri = demand.blob_uri
    db.delete(demand)
    db.commit()
    store.delete(uri)
    return Response(status_code=204)
