from uuid import UUID

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import models as m
from app.ingest import placeholder
from tests.conftest import ADMIN, ANNA, BEN, SAMPLES, publish_sample_settings

TXT = (
    b"1. Summary\n\nSix months, $400,000, three teams.\n\n4. Budget\n\n"
    b"A detailed breakdown will follow after approval."
)
PDF = b"%PDF-1.7\n%starts like a pdf"


def _upload(api, headers=ANNA, name="p.txt", data=TXT):
    return api.client.post("/api/v1/proposals", headers=headers, files={"file": (name, data)})


def _row(api, proposal_id: str) -> m.Proposal:
    with api.factory() as db:
        return db.get(m.Proposal, UUID(proposal_id))


def _ingest(api) -> None:
    with api.factory() as db:
        placeholder.ingest(db, api.queued[-1], api.store)


def test_upload_saves_the_file_and_queues_the_job(api):
    response = _upload(api)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert api.queued == [UUID(body["id"])]
    assert api.store.read(_row(api, body["id"]).blob_uri) == TXT


def test_the_same_file_twice_gives_the_same_proposal(api):
    first = _upload(api).json()
    second = _upload(api)
    assert second.status_code == 200
    assert second.json()["id"] == first["id"]
    assert len(api.queued) == 1


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("notes.exe", b"MZ"),
        ("fake.pdf", b"not a pdf"),
        ("fake.docx", b"plain text"),
        ("binary.txt", b"\x00\x01\x02"),
    ],
)
def test_wrong_file_types_are_refused(api, name, data):
    assert _upload(api, name=name, data=data).status_code == 415
    assert api.queued == []


def test_an_empty_or_oversize_file_is_refused(api, monkeypatch):
    assert _upload(api, data=b"").status_code == 400
    monkeypatch.setenv("PODC_MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    try:
        assert _upload(api, data=b"a" * (1024 * 1024 + 1)).status_code == 413
    finally:
        get_settings.cache_clear()


def test_a_pdf_is_accepted(api):
    assert _upload(api, name="p.pdf", data=PDF).status_code == 202


def test_people_only_see_their_own_proposals(api):
    mine = _upload(api).json()["id"]
    assert api.client.get(f"/api/v1/proposals/{mine}", headers=ANNA).status_code == 200
    assert api.client.get(f"/api/v1/proposals/{mine}", headers=BEN).status_code == 404
    assert api.client.get(f"/api/v1/proposals/{mine}", headers=ADMIN).status_code == 200
    assert api.client.get("/api/v1/proposals", headers=BEN).json() == []
    assert len(api.client.get("/api/v1/proposals", headers=ADMIN).json()) == 1


def test_after_ingest_the_brief_and_chunks_are_readable(api):
    proposal_id = _upload(api).json()["id"]
    _ingest(api)
    detail = api.client.get(f"/api/v1/proposals/{proposal_id}", headers=ANNA).json()
    assert detail["status"] == "ready"
    assert detail["segment_count"] == 4
    segments = api.client.get(f"/api/v1/proposals/{proposal_id}/segments", headers=ANNA).json()
    assert [s["seq"] for s in segments] == [1, 2, 3, 4]
    cited = {sid for item in detail["brief"]["items"] for sid in item["segment_ids"]}
    assert cited <= {s["id"] for s in segments}  # every citation is a real chunk


def test_the_placeholder_marks_unreadable_files_failed(api):
    proposal_id = _upload(api, name="p.pdf", data=PDF).json()["id"]
    _ingest(api)
    detail = api.client.get(f"/api/v1/proposals/{proposal_id}", headers=ANNA).json()
    assert detail["status"] == "failed"
    assert "only reads .txt" in detail["error"]


def test_delete_removes_the_file_and_chunks(api):
    proposal_id = _upload(api).json()["id"]
    _ingest(api)
    uri = _row(api, proposal_id).blob_uri
    assert api.client.delete(f"/api/v1/proposals/{proposal_id}", headers=BEN).status_code == 404
    assert api.client.delete(f"/api/v1/proposals/{proposal_id}", headers=ANNA).status_code == 204
    with api.factory() as db:
        assert db.scalars(select(m.ProposalSegment)).all() == []
    with pytest.raises(FileNotFoundError):
        api.store.read(uri)


def test_a_proposal_used_by_a_session_cannot_be_deleted(api):
    publish_sample_settings(api.client)
    proposal_id = _upload(api).json()["id"]
    _ingest(api)
    started = api.client.post(
        "/api/v1/sessions",
        headers=ANNA,
        json={"persona_key": "verma-strict", "proposal_id": proposal_id},
    )
    assert started.status_code == 201
    assert api.client.delete(f"/api/v1/proposals/{proposal_id}", headers=ANNA).status_code == 409


def test_the_sample_proposal_file_ingests(api):
    data = (SAMPLES / "proposals" / "billing_migration.txt").read_bytes()
    proposal_id = _upload(api, data=data, name="billing.txt").json()["id"]
    _ingest(api)
    detail = api.client.get(f"/api/v1/proposals/{proposal_id}", headers=ANNA).json()
    assert detail["status"] == "ready"
