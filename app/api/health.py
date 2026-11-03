from fastapi import APIRouter, HTTPException

from app import __version__
from app.db import session as db_session

router = APIRouter()

AGENT_NAME = "pod-c-stakeholder-roleplay"
SIGNAL_SCHEMA_VERSION = "1.0"


@router.get("/healthz", tags=["ops"])
def healthz() -> dict:
    """Process is up."""
    return {"status": "ok"}


@router.get("/readyz", tags=["ops"])
def readyz() -> dict:
    """Process can reach its database."""
    if not db_session.check_database():
        raise HTTPException(status_code=503, detail="database not reachable")
    return {"status": "ready"}


@router.get("/api/v1/meta", tags=["ops"])
def meta() -> dict:
    """Registration info the TPM reads on Day 8."""
    return {
        "name": AGENT_NAME,
        "version": __version__,
        "signal_schema_version": SIGNAL_SCHEMA_VERSION,
        "capabilities": ["proposal-ingest", "persona-roleplay", "assessment"],
        "fallback_mode": False,
    }
