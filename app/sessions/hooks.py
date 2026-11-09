"""Hook for features that start when a session ends. Starts scoring and the report."""

from uuid import UUID

from app.workers.dispatch import enqueue_assessment


def on_session_ended(session_id: UUID) -> None:
    """Called once after a session is marked ended. Queues the assessment job (ID only)."""
    enqueue_assessment(session_id)
