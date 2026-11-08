"""The real engine behind the real chat service, with a scripted model instead of a provider."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agent.engine import get_engine
from app.agent.llm_engine import LLMTurnEngine
from app.agent.placeholder import PlaceholderEngine
from app.api.deps import get_llm
from app.llm import FakeLLM
from tests.agent_fixtures import STRONG, opening_json, turn_json
from tests.conftest import ADMIN, ANNA, publish_sample_settings, ready_demand, ready_profile

ITEM_2 = "gives a specific new date and who committed to it"


@pytest.fixture
def real_agent(api, monkeypatch):
    """The app with a non-fake provider (so the real engine is used) and a scripted model."""
    monkeypatch.setattr(
        "app.agent.engine.get_settings", lambda: SimpleNamespace(llm_provider="scripted")
    )
    publish_sample_settings(api.client)
    ready_demand(api)

    def use(script):
        fake = FakeLLM(script)
        api.client.app.dependency_overrides[get_llm] = lambda: fake
        return fake

    return api, use


def _start(api):
    body = {"persona_key": "verma-strict", "profile_id": ready_profile(api, "anna")}
    return api.client.post("/api/v1/sessions", headers=ANNA, json=body)


def _send(api, session_id, text=STRONG, key=None):
    return api.client.post(
        f"/api/v1/sessions/{session_id}/turns",
        headers=ANNA | {"Idempotency-Key": key or str(uuid4())},
        json={"content": text},
    )


def _events(response) -> dict:
    found = {}
    for block in response.text.strip().split("\n\n"):
        name, data = block.split("\n")
        found[name.removeprefix("event: ")] = json.loads(data.removeprefix("data: "))
    return found


def _detail(api, session_id, headers=ANNA):
    return api.client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()


def test_the_client_opens_through_the_real_engine_and_is_saved_at_level_one(real_agent):
    api, use = real_agent
    fake = use({"opening": [opening_json(reply="When were you going to tell me?")]})
    started = _start(api)
    assert started.status_code == 201
    turns = started.json()["turns"]
    assert [(t["idx"], t["role"], t["escalation_level"]) for t in turns] == [(0, "persona", 1)]
    assert turns[0]["content"] == "When were you going to tell me?"
    assert len(fake.calls) == 1


def test_a_turn_saves_the_judgement_the_quote_and_the_level_the_model_proposed(real_agent):
    api, use = real_agent
    use(
        {
            "opening": [opening_json()],
            "turn": [turn_json(proposed_level=2, reply="And who pays for it?")],
        }
    )
    session_id = _start(api).json()["id"]
    events = _events(_send(api, session_id))
    assert events["message"]["content"] == "And who pays for it?"
    assert events["done"]["level"] == 2
    assert events["done"]["turns_used"] == 1

    saved = _detail(api, session_id, headers=ADMIN)["turns"]
    assert [t["role"] for t in saved] == ["persona", "trainee", "persona"]
    evaluation = saved[1]["evaluation"]
    assert evaluation["quote"] == "commits to 9 June"
    assert evaluation["quote"] in saved[1]["content"]  # the exact words the trainee wrote
    assert evaluation["checklist_met"] == [ITEM_2]
    assert saved[2]["escalation_level"] == 2


def test_the_model_is_given_the_demand_the_profile_and_every_scenario(real_agent):
    api, use = real_agent
    fake = use({"opening": [opening_json()], "turn": [turn_json()]})
    session_id = _start(api).json()["id"]
    _send(api, session_id)
    for call in fake.calls:
        content = call.messages[0].content
        assert "invoicing release is due in ten days" in content
        assert "billing rewrite" in content
        assert "[VD-01]" in content
    assert "billing rewrite" not in fake.calls[1].system


def test_a_turn_costs_one_model_call_and_the_opening_one(real_agent):
    api, use = real_agent
    fake = use({"opening": [opening_json()], "turn": [turn_json(), turn_json(proposed_level=1)]})
    session_id = _start(api).json()["id"]
    _send(api, session_id)
    _send(api, session_id)
    assert [c.purpose for c in fake.calls] == ["opening", "turn", "turn"]


def test_a_reply_the_agent_cannot_stand_behind_saves_nothing_and_can_be_retried(real_agent):
    api, use = real_agent
    fake = use(
        {
            "opening": [opening_json()],
            "turn": [
                turn_json(quote="words the trainee never wrote"),
                turn_json(quote="more words the trainee never wrote"),
                turn_json(),  # used by the second send
            ],
        }
    )
    session_id = _start(api).json()["id"]
    failed = _send(api, session_id, key="k1")
    assert failed.status_code == 502
    assert len(_detail(api, session_id)["turns"]) == 1  # nothing saved, the turn is not used up
    assert _detail(api, session_id)["turns_used"] == 0
    retried = _send(api, session_id, key="k1")
    assert retried.status_code == 200
    assert len(_detail(api, session_id)["turns"]) == 3
    assert [c.purpose for c in fake.calls] == ["opening", "turn", "turn", "turn"]


def test_a_model_that_asks_for_too_big_a_jump_never_gets_the_jump_saved(real_agent):
    api, use = real_agent
    use({"opening": [opening_json()], "turn": [turn_json(proposed_level=4)] * 2})
    session_id = _start(api).json()["id"]
    assert _send(api, session_id).status_code == 502  # level 1 -> 4 is refused by the agent
    assert len(_detail(api, session_id)["turns"]) == 1


def test_get_engine_uses_the_placeholder_for_the_fake_provider_and_the_real_engine_otherwise(
    monkeypatch,
):
    llm = FakeLLM()
    for provider, expected in (("fake", PlaceholderEngine), ("anything-else", LLMTurnEngine)):
        monkeypatch.setattr(
            "app.agent.engine.get_settings", lambda p=provider: SimpleNamespace(llm_provider=p)
        )
        assert isinstance(get_engine(llm), expected)
