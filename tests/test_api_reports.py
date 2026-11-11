"""The report endpoints: status, make sure it is generated, and the admin download."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.api import reports as reports_api
from app.db import models as m
from tests.conftest import (
    ADMIN,
    ANNA,
    BEN,
    publish_sample_settings,
    ready_demand,
    ready_profile,
)

PDF = b"%PDF-1.4 a made-up report"
FILES = {"pdf": PDF, "html": b"<html>report</html>", "md": b"# Report\n\nOverall score: 47.5"}


def start(api, headers=ANNA, persona_overrides=None, set_up=True) -> str:
    if set_up:  # once per test: the persona key and the demand document are published once
        publish_sample_settings(api.client, persona_overrides)
        ready_demand(api)
    body = {
        "persona_key": "verma-strict",
        "profile_id": ready_profile(api, headers["X-Dev-User"]),
    }
    created = api.client.post("/api/v1/sessions", headers=headers, json=body)
    assert created.status_code == 201, created.text
    return created.json()["id"]


def end(api, session_id: str, headers=ANNA) -> None:
    assert api.client.post(f"/api/v1/sessions/{session_id}/end", headers=headers).status_code == 200


def ended(api) -> str:
    session_id = start(api)
    end(api, session_id)
    return session_id


def write_report(api, session_id: str) -> None:
    for fmt, data in FILES.items():
        api.store.save(data, name=f"reports/{session_id}/{reports_api.FORMATS[fmt][0]}")


def age(api, session_id: str, minutes: int) -> None:
    """Pretend the chat ended `minutes` ago."""
    with api.factory() as db:
        db.get(m.RoleplaySession, UUID(session_id)).ended_at = datetime.now(UTC) - timedelta(
            minutes=minutes
        )
        db.commit()


@pytest.fixture
def model(monkeypatch):
    """A scoring model is configured (without it a report can never be made)."""
    monkeypatch.setattr(reports_api, "_model_configured", lambda: True)


@pytest.fixture
def sent(monkeypatch):
    """The report jobs the API sends, as session ids."""
    jobs: list = []
    monkeypatch.setattr(reports_api, "send_assessment", jobs.append)
    return jobs


def status(api, session_id, headers=ANNA):
    return api.client.get(f"/api/v1/sessions/{session_id}/report", headers=headers)


def ask(api, session_id, headers=ANNA):
    return api.client.post(f"/api/v1/sessions/{session_id}/report", headers=headers)


# --- the file names match what the job writes ---------------------------------------------------


def test_the_file_names_match_the_ones_the_job_writes():
    from app.scoring.pipeline import REPORT_FILES, blob_key

    names = {fmt: spec[0] for fmt, spec in reports_api.FORMATS.items()}
    assert names == {
        "pdf": REPORT_FILES["pdf"],
        "html": REPORT_FILES["html"],
        "md": REPORT_FILES["markdown"],
    }
    assert reports_api._key("abc", "pdf") == blob_key("abc", REPORT_FILES["pdf"])


# --- status -------------------------------------------------------------------------------------


def test_a_chat_still_going_has_no_report_yet(api):
    body = status(api, start(api)).json()
    assert body["state"] == "not_ended"
    assert body["can_download"] is False and body["formats"] == []


def test_an_ended_chat_without_a_report_is_generating(api):
    body = status(api, ended(api)).json()
    assert body["state"] == "generating"
    assert body["can_download"] is False


def test_the_model_flag_says_when_no_report_can_ever_appear(api, model):
    session_id = ended(api)
    assert status(api, session_id).json()["model_configured"] is True


def test_without_a_model_the_status_says_so(api):
    assert status(api, ended(api)).json()["model_configured"] is False  # the fake provider


def test_a_ready_report_can_be_downloaded_by_admins_but_not_trainees(api):
    session_id = ended(api)
    write_report(api, session_id)

    owner = status(api, session_id).json()
    admin = status(api, session_id, ADMIN).json()

    assert owner["state"] == admin["state"] == "ready"
    assert owner["can_download"] is False and owner["formats"] == []
    assert admin["can_download"] is True and admin["formats"] == ["pdf", "html", "md"]


def test_other_trainees_cannot_even_see_the_status(api):
    session_id = ended(api)
    assert status(api, session_id, BEN).status_code == 404
    assert status(api, "00000000-0000-0000-0000-000000000000").status_code == 404


def test_the_status_needs_a_login(api):
    assert api.client.get(f"/api/v1/sessions/{ended(api)}/report").status_code == 401


# --- making sure the report is generated ----------------------------------------------------------


def test_a_chat_that_has_not_ended_cannot_have_a_report_requested(api, model, sent):
    response = ask(api, start(api))
    assert response.status_code == 409 and "not ended" in response.json()["detail"]
    assert sent == []


def test_a_ready_report_is_left_alone(api, model, sent):
    session_id = ended(api)
    write_report(api, session_id)

    response = ask(api, session_id)

    assert response.status_code == 200
    assert response.json()["state"] == "ready" and response.json()["queued"] is False
    assert sent == []


def test_without_a_model_the_request_says_what_to_configure(api, sent):
    response = ask(api, ended(api))
    assert response.status_code == 409
    assert "PODC_LLM_PROVIDER" in response.json()["detail"]
    assert sent == []


def test_a_job_that_probably_still_runs_is_not_sent_twice(api, model, sent):
    session_id = ended(api)  # it ended a moment ago: the hook's job is queued or running

    response = ask(api, session_id)

    assert response.status_code == 202 and response.json()["queued"] is False
    assert sent == []


def test_a_report_that_never_appeared_is_requested_again(api, model, sent):
    session_id = ended(api)
    age(api, session_id, minutes=10)  # long enough that the first job must have been lost

    response = ask(api, session_id)

    assert response.status_code == 202 and response.json()["queued"] is True
    assert sent == [UUID(session_id)]


def test_the_owner_may_ask_but_another_trainee_may_not(api, model, sent):
    session_id = ended(api)
    age(api, session_id, minutes=10)
    assert ask(api, session_id, BEN).status_code == 404
    assert sent == []
    assert ask(api, session_id, ANNA).status_code == 202


def test_a_queue_that_is_down_is_reported_not_hidden(api, model, monkeypatch):
    def down(session_id):
        raise ConnectionError("redis refused SECRET connection")

    monkeypatch.setattr(reports_api, "send_assessment", down)
    session_id = ended(api)
    age(api, session_id, minutes=10)

    response = ask(api, session_id)

    assert response.status_code == 503
    assert "Redis" in response.json()["detail"] and "SECRET" not in response.text


def test_inline_mode_runs_the_job_in_the_request_and_ignores_the_wait(api, monkeypatch):
    monkeypatch.setattr(
        reports_api, "get_settings", lambda: SimpleNamespace(ingest_inline=True, llm_provider="x")
    )
    session_id = ended(api)  # just ended: a queued job would still be running, an inline one is not

    monkeypatch.setattr(reports_api, "send_assessment", lambda sid: write_report(api, str(sid)))
    response = ask(api, session_id)

    assert response.status_code == 200
    assert response.json()["state"] == "ready" and response.json()["queued"] is True


def test_inline_mode_failure_names_the_error_type_only(api, monkeypatch):
    monkeypatch.setattr(
        reports_api, "get_settings", lambda: SimpleNamespace(ingest_inline=True, llm_provider="x")
    )

    def fails(session_id):
        raise ValueError("SECRET chat text")

    monkeypatch.setattr(reports_api, "send_assessment", fails)
    response = ask(api, ended(api))

    assert response.status_code == 502
    assert "ValueError" in response.json()["detail"] and "SECRET" not in response.text


def test_every_way_a_chat_can_end_starts_the_report_job(api):
    """The report job is queued by the chat's end hook, however the chat ended."""
    manual = start(api)
    end(api, manual)  # the trainee ends it
    assert api.queued_assessment == [UUID(manual)]

    by_admin = start(api, ANNA, set_up=False)
    end(api, by_admin, ADMIN)  # an admin ends someone else's chat
    assert api.queued_assessment[-1] == UUID(by_admin)


