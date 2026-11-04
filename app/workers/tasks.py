"""Background job stubs. Messages carry IDs only, never proposal text or personal data.

Each task must be safe to run twice: check the row's status first and overwrite its own rows.
Owners: ingest_proposal -> Dev A, run_assessment -> Dev C, render_report -> Dev A,
sweep_stuck_jobs and the retention purge -> Dev D.
"""

from pathlib import Path
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db.session import make_session
from app.ingest.extract import OcrUnavailable
from app.ingest.pipeline import run_ingest
from app.ingest.storage import BlobStore
from app.workers.celery_app import celery_app


@celery_app.task(
    name="ingest_proposal",
    autoretry_for=(OSError, SQLAlchemyError, OcrUnavailable),
    retry_backoff=True,
    max_retries=3,
)
def ingest_proposal(proposal_id: str) -> None:
    settings = get_settings()
    with make_session() as session:
        run_ingest(session, UUID(proposal_id), BlobStore(Path(settings.blob_dir)), settings)


@celery_app.task(name="run_assessment")
def run_assessment(assessment_id: str) -> None:
    raise NotImplementedError("Dev C: scoring graph, quote check, blend, confidence")


@celery_app.task(name="render_report")
def render_report(assessment_id: str) -> None:
    raise NotImplementedError("Dev A: HTML to PDF report with citations")


@celery_app.task(name="sweep_stuck_jobs")
def sweep_stuck_jobs() -> None:
    raise NotImplementedError("Dev D: re-send anything stuck in 'queued'")
