"""The one place the API sends a background job. Tests patch these functions."""

import logging
from uuid import UUID

from app.config import get_settings

log = logging.getLogger(__name__)


def enqueue_profile_ingest(profile_id: UUID) -> None:
    """Queue `ingest_profile` (IDs only). With PODC_INGEST_INLINE=true, run it right here."""
    if get_settings().ingest_inline:
        from app.ingest.pipeline import ingest_profile_in_new_session

        ingest_profile_in_new_session(profile_id)
        return
    from app.workers.tasks import ingest_profile

    ingest_profile.delay(str(profile_id))


def enqueue_demand_ingest(demand_id: UUID) -> None:
    """Queue `ingest_demand` (IDs only). With PODC_INGEST_INLINE=true, run it right here."""
    if get_settings().ingest_inline:
        from app.ingest.pipeline import ingest_demand_in_new_session

        ingest_demand_in_new_session(demand_id)
        return
    from app.workers.tasks import ingest_demand

    ingest_demand.delay(str(demand_id))


def enqueue_assessment(session_id: UUID) -> None:
    """Queue `run_assessment` (ID only); it queues `render_report` when it finishes.

    With PODC_INGEST_INLINE=true both run right here. The chat has already ended, so a failure to
    score or to queue is logged and never raised back into the request.
    """
    try:
        if get_settings().ingest_inline:
            from app.scoring.pipeline import assess_and_render_in_new_session

            assess_and_render_in_new_session(session_id)
        else:
            from app.workers.tasks import run_assessment

            run_assessment.delay(str(session_id))
    except Exception:
        log.exception("could not start the assessment for session %s", session_id)
