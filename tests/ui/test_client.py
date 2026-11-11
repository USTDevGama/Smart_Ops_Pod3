"""The UI's client against the real API (in memory), following the story."""

import httpx
import pytest

from tests.ui.support import clients, output, stage
from ui.client import ApiError, PodCClient, error_detail, parse_sse
from ui.persona_form import default_persona


def test_server_sent_events_are_parsed_in_order():
    text = 'event: message\ndata: {"content": "Hi"}\n\nevent: done\ndata: {"ended": false}\n\n'
    assert parse_sse(text) == [("message", {"content": "Hi"}), ("done", {"ended": False})]


def test_error_text_comes_from_the_apis_standard_shape():
    def reply(status, body):
        return httpx.Response(status, json=body)

    assert error_detail(reply(409, {"title": "Conflict", "detail": "no demand"})) == "no demand"
    assert error_detail(reply(404, {"title": "Not Found"})) == "Not Found"
    listed = reply(422, {"detail": [{"loc": ["body", "config", "name"], "msg": "Field required"}]})
    assert error_detail(listed) == "config.name: Field required"
    assert error_detail(httpx.Response(500, text="boom")).startswith("500")


def test_an_api_validation_error_is_readable(api):
    admin, _ = clients(api)
    bad = default_persona() | {"escalation_ladder": [], "name": ""}
    with pytest.raises(ApiError) as info:
        admin.create_persona("bad-card", bad)
    assert info.value.status == 422
    assert "escalation_ladder" in info.value.detail and not info.value.retryable


def test_a_plain_refusal_carries_the_apis_own_words(api):
    _, anna = clients(api)
    with pytest.raises(ApiError) as info:
        anna.list_keys("persona")  # admins only
    assert info.value.status == 403 and not info.value.retryable


def test_an_unreachable_api_is_a_retryable_error():
    def refuse(request):
        raise httpx.ConnectError("no route")

    client = PodCClient(http=httpx.Client(transport=httpx.MockTransport(refuse)))
    with pytest.raises(ApiError) as info:
        client.meta()
    assert info.value.status == 0 and info.value.retryable
    assert client.ready() is False


def test_the_morning_set_up_and_a_first_message(api, engine):
    admin, anna, profile_id = stage(api)
    engine([output(reply="Options is not a plan. Give me a date.")])

    assert [p["key"] for p in anna.list_personas()] == ["verma-strict"]
    session = anna.start_session("verma-strict", profile_id)
    assert session["turns"][0]["content"] == "When were you going to tell me?"

    from ui.client import new_ticket

    result = anna.send_turn(session["id"], "We are looking at options.", new_ticket())
    assert result.reply["content"].startswith("Options is not a plan")
    assert result.done["turns_used"] == 1 and result.done["replayed"] is False


def test_the_same_ticket_returns_the_saved_reply_and_saves_nothing_new(api, engine):
    _, anna, profile_id = stage(api)
    scripted = engine([output(reply="First reply."), output(reply="Should never be used.")])
    session = anna.start_session("verma-strict", profile_id)

    first = anna.send_turn(session["id"], "My answer", "ticket-1")
    again = anna.send_turn(session["id"], "My answer", "ticket-1")

    assert again.reply["content"] == first.reply["content"] == "First reply."
    assert again.done["replayed"] is True
    assert scripted.calls == 1
    assert len(anna.get_session(session["id"])["turns"]) == 3  # opening, answer, reply


def test_only_admins_see_the_score_notes(api, engine):
    admin, anna, profile_id = stage(api)
    engine([output()])
    session = anna.start_session("verma-strict", profile_id)
    anna.send_turn(session["id"], "My answer", "t-1")

    as_anna = anna.get_session(session["id"])["turns"]
    as_admin = admin.get_session(session["id"])["turns"]
    assert all(t["evaluation"] is None for t in as_anna)
    assert any(t["evaluation"] for t in as_admin)


def test_starting_without_a_ready_demand_says_what_is_missing(api):
    admin, anna = clients(api)
    admin.create_persona("verma-strict", default_persona())
    admin.publish_persona("verma-strict", 1)
    anna.upload_profile("resume.txt", b"Backend engineer.")
    from app.ingest import pipeline

    with api.factory() as db:
        pipeline.ingest_profile(db, api.queued[-1], api.store)
    profile_id = anna.list_profiles()[0]["id"]

    with pytest.raises(ApiError) as info:
        anna.start_session("verma-strict", profile_id)
    assert info.value.status == 409 and "demand" in info.value.detail


def test_the_same_resume_again_is_reported_as_reused(api):
    _, anna = clients(api)
    first = anna.upload_profile("resume.txt", b"Backend engineer.")
    second = anna.upload_profile("resume.txt", b"Backend engineer.")
    assert first.reused is False and second.reused is True
    assert second.row["id"] == first.row["id"]


# --- the report of an ended chat ------------------------------------------------------------------


def test_the_report_status_follows_the_chat(api, engine):
    from tests.ui.support import write_report

    admin, anna, profile_id = stage(api)
    engine([output()])
    session = anna.start_session("verma-strict", profile_id)
    assert anna.report_status(session["id"])["state"] == "not_ended"

    anna.end_session(session["id"])
    assert anna.report_status(session["id"])["state"] == "generating"

    write_report(api, session["id"])
    assert anna.report_status(session["id"]) | {} == {
        "session_id": session["id"],
        "state": "ready",
        "model_configured": False,
        "can_download": False,  # trainees are told it exists, not given the file
        "formats": [],
        "queued": None,
    }
    assert admin.report_status(session["id"])["formats"] == ["pdf", "html", "md"]


def test_only_admins_can_download_the_report(api, engine):
    from tests.ui.support import REPORT_FILES, write_report

    admin, anna, profile_id = stage(api)
    engine([output()])
    session = anna.start_session("verma-strict", profile_id)
    anna.end_session(session["id"])
    write_report(api, session["id"])

    assert admin.download_report(session["id"], "pdf") == REPORT_FILES["pdf"][1]
    assert admin.download_report(session["id"], "md") == REPORT_FILES["md"][1]
    with pytest.raises(ApiError) as info:
        anna.download_report(session["id"], "pdf")
    assert info.value.status == 403 and not info.value.retryable


def test_asking_for_a_report_without_a_model_says_what_to_configure(api, engine):
    _, anna, profile_id = stage(api)
    engine([output()])
    session = anna.start_session("verma-strict", profile_id)
    anna.end_session(session["id"])

    with pytest.raises(ApiError) as info:
        anna.request_report(session["id"])  # the default provider is the fake one
    assert info.value.status == 409 and "PODC_LLM_PROVIDER" in info.value.detail


def test_asking_for_a_report_before_the_chat_ends_is_refused(api, engine):
    _, anna, profile_id = stage(api)
    engine([output()])
    session = anna.start_session("verma-strict", profile_id)

    with pytest.raises(ApiError) as info:
        anna.request_report(session["id"])
    assert info.value.status == 409 and "not ended" in info.value.detail
