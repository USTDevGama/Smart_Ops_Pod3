"""Background job stubs. Messages carry IDs only, never profile text or personal data.

Each task must be safe to run twice: check the row's status first and overwrite its own rows.
Owners: ingest_profile and ingest_demand -> Dev A, run_assessment and render_report -> Disha,
sweep_stuck_jobs and the retention purge -> Dev D.
"""

from sqlalchemy.exc import SQLAlchemyError

from app.ingest.errors import TransientIngestError
from app.workers.celery_app import celery_app

# A storage or database hiccup is tried again (1, 2, 4 ... seconds apart, up to 3 retries). The
# pipeline sets the row back to `queued` between tries and fails it on the last one.
INGEST_RETRY = {
    "bind": True,
    "autoretry_for": (TransientIngestError, SQLAlchemyError),
    "retry_backoff": True,
    "retry_backoff_max": 300,
    "retry_jitter": True,
    "max_retries": 3,
}


@celery_app.task(name="ingest_profile", **INGEST_RETRY)
def ingest_profile(self, profile_id: str) -> None:
    from uuid import UUID

    from app.ingest.pipeline import ingest_profile_in_new_session

    # The pipeline is imported here, not above: the API process imports this module to send jobs
    # and should not load the PDF and DOCX readers.
    ingest_profile_in_new_session(
        UUID(profile_id), last_attempt=self.request.retries >= self.max_retries
    )


@celery_app.task(name="ingest_demand", **INGEST_RETRY)
def ingest_demand(self, demand_id: str) -> None:
    from uuid import UUID

    from app.ingest.pipeline import ingest_demand_in_new_session

    ingest_demand_in_new_session(
        UUID(demand_id), last_attempt=self.request.retries >= self.max_retries
    )


@celery_app.task(name="run_assessment", bind=True, max_retries=2)
def run_assessment(self, session_id: str) -> None:
    """Score the ended chat and save the assessment JSON, then queue `render_report`."""
    from uuid import UUID

    from app.llm import LLMError
    from app.scoring.pipeline import run_assessment_in_new_session
    from app.scoring.scorer import ScoringError

    # Imported here so the API process, which only sends jobs, does not load the scoring code.
    try:
        run_assessment_in_new_session(UUID(session_id))
    except (ScoringError, LLMError, SQLAlchemyError) as exc:
        raise self.retry(exc=exc, countdown=30 * 2**self.request.retries) from exc
    render_report.delay(session_id)


@celery_app.task(name="render_report", bind=True, max_retries=2)
def render_report(self, session_id: str) -> None:
    """Turn the saved assessment into the Markdown, HTML and PDF report files."""
    from uuid import UUID

    from app.scoring.pipeline import render_report_in_new_session

    try:
        render_report_in_new_session(UUID(session_id))
    except SQLAlchemyError as exc:
        raise self.retry(exc=exc, countdown=30 * 2**self.request.retries) from exc


@celery_app.task(name="sweep_stuck_jobs")
def sweep_stuck_jobs() -> None:
    raise NotImplementedError("Dev D: re-send anything stuck in 'queued'")
