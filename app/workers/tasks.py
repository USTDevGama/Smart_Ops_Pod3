"""Background job stubs. Messages carry IDs only, never profile text or personal data.

Each task must be safe to run twice: check the row's status first and overwrite its own rows.
Owners: ingest_profile and ingest_demand -> Dev A, run_assessment -> Dev C, render_report -> Dev A,
sweep_stuck_jobs and the retention purge -> Dev D.
"""

from app.workers.celery_app import celery_app


@celery_app.task(name="ingest_profile")
def ingest_profile(profile_id: str) -> None:
    # TEMPORARY: the real extraction comes from Kedar. Replace this call.
    from uuid import UUID

    from app.ingest.placeholder import ingest_profile_in_new_session

    ingest_profile_in_new_session(UUID(profile_id))


@celery_app.task(name="ingest_demand")
def ingest_demand(demand_id: str) -> None:
    # TEMPORARY: the real extraction comes from Kedar. Replace this call.
    from uuid import UUID

    from app.ingest.placeholder import ingest_demand_in_new_session

    ingest_demand_in_new_session(UUID(demand_id))


@celery_app.task(name="run_assessment")
def run_assessment(session_id: str) -> None:
    raise NotImplementedError("Dev C: validate criterion scores, apply weights, compute confidence")


@celery_app.task(name="render_report")
def render_report(session_id: str) -> None:
    raise NotImplementedError("Dev A: HTML to PDF report with citations")


@celery_app.task(name="sweep_stuck_jobs")
def sweep_stuck_jobs() -> None:
    raise NotImplementedError("Dev D: re-send anything stuck in 'queued'")
