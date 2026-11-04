"""Hook for features that start when a session ends (scoring, reports). Does nothing yet."""

from uuid import UUID


def on_session_ended(session_id: UUID) -> None:
    """Called once after a session is marked ended. The scoring owner plugs in here."""
