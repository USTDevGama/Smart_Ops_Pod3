import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.db import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.schemas.enums import FileType, IngestStatus
from app.storage import LocalBlobStore, get_blob_store

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"

ADMIN = {"X-Dev-User": "admin1", "X-Dev-Role": "admin"}
ANNA = {"X-Dev-User": "anna", "X-Dev-Role": "trainee"}
BEN = {"X-Dev-User": "ben", "X-Dev-Role": "trainee"}


def load_sample(relative: str) -> dict:
    return json.loads((SAMPLES / relative).read_text(encoding="utf-8"))


def _fk_on(dbapi_conn, _):
    dbapi_conn.execute("PRAGMA foreign_keys=ON")


@pytest.fixture
def db() -> Session:
    """In-memory SQLite with foreign keys on: tests need no Postgres or Docker."""
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", _fk_on)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def api(tmp_path, monkeypatch):
    """The real app on an in-memory database, a temp upload folder and no job queue."""
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    event.listen(engine, "connect", _fk_on)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with factory() as session:
            yield session

    store = LocalBlobStore(tmp_path / "blobs")
    queued: list = []
    queued_demand: list = []
    queued_assessment: list = []
    monkeypatch.setattr("app.ingest.router.enqueue_profile_ingest", queued.append)
    monkeypatch.setattr("app.ingest.demand_router.enqueue_demand_ingest", queued_demand.append)
    monkeypatch.setattr("app.sessions.hooks.enqueue_assessment", queued_assessment.append)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_blob_store] = lambda: store
    yield SimpleNamespace(
        client=TestClient(app), factory=factory, store=store, queued=queued,
        queued_demand=queued_demand, queued_assessment=queued_assessment,
    )
    app.dependency_overrides.clear()


def ready_profile(api, owner_ref: str = "anna") -> str:
    """A trainee profile that is already ingested (a ready row, no file needed)."""
    with api.factory() as db:
        row = models.Profile(
            owner_ref=owner_ref, filename="profile.txt", file_type=FileType.TXT,
            sha256=uuid.uuid4().hex * 2, blob_uri="none", status=IngestStatus.READY,
            content={"text": "Backend engineer. Led a billing rewrite; one service shipped late."},
        )
        db.add(row)
        db.commit()
        return str(row.id)


def ready_demand(api, minutes_ago: int = 0) -> str:
    """An admin-uploaded demand document that is already ingested."""
    with api.factory() as db:
        row = models.DemandDocument(
            uploaded_by="admin1", filename="demand.txt", file_type=FileType.TXT,
            sha256=uuid.uuid4().hex * 2, blob_uri="none", status=IngestStatus.READY,
            content={"text": "Billing modernisation. The invoicing release is due in ten days."},
            created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        )
        db.add(row)
        db.commit()
        return str(row.id)


def publish_sample_settings(
    client, persona_overrides: dict | None = None, scenarios: bool = True
) -> None:
    """An admin publishes the made-up persona and imports the made-up scenarios."""
    persona = load_sample("personas/ms_verma_strict.json") | (persona_overrides or {})
    if scenarios:
        imported = client.post(
            "/api/v1/admin/scenarios/import", headers=ADMIN,
            json=load_sample("scenarios/vendor_delay.json"),
        )
        assert imported.status_code == 200, imported.text
    created = client.post(
        "/api/v1/admin/config/persona", headers=ADMIN,
        json={"key": "verma-strict", "config": persona},
    )
    assert created.status_code == 201, created.text
    published = client.post(
        "/api/v1/admin/config/persona/verma-strict/versions/1/publish", headers=ADMIN
    )
    assert published.status_code == 200, published.text
