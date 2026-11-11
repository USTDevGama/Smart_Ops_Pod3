"""The Streamlit pages, run headlessly against the real API (in memory).

Skipped when Streamlit is not installed (it is in the optional `ui` dependency group).
"""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from app.api import reports as reports_api  # noqa: E402
from tests.ui.support import clients, output, stage, write_report  # noqa: E402
from ui.persona_form import default_persona  # noqa: E402

UI = Path(__file__).resolve().parents[2] / "ui"

# Starlette's test client warns about the short timeout the client puts on status calls.
pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")


def page(name: str, client) -> AppTest:
    """A page of the app as one user sees it. `client` is that user's connection to the API."""
    # A generous timeout: the first run in a process also imports Streamlit and pandas.
    at = AppTest.from_file(str(UI / "views" / name), default_timeout=90)
    at.session_state["_client"] = client
    return at


def texts(elements) -> str:
    return " ".join(str(e.value) for e in elements)


def app(client, role: str, monkeypatch) -> AppTest:
    """The whole app (login sidebar and navigation), signed in with this role."""
    # The sidebar asks /readyz, which would try the default Postgres: there is none in tests.
    monkeypatch.setattr("app.db.session.check_database", lambda: True)
    at = AppTest.from_file(str(UI / "streamlit_app.py"), default_timeout=90)
    at.session_state["_client_override"] = client
    at.run()
    if role != "trainee":
        at.sidebar.selectbox[0].select(role).run()
    return at


def test_a_trainee_lands_on_the_resume_page(api, monkeypatch):
    _, anna = clients(api)
    at = app(anna, "trainee", monkeypatch)

    assert not at.exception
    assert at.header[0].value == "My resume"
    assert "API reachable" in texts(at.sidebar.caption)


def test_switching_to_the_admin_role_keeps_the_app_working(api, monkeypatch):
    admin, _ = clients(api)
    at = app(admin, "admin", monkeypatch)

    assert not at.exception
    assert at.sidebar.selectbox[0].value == "admin"  # the admin pages are now in the navigation


def test_the_resume_page_lists_a_ready_resume(api):
    _, anna, _ = stage(api)
    at = page("trainee_profile.py", anna).run()

    assert not at.exception
    assert at.header[0].value == "My resume"
    assert any("resume.txt" in e.label for e in at.expander)


def test_the_resume_page_with_nothing_uploaded_says_so(api):
    _, anna = clients(api)
    at = page("trainee_profile.py", anna).run()
    assert not at.exception
    assert "not uploaded a resume" in texts(at.info)


def test_starting_a_chat_shows_the_clients_opening_line(api, engine):
    _, anna, _ = stage(api)
    engine([output()])

    at = page("trainee_chat.py", anna).run()
    assert not at.exception
    assert [b.label for b in at.button] == ["Start the chat", "Open"] or "Start the chat" in [
        b.label for b in at.button
    ]
    next(b for b in at.button if b.label == "Start the chat").click()
    at.run()

    assert not at.exception
    assert len(at.chat_message) == 1  # the client speaks first
    assert "When were you going to tell me?" in texts(at.chat_message[0].markdown)
    assert at.chat_input  # and Anna can answer


def test_an_answer_gets_a_reply_and_the_counters_move(api, engine):
    _, anna, _ = stage(api)
    engine([output(level=2, reply="Options is not a plan.")])

    at = page("trainee_chat.py", anna).run()
    next(b for b in at.button if b.label == "Start the chat").click()
    at.run()
    at.chat_input[0].set_value("We are looking at options.").run()

    assert not at.exception
    assert len(at.chat_message) == 3  # opening, Anna's answer, the reply
    assert "Options is not a plan." in texts(at.chat_message[2].markdown)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Client mood"] == "Level 2 of 4"
    assert metrics["Your messages"].startswith("1 of")


def test_a_failed_reply_keeps_the_message_and_offers_to_send_it_again(api, engine):
    _, anna, _ = stage(api)
    engine([RuntimeError("agent crashed"), output(reply="Now it works.")])

    at = page("trainee_chat.py", anna).run()
    next(b for b in at.button if b.label == "Start the chat").click()
    at.run()
    at.chat_input[0].set_value("Here is my answer.").run()

    assert not at.exception
    assert "did not go through" in texts(at.warning)
    again = next(b for b in at.button if b.label == "Send it again")

    again.click()
    at.run()

    assert not at.warning or "did not go through" not in texts(at.warning)
    assert "Now it works." in texts(m for c in at.chat_message for m in c.markdown)


def test_an_ended_chat_cannot_be_written_to(api, engine):
    persona = default_persona() | {"min_turns": 1, "max_turns": 1, "grace_turns": 0}
    _, anna, _ = stage(api, persona=persona)
    engine([output()])

    at = page("trainee_chat.py", anna).run()
    next(b for b in at.button if b.label == "Start the chat").click()
    at.run()
    at.chat_input[0].set_value("My only answer.").run()

    assert not at.exception
    assert "ended" in texts(at.info)
    assert not at.chat_input


def test_the_chat_page_says_what_is_missing(api):
    _, anna = clients(api)
    at = page("trainee_chat.py", anna).run()
    assert not at.exception
    warnings = texts(at.warning)
    assert "No client is published" in warnings and "no ready resume" in warnings


