"""Background job stubs. Messages carry IDs only, never profile text or personal data.

Each task must be safe to run twice: check the row's status first and overwrite its own rows.
Owners: ingest_profile and ingest_demand -> Dev A, run_assessment -> Dev C, render_report -> Dev A,
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


@celery_app.task(name="run_assessment")
def run_assessment(session_id: str) -> None:
    raise NotImplementedError("Dev C: validate criterion scores, apply weights, compute confidence")


@celery_app.task(name="render_report")
def render_report(session_id: str) -> None:
    raise NotImplementedError("Dev A: HTML to PDF report with citations")


@celery_app.task(name="sweep_stuck_jobs")
def sweep_stuck_jobs() -> None:
    raise NotImplementedError("Dev D: re-send anything stuck in 'queued'")
