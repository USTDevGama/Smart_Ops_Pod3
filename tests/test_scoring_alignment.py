"""A real chat (agent engine + chat service) flowing through scoring and into the report.

The agent's saved rows go in at one end; the assessment job and the report are the other end. The
scoring model is scripted with the sample output. Everything here is made up: the repo is public.
"""

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.api.deps import get_llm
from app.db import models as m
from app.llm import FakeLLM
from app.scoring.pipeline import (
    ASSESSMENT_FILE,
    AssessmentNotReadyError,
    blob_key,
    render_report,
    report_ready,
    run_assessment,
)
from tests.agent_fixtures import STRONG, opening_json, turn_json
from tests.conftest import ANNA, load_sample, publish_sample_settings, ready_demand, ready_profile

ANSWERS = 4


@pytest.fixture
def ended_chat(api, monkeypatch):
    """A four-answer chat run through the real engine and service, then ended by the trainee."""
    monkeypatch.setattr(
        "app.agent.engine.get_settings", lambda: SimpleNamespace(llm_provider="scripted")
    )
    publish_sample_settings(api.client)
    ready_demand(api)
    script = {"opening": [opening_json()], "turn": [turn_json() for _ in range(ANSWERS)]}
    agent_llm = FakeLLM(script)  # one instance, so the scripted replies are handed out in order
    api.client.app.dependency_overrides[get_llm] = lambda: agent_llm

    body = {"persona_key": "verma-strict", "profile_id": ready_profile(api, "anna")}
    session_id = api.client.post("/api/v1/sessions", headers=ANNA, json=body).json()["id"]
    for _ in range(ANSWERS):
        sent = api.client.post(
            f"/api/v1/sessions/{session_id}/turns",
            headers=ANNA | {"Idempotency-Key": str(uuid4())},
            json={"content": STRONG},
        )
        assert sent.status_code == 200, sent.text
    assert api.client.post(f"/api/v1/sessions/{session_id}/end", headers=ANNA).status_code == 200
    return api, UUID(session_id)


def _scoring_llm() -> FakeLLM:
    return FakeLLM({"score": [load_sample("results/llm_output.json")]})


def test_ending_the_chat_queues_one_assessment_job_with_the_id_only(ended_chat):
    api, session_id = ended_chat

    assert api.queued_assessment == [session_id]


def test_the_job_scores_the_real_chat_and_saves_one_snapshot(ended_chat):
    api, session_id = ended_chat
    with api.factory() as db:
        assessment = run_assessment(db, session_id, _scoring_llm(), api.store)

    assert assessment.overall_score == pytest.approx(47.5)  # 0.5/0.7/0.4/0.2 at 25/30/25/20
    assert assessment.handled == "partly"  # 47.5 is between the 40 and 70 cutoffs
    assert [c.id for c in assessment.criteria] == ["C1", "C2", "C3", "C4"]

    snapshot = json.loads(api.store.read(blob_key(session_id, ASSESSMENT_FILE)))
    assert snapshot["scoring_output"]["criteria"][0]["id"] == "C1"  # what the model said
    assert set(snapshot["signals"]) == {"1", "2", "3", "4"}  # one entry per trainee answer
    assert set(snapshot["question_validity"]) == {"1", "2", "3", "4", "5"}
    assert snapshot["grounding_documents_found"] is True


def test_the_report_is_written_from_the_snapshot_and_needs_no_scenario(ended_chat):
    api, session_id = ended_chat
    with api.factory() as db:
        run_assessment(db, session_id, _scoring_llm(), api.store)
        assert not report_ready(api.store, session_id)
        render_report(db, session_id, api.store)

    assert report_ready(api.store, session_id)
    markdown = api.store.read(blob_key(session_id, "report.md")).decode()
    assert "Overall score: **47.5 / 100**" in markdown
    assert "Scenario" not in markdown
    assert "### Turn 5" in markdown  # the unanswered last client message is in the transcript
    assert api.store.read(blob_key(session_id, "report.pdf")).startswith(b"%PDF-")


def test_running_the_job_twice_overwrites_instead_of_piling_up(ended_chat):
    api, session_id = ended_chat
    with api.factory() as db:
        run_assessment(db, session_id, _scoring_llm(), api.store)
        run_assessment(db, session_id, _scoring_llm(), api.store)

    files = [p for p in (api.store.root / "reports" / str(session_id)).iterdir()]
    assert [p.name for p in files] == [ASSESSMENT_FILE]


def test_rendering_before_scoring_is_refused(ended_chat):
    api, session_id = ended_chat
    with api.factory() as db, pytest.raises(AssessmentNotReadyError, match="not been saved"):
        render_report(db, session_id, api.store)


def test_a_missing_resume_and_demand_still_scores_without_the_grounding_check(ended_chat):
    api, session_id = ended_chat
    with api.factory() as db:
        session = db.get(m.RoleplaySession, session_id)
        session.profile_id = None
        session.demand_id = None
        db.commit()
        assessment = run_assessment(db, session_id, _scoring_llm(), api.store)

    snapshot = json.loads(api.store.read(blob_key(session_id, ASSESSMENT_FILE)))
    assert snapshot["grounding_documents_found"] is False
    assert assessment.overall_score == pytest.approx(47.5)