def test_the_admin_can_publish_a_draft_card(api):
    admin, _ = clients(api)
    admin.create_persona("verma-strict", default_persona())

    at = page("admin_setup.py", admin).run()
    assert not at.exception
    assert at.header[0].value == "Set the stage"
    publish = next(b for b in at.button if b.label == "Publish this version")
    publish.click()
    at.run()

    assert not at.exception
    statuses = {v["version_no"]: v["status"] for v in admin.list_keys("persona")[0]["versions"]}
    assert statuses == {1: "published"}


def test_the_admin_sees_the_loaded_situations_and_the_demand_in_use(api):
    admin, _, _ = stage(api)
    at = page("admin_setup.py", admin).run()

    assert not at.exception
    assert any("IN USE" in e.label for e in at.expander)  # the demand document
    assert any(
        "Vendor late with a component" in str(row) for df in at.dataframe for row in df.value.values
    )


def test_the_review_page_shows_the_score_notes_to_an_admin(api, engine):
    admin, anna, profile_id = stage(api)
    engine([output()])
    session = anna.start_session("verma-strict", profile_id)
    anna.send_turn(session["id"], "My answer", "t-1")

    at = page("sessions_review.py", admin).run()

    assert not at.exception
    assert at.header[0].value == "Review chats"
    assert any("Score notes" in e.label for e in at.expander)


# --- the report of an ended chat ------------------------------------------------------------------


def click(at: AppTest, label: str) -> None:
    next(b for b in at.button if b.label == label).click()
    at.run()


def end_by_hand(api, engine, anna, monkeypatch) -> tuple[AppTest, list[str]]:
    """Anna starts a chat in the page and ends it with the button. Returns the page and the
    session ids the page asked the API to make a report for."""
    engine([output()])
    asked: list[str] = []
    real = anna.request_report
    monkeypatch.setattr(anna, "request_report", lambda sid: (asked.append(sid), real(sid))[1])

    at = page("trainee_chat.py", anna).run()
    click(at, "Start the chat")
    click(at, "End the chat")
    return at, asked


def downloads(at: AppTest) -> list[str]:
    return [b.proto.label for b in at.get("download_button")]


def test_ending_a_chat_by_hand_asks_for_its_report(api, engine, monkeypatch):
    _, anna, _ = stage(api)
    at, asked = end_by_hand(api, engine, anna, monkeypatch)

    assert not at.exception
    assert "This chat has ended" in texts(at.info)
    assert "Report" in [s.value for s in at.subheader]
    assert asked == [anna.list_sessions()[0]["id"]]  # asked once, for this chat


def test_without_a_model_the_page_says_what_to_configure(api, engine, monkeypatch):
    _, anna, _ = stage(api)
    at, _ = end_by_hand(api, engine, anna, monkeypatch)  # the default provider is the fake one

    assert "needs a scoring model" in texts(at.warning)
    assert "PODC_LLM_PROVIDER" in texts(at.warning)


def test_a_report_still_being_made_shows_progress_and_is_not_started_twice(
    api, engine, monkeypatch
):
    monkeypatch.setattr(reports_api, "_model_configured", lambda: True)
    sent: list = []
    monkeypatch.setattr(reports_api, "send_assessment", sent.append)
    _, anna, _ = stage(api)

    at, asked = end_by_hand(api, engine, anna, monkeypatch)

    assert "being generated" in texts(at.info)
    assert len(asked) == 1
    assert sent == []  # the chat's own end already queued the job: no second one


def test_a_trainee_is_told_the_report_exists_but_cannot_download_it(api, engine, monkeypatch):
    _, anna, _ = stage(api)
    at, _ = end_by_hand(api, engine, anna, monkeypatch)
    write_report(api, anna.list_sessions()[0]["id"])

    at.run()

    assert not at.exception
    assert "has gone to an admin for review" in texts(at.success)
    assert downloads(at) == []


def test_an_admin_sees_the_download_buttons_when_the_report_is_ready(api, engine):
    admin, anna, profile_id = stage(api)
    engine([output()])
    session = anna.start_session("verma-strict", profile_id)
    anna.end_session(session["id"])
    write_report(api, session["id"])

    at = page("sessions_review.py", admin).run()

    assert not at.exception
    assert "The report is ready." in texts(at.success)
    assert downloads(at) == ["Download PDF", "Download HTML", "Download Markdown"]


def test_browsing_chats_does_not_start_report_jobs(api, engine, monkeypatch):
    monkeypatch.setattr(reports_api, "_model_configured", lambda: True)
    sent: list = []
    monkeypatch.setattr(reports_api, "send_assessment", sent.append)
    admin, anna, profile_id = stage(api)
    engine([output()])
    session = anna.start_session("verma-strict", profile_id)
    anna.end_session(session["id"])
    asked: list = []
    monkeypatch.setattr(admin, "request_report", lambda sid: asked.append(sid))

    at = page("sessions_review.py", admin).run()

    assert not at.exception
    assert "being generated" in texts(at.info)
    assert asked == [] and sent == []  # only the "Generate it again" button asks


def test_a_chat_still_going_has_no_report_panel_in_the_review(api, engine):
    admin, anna, profile_id = stage(api)
    engine([output()])
    anna.start_session("verma-strict", profile_id)

    at = page("sessions_review.py", admin).run()

    assert not at.exception
    assert "Report" not in [s.value for s in at.subheader]
