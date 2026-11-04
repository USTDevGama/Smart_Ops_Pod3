import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.api.proposals as proposals_api
from app.config import Settings
from app.db.base import Base
from app.db.models import AppUser, AuditLog, ConfigVersion, Proposal, RoleplaySession
from app.db.session import get_session
from app.ingest.storage import BlobStore
from app.main import create_app
from app.schemas.enums import ConfigKind, ConfigStatus, SessionStatus
from app.workers.tasks import ingest_proposal
from tests.ingest_fixtures import make_docx, make_pdf

TXT = b"Budget is 400000.\n\nNo risks listed."


def trainee(name="trainee-a"):
    return {"X-Dev-User": name, "X-Dev-Role": "trainee"}


@pytest.fixture
def db():
    """Like the shared fixture, but one connection for all threads: TestClient runs requests
    on a worker thread, and a plain in-memory SQLite connection refuses that."""
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def queued(monkeypatch):
    """Records what the API would send to the worker. Nothing is really queued."""
    sent = []
    monkeypatch.setattr(ingest_proposal, "delay", lambda pid: sent.append(pid))
    return sent


@pytest.fixture
def api(db, tmp_path, queued):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[proposals_api.blob_store] = lambda: BlobStore(tmp_path)
    yield TestClient(app)
    app.dependency_overrides.clear()


def upload(client, name, data, headers=None):
    return client.post(
        "/api/v1/proposals",
        files={"file": (name, data)},
        headers=headers or trainee(),
    )


def test_upload_returns_202_queued_and_saves_the_file(api, db, tmp_path, queued):
    response = upload(api, "plan.txt", TXT)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["filename"] == "plan.txt"
    assert body["file_type"] == "txt"
    assert "blob_uri" not in body  # no storage path leaves the API
    assert queued == [body["id"]]  # only the id is sent to the worker
    saved = tmp_path / "proposals" / body["id"] / "original.txt"
    assert saved.read_bytes() == TXT
    assert db.scalar(select(AuditLog).where(AuditLog.action == "proposal.upload")) is not None


def test_upload_of_a_renamed_exe_is_refused(api, queued):
    response = upload(api, "plan.pdf", b"MZ\x90\x00 definitely not a pdf")
    assert response.status_code == 422
    assert queued == []


def test_unsupported_extension_is_refused(api):
    assert upload(api, "plan.exe", TXT).status_code == 422


def test_oversized_upload_is_refused(api, monkeypatch):
    monkeypatch.setattr(
        proposals_api, "get_settings", lambda: Settings(max_upload_mb=1, env="local")
    )
    assert upload(api, "plan.txt", b"x" * (1024 * 1024 + 1)).status_code == 422


def test_real_docx_and_pdf_are_accepted(api):
    assert upload(api, "plan.docx", make_docx([("", "Budget.")])).status_code == 202
    assert upload(api, "plan.pdf", make_pdf(["Budget."])).status_code == 202


def test_owner_can_read_their_proposal(api):
    proposal_id = upload(api, "plan.txt", TXT).json()["id"]
    response = api.get(f"/api/v1/proposals/{proposal_id}", headers=trainee())
    assert response.status_code == 200
    assert response.json()["id"] == proposal_id


def test_other_trainee_gets_404_not_403(api):
    proposal_id = upload(api, "plan.txt", TXT).json()["id"]
    response = api.get(f"/api/v1/proposals/{proposal_id}", headers=trainee("trainee-b"))
    assert response.status_code == 404


def test_admin_can_read_any_proposal(api):
    proposal_id = upload(api, "plan.txt", TXT).json()["id"]
    admin = {"X-Dev-User": "admin-1", "X-Dev-Role": "admin"}
    assert api.get(f"/api/v1/proposals/{proposal_id}", headers=admin).status_code == 200


def test_integrator_cannot_upload_or_read(api):
    integrator = {"X-Dev-User": "pod-d", "X-Dev-Role": "integrator"}
    proposal_id = upload(api, "plan.txt", TXT).json()["id"]
    assert upload(api, "plan.txt", TXT, headers=integrator).status_code == 403
    assert api.get(f"/api/v1/proposals/{proposal_id}", headers=integrator).status_code == 403


def test_no_login_is_unauthorised(api):
    assert api.post("/api/v1/proposals", files={"file": ("plan.txt", TXT)}).status_code == 401


def test_unknown_proposal_is_404(api):
    assert api.get(f"/api/v1/proposals/{uuid.uuid4()}", headers=trainee()).status_code == 404


def test_owner_can_delete_and_the_file_goes_too(api, db, tmp_path):
    proposal_id = upload(api, "plan.txt", TXT).json()["id"]
    response = api.delete(f"/api/v1/proposals/{proposal_id}", headers=trainee())

    assert response.status_code == 204
    assert db.get(Proposal, uuid.UUID(proposal_id)) is None
    assert not (tmp_path / "proposals" / proposal_id).exists()


def test_other_trainee_cannot_delete(api, db):
    proposal_id = upload(api, "plan.txt", TXT).json()["id"]
    response = api.delete(f"/api/v1/proposals/{proposal_id}", headers=trainee("trainee-b"))
    assert response.status_code == 404
    assert db.get(Proposal, uuid.UUID(proposal_id)) is not None


def test_delete_is_refused_when_a_session_used_the_proposal(api, db):
    proposal_id = upload(api, "plan.txt", TXT).json()["id"]
    owner = db.scalar(select(AppUser).where(AppUser.idp_sub == "trainee-a"))
    versions = [
        ConfigVersion(
            kind=kind,
            key=f"{kind.value}-test",
            version_no=1,
            status=ConfigStatus.PUBLISHED,
            config={},
        )
        for kind in (ConfigKind.PERSONA, ConfigKind.SCENARIO, ConfigKind.SCORING_PROFILE)
    ]
    db.add_all(versions)
    db.flush()
    db.add(
        RoleplaySession(
            trainee_id=owner.id,
            proposal_id=uuid.UUID(proposal_id),
            persona_version_id=versions[0].id,
            scenario_version_id=versions[1].id,
            scoring_profile_version_id=versions[2].id,
            status=SessionStatus.ENDED,
        )
    )
    db.commit()

    response = api.delete(f"/api/v1/proposals/{proposal_id}", headers=trainee())
    assert response.status_code == 409
    assert db.get(Proposal, uuid.UUID(proposal_id)) is not None
