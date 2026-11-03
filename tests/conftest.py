import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db import models  # noqa: F401
from app.db.base import Base

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"


def load_sample(relative: str) -> dict:
    return json.loads((SAMPLES / relative).read_text(encoding="utf-8"))


@pytest.fixture
def db() -> Session:
    """In-memory SQLite with foreign keys on: tests need no Postgres or Docker."""
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
