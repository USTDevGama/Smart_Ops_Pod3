"""The real engine inside the real chat service, with a scripted model instead of a live one."""

import json
from uuid import uuid4

import pytest

from app.agent.drafts import ReplyDraft
from app.api.deps import get_llm
from app.config import get_settings
from app.llm import FakeLLM
from app.main import app
from tests.agent_fixtures import STRONG_ANSWER, WEAK_ANSWER, draft
from tests.conftest import ADMIN, ANNA, load_sample, publish_sample_settings

START = {"persona_key": "verma-strict", "scenario_key": "vendor-delay"}
CHECKLIST = load_sample("scenarios/vendor_delay.json")["scenarios"][0]["good_answer_contains"]


@pytest.fixture
def chat(api, monkeypatch):
    """A session service whose engine is the real LLMTurnEngine, fed by `fake`."""
    publish_sample_settings(api.client)
    monkeypatch.setenv("PODC_LLM_PROVIDER", "scripted")  # anything but "fake" selects the engine
    get_settings.cache_clear()

    def script(replies: dict) -> FakeLLM:
        fake = FakeLLM(replies)
        app.dependency_overrides[get_llm] = lambda: fake
        return fake

    yield api, script
    app.dependency_overrides.pop(get_llm, None)
    get_settings.cache_clear()


def _send(api, session_id, text):
    response = api.client.post(
        f"/api/v1/sessions/{session_id}/turns",
        headers=ANNA | {"Idempotency-Key": str(uuid4())},
        json={"content": text},
    )
    events = {}
    for block in response.text.strip().split("\n\n"):
        name, data = block.split("\n")
        events[name.removeprefix("event: ")] = json.loads(data.removeprefix("data: "))
    return response, events


def test_a_conversation_runs_end_to_end_with_levels_decided_by_the_rules(chat):
    api, script = chat
    fake = script(
        {
            "opening": [ReplyDraft(reply="When were you going to tell me about the delay?")],
            "turn": [
                draft(answer_quality=0.2, proposed_level=2),  # weak
                draft(answer_quality=0.9, quote="commits to 9 June", proposed_level=2,
                      checklist_met=[1, 2], reply="Better. Who pays for the delay?"),
                draft(answer_quality=0.9, quote="commits to 9 June", proposed_level=1,
                      checklist_met=[1],  # open items are now 3 and 4, renumbered 1 and 2
                      reply="Fine. What changes so this does not repeat?"),
            ],
        }
    )

    started = api.client.post("/api/v1/sessions", headers=ANNA, json=START)
    assert started.status_code == 201
    session = started.json()
    assert session["turns"][0]["content"] == "When were you going to tell me about the delay?"

    _, first = _send(api, session["id"], WEAK_ANSWER)
    assert first["message"]["content"] == "Options is not a plan. Give me a date."
    assert first["done"]["level"] == 2  # weak answer: one step tougher

    _, second = _send(api, session["id"], STRONG_ANSWER)
    assert second["done"]["level"] == 2  # one good answer after a weak one: no easing off

    _, third = _send(api, session["id"], STRONG_ANSWER)
    assert third["done"]["level"] == 1  # two good answers in a row: one step easier

    detail = api.client.get(f"/api/v1/sessions/{session['id']}", headers=ADMIN).json()
    trainee_rows = [t for t in detail["turns"] if t["role"] == "trainee"]
    assert [round(t["evaluation"]["answer_quality"], 1) for t in trainee_rows] == [0.2, 0.9, 0.9]
    assert trainee_rows[1]["evaluation"]["checklist_met"] == CHECKLIST[:2]  # real item texts
    assert trainee_rows[1]["evaluation"]["quote"] == "commits to 9 June"
    assert [c.purpose for c in fake.calls] == ["opening", "turn", "turn", "turn"]


def test_a_failing_model_gives_502_and_the_trainee_keeps_the_turn(chat):
    api, script = chat
    script({"opening": [ReplyDraft(reply="Why so late?")], "turn": ["not json at all"]})
    session = api.client.post("/api/v1/sessions", headers=ANNA, json=START).json()

    response = api.client.post(
        f"/api/v1/sessions/{session['id']}/turns",
        headers=ANNA | {"Idempotency-Key": "k1"},
        json={"content": WEAK_ANSWER},
    )
    assert response.status_code == 502
    after = api.client.get(f"/api/v1/sessions/{session['id']}", headers=ANNA).json()
    assert after["turns_used"] == 0 and len(after["turns"]) == 1  # nothing was saved
