"""A real chat (agent engine + chat service) flowing through scoring and into the report.

The agent's saved rows go in at one end; Disha's `load_report_data` is the other end. The scoring
model is scripted with her sample output. Everything here is made up: the repo is public.
"""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.api.deps import get_llm
from app.db import models as m
from app.llm import FakeLLM
from app.reports.generator import ReportDataError, load_report_data, render_markdown
from app.schemas import ScoringConfig
from app.schemas.enums import ConfigKind
from app.scoring import ScoringValidationContext, build_assessment
from app.scoring.scorer import score_session
from app.scoring.transcript import build_transcript
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


def _score(db, session_id):
    rows = list(
        db.scalars(select(m.Turn).where(m.Turn.session_id == session_id).order_by(m.Turn.idx))
    )
    transcript = build_transcript(rows)
    config = ScoringConfig.model_validate(load_sample("scoring/default.json"))
    llm = FakeLLM({"score": [load_sample("results/llm_output.json")]})
    output = score_session(llm, config, transcript)
    validation = ScoringValidationContext(
        client_exchange_numbers=transcript.client_numbers,
        trainee_exchange_numbers=transcript.trainee_numbers,
        question_validity=dict.fromkeys(transcript.client_numbers, True),
        trainee_signals={n: set() for n in transcript.trainee_numbers},
    )
    return transcript, build_assessment(output, config, validation, handled="partly")


def test_saved_rows_become_the_exchanges_the_scorer_and_the_validation_context_expect(ended_chat):
    api, session_id = ended_chat
    with api.factory() as db:
        transcript, assessment = _score(db, session_id)

    assert transcript.trainee_numbers == {1, 2, 3, 4}
    assert transcript.client_numbers == {1, 2, 3, 4, 5}  # the last client message is unanswered
    assert len(assessment.criteria) == 4


@pytest.mark.xfail(
    strict=True,
    raises=ReportDataError,
    reason="the agent chooses the scenario but nothing saves it: session.scenario_version_id is "
    "empty, and the report needs it for scenario_id and title (see docs/agent-architecture.md)",
)
def test_the_report_loads_for_a_session_made_by_the_real_chat_path(ended_chat):
    api, session_id = ended_chat
    with api.factory() as db:
        _, assessment = _score(db, session_id)
        data = load_report_data(db, session_id, assessment)

    assert "VD-01" in render_markdown(data)


def test_everything_else_in_the_report_loader_accepts_the_agents_rows(ended_chat):
    """Same session, but with the scenario saved by hand: the only thing the chat path lacks."""
    api, session_id = ended_chat
    with api.factory() as db:
        scenario = db.scalars(
            select(m.ConfigVersion).where(m.ConfigVersion.kind == ConfigKind.SCENARIO)
        ).one()
        db.get(m.RoleplaySession, session_id).scenario_version_id = scenario.id
        db.commit()
        _, assessment = _score(db, session_id)
        data = load_report_data(db, session_id, assessment)
        markdown = render_markdown(data)

    assert data.scenario_id == "VD-01"
    assert data.escalation_peak == 1  # the scripted client stayed at level 1
    assert [e.turn for e in data.transcript] == [1, 2, 3, 4, 5]
    assert "Scenario: VD-01" in markdown and "### Turn 5" in markdown