def test_the_turn_limit_also_starts_the_report_job(api):
    session_id = start(api, persona_overrides={"min_turns": 1, "max_turns": 1, "grace_turns": 0})

    answered = api.client.post(
        f"/api/v1/sessions/{session_id}/turns",
        headers=ANNA | {"Idempotency-Key": "only-answer"},
        json={"content": "We will fix it by 9 June."},
    )

    assert answered.status_code == 200
    assert '"ended": true' in answered.text  # the chat ended by itself
    assert api.queued_assessment == [UUID(session_id)]
    assert status(api, session_id).json()["state"] == "generating"


# --- downloads ----------------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["pdf", "html", "md"])
def test_an_admin_downloads_each_file(api, fmt):
    session_id = ended(api)
    write_report(api, session_id)

    response = api.client.get(f"/api/v1/admin/sessions/{session_id}/report/{fmt}", headers=ADMIN)

    assert response.status_code == 200
    assert response.content == FILES[fmt]
    assert response.headers["content-type"].startswith(reports_api.FORMATS[fmt][1].split(";")[0])
    assert f'filename="report-{session_id}.{fmt}"' in response.headers["content-disposition"]
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_trainees_cannot_download_even_their_own_report(api):
    session_id = ended(api)
    write_report(api, session_id)
    for headers in (ANNA, BEN):
        response = api.client.get(
            f"/api/v1/admin/sessions/{session_id}/report/pdf", headers=headers
        )
        assert response.status_code == 403


def test_a_report_that_is_not_ready_is_a_404(api):
    session_id = ended(api)
    response = api.client.get(f"/api/v1/admin/sessions/{session_id}/report/pdf", headers=ADMIN)
    assert response.status_code == 404 and "not ready" in response.json()["detail"]


def test_an_unknown_session_or_format_is_refused(api):
    session_id = ended(api)
    write_report(api, session_id)
    unknown = "00000000-0000-0000-0000-000000000000"
    assert (
        api.client.get(f"/api/v1/admin/sessions/{unknown}/report/pdf", headers=ADMIN).status_code
        == 404
    )
    assert (
        api.client.get(f"/api/v1/admin/sessions/{session_id}/report/exe", headers=ADMIN).status_code
        == 422
    )
