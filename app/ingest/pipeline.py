"""The ingest job: read an uploaded file and keep its text, as markdown, in the row's `content`.

Used for both the trainee profile and the admin demand document. The status follows the job:
`queued` -> `extracting` -> `ready`, or `failed` with an error. The agent receives `content` as it
is, so the shape is `{"text": "<markdown>"}`.

A problem with the file fails the row at once. A problem that is not the file's fault (storage or
database hiccup) puts the row back to `queued` and raises `TransientIngestError`, so Celery tries
again; on the last attempt the row is failed instead, so it is never left waiting for ever.
"""

import logging
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import get_engine
from app.ingest.errors import ExtractionError, TransientIngestError
from app.ingest.extract import extract_markdown
from app.schemas.enums import IngestStatus
from app.storage import BlobStore, get_blob_store

log = logging.getLogger(__name__)

NO_TEXT = "no readable text was found in the file"
MISSING = "the uploaded file could not be found"
FAILED = "the file could not be processed"
GAVE_UP = "the file could not be processed right now: upload it again later"


def _ingest(
    db: Session, model: type, row_id: UUID, store: BlobStore, last_attempt: bool = False
) -> None:
    row = db.get(model, row_id)
    if row is None or row.status == IngestStatus.READY:
        return  # safe to run twice
    row.status = IngestStatus.EXTRACTING
    db.commit()
    try:
        text = extract_markdown(store.read(row.blob_uri), row.file_type)
        if not text:
            raise ExtractionError(NO_TEXT)
        row.content = {"text": text}
        row.error = None
        row.status = IngestStatus.READY
    except Exception as exc:
        db.rollback()
        transient = _is_transient(exc)
        if transient and not last_attempt:
            _set_status(db, model, row_id, IngestStatus.QUEUED)
            # The type only: the message of an unexpected error can echo the file's content.
            log.warning("ingest will be retried: %s", type(exc).__name__)
            raise TransientIngestError from None
        _set_status(db, model, row_id, IngestStatus.FAILED, _safe_error(exc, transient))
        return
    db.commit()


def _is_transient(exc: Exception) -> bool:
    """A storage or database problem, as opposed to something wrong with the file."""
    if isinstance(exc, SQLAlchemyError):
        return True
    return isinstance(exc, OSError) and not isinstance(exc, FileNotFoundError)


def _safe_error(exc: Exception, transient: bool) -> str:
    """What the uploader may see. Never `str(exc)` for an unexpected error: it can echo content."""
    if isinstance(exc, ExtractionError):
        return str(exc)
    if isinstance(exc, FileNotFoundError):
        return MISSING
    log.warning("ingest failed: %s", type(exc).__name__)
    return GAVE_UP if transient else FAILED


def _set_status(
    db: Session, model: type, row_id: UUID, status: IngestStatus, error: str | None = None
) -> None:
    row = db.get(model, row_id)
    row.status = status
    row.error = error
    db.commit()


def ingest_profile(
    db: Session, profile_id: UUID, store: BlobStore, last_attempt: bool = False
) -> None:
    _ingest(db, m.Profile, profile_id, store, last_attempt)


def ingest_demand(
    db: Session, demand_id: UUID, store: BlobStore, last_attempt: bool = False
) -> None:
    _ingest(db, m.DemandDocument, demand_id, store, last_attempt)


def ingest_profile_in_new_session(profile_id: UUID, last_attempt: bool = False) -> None:
    with Session(get_engine()) as db:
        ingest_profile(db, profile_id, get_blob_store(), last_attempt)


def ingest_demand_in_new_session(demand_id: UUID, last_attempt: bool = False) -> None:
    with Session(get_engine()) as db:
        ingest_demand(db, demand_id, get_blob_store(), last_attempt)
