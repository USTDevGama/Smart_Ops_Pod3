"""The one place the API sends a background job. Tests patch these functions."""

from uuid import UUID

from app.config import get_settings


def enqueue_ingest(proposal_id: UUID) -> None:
    """Queue `ingest_proposal` (IDs only). With PODC_INGEST_INLINE=true, run it right here."""
    if get_settings().ingest_inline:
        from app.ingest.placeholder import ingest_in_new_session

        ingest_in_new_session(proposal_id)
        return
    from app.workers.tasks import ingest_proposal

    ingest_proposal.delay(str(proposal_id))
