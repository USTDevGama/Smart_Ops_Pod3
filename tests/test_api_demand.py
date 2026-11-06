from uuid import UUID

import pytest
from sqlalchemy import select

from app.db import models as m
from app.ingest import pipeline
from tests.conftest import (
    ADMIN,
    ANNA,
    SAMPLES,
    publish_sample_settings,
    ready_demand,
    ready_profile,
)
from tests.ingest_fixtures import make_docx, make_text_pdf

BASE = "/api/v1/admin/demand"
TXT = b"1. Project\n\nBilling modernisation.\n\n2. Pressure\n\nThe release is due in ten days."


def _upload(api, headers=ADMIN, name="demand.txt", data=TXT):
    return api.client.post(BASE, headers=headers, files={"file": (name, data)})


def _ingest(api) -> None:
    with api.factory() as db:
        pipeline.ingest_demand(db, api.queued_demand[-1], api.store)


def test_only_admins_manage_the_demand_document(api):
    assert _upload(api, headers=ANNA).status_code == 403
    assert api.client.get(BASE, headers=ANNA).status_code == 403
    assert api.queued_demand == []


def test_upload_saves_the_file_and_queues_the_job(api):
    response = _upload(api)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["uploaded_by"] == "admin1"
    assert api.queued_demand == [UUID(body["id"])]
    with api.factory() as db:
        row = db.get(m.DemandDocument, UUID(body["id"]))
        assert api.store.read(row.blob_uri) == TXT


def test_the_same_file_twice_gives_the_same_document(api):
    first = _upload(api).json()
    second = _upload(api)
    assert second.status_code == 200
    assert second.json()["id"] == first["id"]
    assert len(api.queued_demand) == 1


@pytest.mark.parametrize(
    ("name", "data"), [("notes.exe", b"MZ"), ("fake.pdf", b"not a pdf"), ("empty.txt", b"\x00\x01")]
)
def test_wrong_file_types_are_refused(api, name, data):
    assert _upload(api, name=name, data=data).status_code == 415
    assert _upload(api, data=b"").status_code == 400


def test_after_ingest_the_whole_text_is_kept_as_content(api):
    demand_id = _upload(api).json()["id"]
    _ingest(api)
    detail = api.client.get(f"{BASE}/{demand_id}", headers=ADMIN).json()
    assert detail["status"] == "ready"
    assert detail["content"] == {"text": TXT.decode().strip()}
    assert len(api.client.get(BASE, headers=ADMIN).json()) == 1


def test_an_unreadable_file_is_marked_failed_with_a_fixed_message(api):
    demand_id = _upload(api, name="d.pdf", data=b"%PDF-1.7\n").json()["id"]
    _ingest(api)
    detail = api.client.get(f"{BASE}/{demand_id}", headers=ADMIN).json()
    assert detail["status"] == "failed"
    assert detail["error"] == "the file could not be read"


def test_a_docx_demand_is_read_as_markdown(api):
    data = make_docx(
        [("Project", "Billing modernisation.")], table=[["Role", "Number"], ["Developer", "2"]]
    )
    demand_id = _upload(api, name="d.docx", data=data).json()["id"]
    _ingest(api)
    detail = api.client.get(f"{BASE}/{demand_id}", headers=ADMIN).json()
    assert detail["status"] == "ready"
    text = detail["content"]["text"]
    assert "## Project" in text and "| Role | Number |" in text


def test_a_text_pdf_demand_is_read_with_page_markers(api):
    data = make_text_pdf([["Project", "", "The release is due in ten days."]])
    demand_id = _upload(api, name="d.pdf", data=data).json()["id"]
    _ingest(api)
    detail = api.client.get(f"{BASE}/{demand_id}", headers=ADMIN).json()
    assert detail["status"] == "ready"
    assert detail["content"]["text"].startswith("<!-- page 1 -->")
    assert "ten days" in detail["content"]["text"]


def test_the_sample_demand_document_ingests(api):
    data = (SAMPLES / "demand" / "project_demand.txt").read_bytes()
    demand_id = _upload(api, data=data, name="project_demand.txt").json()["id"]
    _ingest(api)
    detail = api.client.get(f"{BASE}/{demand_id}", headers=ADMIN).json()
    assert detail["status"] == "ready"
    assert "ten days" in detail["content"]["text"]


def test_a_new_chat_uses_the_newest_ready_demand(api):
    publish_sample_settings(api.client)
    old = ready_demand(api, minutes_ago=10)
    new = ready_demand(api)
    started = api.client.post(
        "/api/v1/sessions", headers=ANNA,
        json={"persona_key": "verma-strict", "profile_id": ready_profile(api)},
    )
    assert started.status_code == 201
    assert started.json()["demand_id"] == new != old


def test_a_queued_demand_is_not_used_for_chats(api):
    publish_sample_settings(api.client)
    _upload(api)  # still queued
    started = api.client.post(
        "/api/v1/sessions", headers=ANNA,
        json={"persona_key": "verma-strict", "profile_id": ready_profile(api)},
    )
    assert started.status_code == 409


def test_delete_removes_the_row_and_the_file(api):
    demand_id = _upload(api).json()["id"]
    with api.factory() as db:
        uri = db.get(m.DemandDocument, UUID(demand_id)).blob_uri
    assert api.client.delete(f"{BASE}/{demand_id}", headers=ANNA).status_code == 403
    assert api.client.delete(f"{BASE}/{demand_id}", headers=ADMIN).status_code == 204
    with api.factory() as db:
        assert db.scalars(select(m.DemandDocument)).all() == []
    with pytest.raises(FileNotFoundError):
        api.store.read(uri)
    assert api.client.get(f"{BASE}/{demand_id}", headers=ADMIN).status_code == 404


def test_a_demand_used_by_a_session_cannot_be_deleted(api):
    publish_sample_settings(api.client)
    demand_id = ready_demand(api)
    started = api.client.post(
        "/api/v1/sessions", headers=ANNA,
        json={"persona_key": "verma-strict", "profile_id": ready_profile(api)},
    )
    assert started.status_code == 201
    assert api.client.delete(f"{BASE}/{demand_id}", headers=ADMIN).status_code == 409
