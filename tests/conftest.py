import json
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
    monkeypatch.setattr("app.ingest.router.enqueue_ingest", queued.append)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_blob_store] = lambda: store
    yield SimpleNamespace(client=TestClient(app), factory=factory, store=store, queued=queued)
    app.dependency_overrides.clear()


def publish_sample_settings(client, persona_overrides: dict | None = None) -> None:
    """An admin publishes the made-up persona and scenario from samples/."""
    persona = load_sample("personas/ms_verma_strict.json") | (persona_overrides or {})
    scenario = load_sample("scenarios/vendor_delay.json")["scenarios"][0]
    for kind, key, config in (
        ("persona", "verma-strict", persona),
        ("scenario", "vendor-delay", scenario),
    ):
        created = client.post(
            f"/api/v1/admin/config/{kind}", headers=ADMIN, json={"key": key, "config": config}
        )
        assert created.status_code == 201, created.text
        published = client.post(
            f"/api/v1/admin/config/{kind}/{key}/versions/1/publish", headers=ADMIN
        )
        assert published.status_code == 200, published.text
