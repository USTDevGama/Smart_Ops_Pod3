"""TEMPORARY stand-in for the real ingestion (Kedar's work), so chat can use the uploads.

It only reads .txt files and keeps the whole text as `{"text": "..."}` in the row's `content`
column. The real pipeline may put any JSON there (the agent receives it as it is); it must keep
the same outcome: `content` filled and status ready, or status failed with an error.
Used for both the trainee profile and the admin demand document.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import get_engine
from app.schemas.enums import FileType, IngestStatus
from app.storage import BlobStore, get_blob_store


def _ingest(db: Session, model: type, row_id: UUID, store: BlobStore) -> None:
    row = db.get(model, row_id)
    if row is None or row.status == IngestStatus.READY:
        return  # safe to run twice
    row.status = IngestStatus.EXTRACTING
    db.commit()
    try:
        if row.file_type != FileType.TXT:
            raise ValueError("the placeholder ingest only reads .txt files")
        text = store.read(row.blob_uri).decode("utf-8").strip()
        if not text:
            raise ValueError("the file has no text")
        row.content = {"text": text}
        row.error = None
        row.status = IngestStatus.READY
    except Exception as exc:
        db.rollback()
        row = db.get(model, row_id)
        row.status = IngestStatus.FAILED
        row.error = str(exc)[:500]
    db.commit()


def ingest_profile(db: Session, profile_id: UUID, store: BlobStore) -> None:
    _ingest(db, m.Profile, profile_id, store)


def ingest_demand(db: Session, demand_id: UUID, store: BlobStore) -> None:
    _ingest(db, m.DemandDocument, demand_id, store)


def ingest_profile_in_new_session(profile_id: UUID) -> None:
    with Session(get_engine()) as db:
        ingest_profile(db, profile_id, get_blob_store())


def ingest_demand_in_new_session(demand_id: UUID) -> None:
    with Session(get_engine()) as db:
        ingest_demand(db, demand_id, get_blob_store())
