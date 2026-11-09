"""Background job stubs. Messages carry IDs only, never profile text or personal data.

Each task must be safe to run twice: check the row's status first and overwrite its own rows.
Owners: ingest_profile and ingest_demand -> Dev A, run_assessment (score and report) -> Disha,
sweep_stuck_jobs and the retention purge -> Dev D.
"""

from sqlalchemy.exc import SQLAlchemyError

from app.ingest.errors import TransientIngestError
from app.llm.base import LLMError
from app.scoring.scorer import ScoringError
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

# A failed or unusable model reply, or a database hiccup, is tried again 30, 60 ... seconds
# apart, up to 2 retries. A saved score is reused on a retry, so the model is not called twice.
ASSESS_RETRY = {
    "bind": True,
    "autoretry_for": (ScoringError, LLMError, SQLAlchemyError),
    "retry_backoff": 30,
    "retry_backoff_max": 300,
    "retry_jitter": False,
    "max_retries": 2,
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


@celery_app.task(name="run_assessment", **ASSESS_RETRY)
def run_assessment(self, session_id: str) -> None:
    """Score the ended chat and write the report files (the whole post-session job)."""
    from uuid import UUID

    from app.scoring.pipeline import assess_and_render_in_new_session

    # Imported here so the API process, which only sends jobs, does not load the PDF and
    # Markdown libraries.
    assess_and_render_in_new_session(UUID(session_id))


@celery_app.task(name="sweep_stuck_jobs")
def sweep_stuck_jobs() -> None:
    raise NotImplementedError("Dev D: re-send anything stuck in 'queued'")
