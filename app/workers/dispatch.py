"""The one place the API sends a background job. Tests patch these functions."""

from uuid import UUID

from app.config import get_settings


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
