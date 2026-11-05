import json
from uuid import uuid4

import pytest

from app.agent.engine import get_engine
from app.ingest import placeholder
from app.main import app
from app.schemas import Evaluation, TurnOutput
from tests.conftest import ADMIN, ANNA, BEN, load_sample, publish_sample_settings

START = {"persona_key": "verma-strict", "scenario_key": "vendor-delay"}
CHECKLIST = load_sample("scenarios/vendor_delay.json")["scenarios"][0]["good_answer_contains"]


def output(quality=0.3, level=2, met=(), refs=(), reply="Be specific."):
    return TurnOutput(
        evaluation=Evaluation(
            answer_quality=quality, checklist_met=list(met), quote="x", proposed_level=level
        ),
        reply=reply,
        refs=list(refs),
    )


class ScriptedEngine:
    """Hands out prepared answers; raises when told to."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.contexts = []

    def opening(self, ctx):
        return output(reply="When were you going to tell me?")

    def respond(self, ctx, answer):
        self.contexts.append(ctx)
        item = self.outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def chat(api):
    publish_sample_settings(api.client)

    def use(outputs):
        engine = ScriptedEngine(outputs)
        app.dependency_overrides[get_engine] = lambda: engine
        return engine

    yield api, use
    app.dependency_overrides.pop(get_engine, None)


def _start(api, headers=ANNA, **extra):
    return api.client.post("/api/v1/sessions", headers=headers, json=START | extra)


def _send(api, session_id, text="We will fix it by 9 June", key=None, headers=ANNA):
    return api.client.post(
        f"/api/v1/sessions/{session_id}/turns",
        headers=headers | {"Idempotency-Key": key or str(uuid4())},
        json={"content": text},
    )


def _events(response) -> dict:
    found = {}
    for block in response.text.strip().split("\n\n"):
        name, data = block.split("\n")
        found[name.removeprefix("event: ")] = json.loads(data.removeprefix("data: "))
    return found


def _get(api, session_id, headers=ANNA):
    return api.client.get(f"/api/v1/sessions/{session_id}", headers=headers)


def test_the_client_speaks_first(chat):
    api, use = chat
    use([])
    started = _start(api)
    assert started.status_code == 201
    body = started.json()
    assert body["status"] == "active"
    assert body["persona"] == {"key": "verma-strict", "version_no": 1}
    assert [(t["idx"], t["role"], t["escalation_level"]) for t in body["turns"]] == [
        (0, "persona", 1)
    ]
    assert body["max_turns"] == 8


def test_a_turn_saves_both_messages_and_streams_the_reply(chat):
    api, use = chat
    use([output(level=2, reply="Not good enough.")])
    session_id = _start(api).json()["id"]
    response = _send(api, session_id)
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response)
    assert events["message"]["content"] == "Not good enough."
    assert events["done"]["level"] == 2
    assert events["done"]["turns_used"] == 1
    assert events["done"]["ended"] is False

    turns = _get(api, session_id).json()["turns"]
    shape = [(t["idx"], t["role"]) for t in turns]
    assert shape == [(0, "persona"), (1, "trainee"), (2, "persona")]
    assert turns[1]["content"] == "We will fix it by 9 June"


def test_sending_the_same_message_twice_saves_it_once(chat):
    api, use = chat
    engine = use([output(reply="First reply")])
    session_id = _start(api).json()["id"]
    first = _events(_send(api, session_id, key="k1"))
    again = _events(_send(api, session_id, key="k1"))
    assert again["message"]["content"] == "First reply"
    assert again["done"]["replayed"] is True
    assert first["done"]["persona_turn_id"] == again["done"]["persona_turn_id"]
    assert len(_get(api, session_id).json()["turns"]) == 3
    assert len(engine.contexts) == 1  # the engine was not asked twice


def test_a_failed_reply_saves_nothing_and_can_be_retried(chat):
    api, use = chat
    use([RuntimeError("model down"), output(reply="Back again")])
    session_id = _start(api).json()["id"]
    failed = _send(api, session_id, key="k1")
    assert failed.status_code == 502
    assert len(_get(api, session_id).json()["turns"]) == 1
    retried = _send(api, session_id, key="k1")
    assert retried.status_code == 200
    assert _events(retried)["message"]["content"] == "Back again"


def test_the_client_can_only_move_one_step_at_a_time(chat):
    api, use = chat
    use([output(level=4), output(level=1)])
    session_id = _start(api).json()["id"]
    assert _events(_send(api, session_id))["done"]["level"] == 2  # asked for 4 from step 1
    assert _events(_send(api, session_id))["done"]["level"] == 1


def _publish_persona(api, **overrides) -> None:
    """Publish a new version of the sample persona with some settings changed."""
    config = load_sample("personas/ms_verma_strict.json") | overrides
    base = "/api/v1/admin/config/persona/verma-strict/versions"
    version = api.client.post(base, headers=ADMIN, json={"config": config}).json()["version_no"]
    assert api.client.post(f"{base}/{version}/publish", headers=ADMIN).status_code == 200


def test_the_session_ends_at_the_turn_limit(chat):
    api, use = chat
    use([output(level=1)] * 3)
    _publish_persona(api, max_turns=3)
    session_id = _start(api).json()["id"]
    done = [_events(_send(api, session_id))["done"] for _ in range(3)]
    assert [d["ended"] for d in done] == [False, False, True]
    assert done[-1]["end_reason"] == "turn_cap"
    detail = _get(api, session_id).json()
    assert detail["status"] == "ended"
    assert detail["ended_at"] is not None
    assert _send(api, session_id).status_code == 409


def test_the_session_ends_early_when_the_checklist_is_covered(chat):
    api, use = chat
    use([output(quality=0.9, level=1, met=CHECKLIST)])
    _publish_persona(api, min_turns=1)
    session_id = _start(api).json()["id"]
    done = _events(_send(api, session_id))["done"]
    assert done["ended"] is True
    assert done["end_reason"] == "concerns_resolved"


def test_the_engine_is_told_which_checklist_items_are_still_open(chat):
    api, use = chat
    engine = use([output(met=CHECKLIST[:2]), output()])
    session_id = _start(api).json()["id"]
    _send(api, session_id)
    _send(api, session_id)
    assert engine.contexts[0].open_checklist == CHECKLIST
    assert engine.contexts[1].open_checklist == CHECKLIST[2:]
    assert engine.contexts[1].turns_used == 1


def test_invented_citations_are_dropped_and_real_ones_kept(chat):
    api, use = chat
    upload = api.client.post("/api/v1/proposals", headers=ANNA,
                             files={"file": ("p.txt", b"Budget\n\nVendor risk")})
    proposal_id = upload.json()["id"]
    with api.factory() as db:
        placeholder.ingest(db, api.queued[-1], api.store)
    real = api.client.get(f"/api/v1/proposals/{proposal_id}/segments", headers=ANNA).json()[0]["id"]
    use([output(refs=[real, str(uuid4())])])
    session_id = _start(api, proposal_id=proposal_id).json()["id"]
    assert _get(api, session_id).json()["turns"][0]["refs"] != [None]
    _send(api, session_id)
    persona_turn = _get(api, session_id).json()["turns"][-1]
    assert persona_turn["refs"] == [real]


def test_a_session_cannot_start_on_an_unready_or_foreign_proposal(chat):
    api, use = chat
    use([])
    upload = api.client.post("/api/v1/proposals", headers=ANNA,
                             files={"file": ("p.txt", b"Budget")})
    proposal_id = upload.json()["id"]  # still queued
    assert _start(api, proposal_id=proposal_id).status_code == 409
    assert _start(api, headers=BEN, proposal_id=proposal_id).status_code == 404


def test_starting_needs_published_settings(api):
    assert _start(api).status_code == 404


def test_people_only_see_their_own_sessions(chat):
    api, use = chat
    use([output()])
    session_id = _start(api).json()["id"]
    _send(api, session_id)
    assert _get(api, session_id, headers=BEN).status_code == 404
    assert api.client.get("/api/v1/sessions", headers=BEN).json() == []
    assert len(api.client.get("/api/v1/sessions", headers=ANNA).json()) == 1
    assert len(api.client.get("/api/v1/sessions?trainee_ref=anna", headers=ADMIN).json()) == 1
    assert _send(api, session_id, headers=BEN).status_code == 404
    assert _send(api, session_id, headers=ADMIN).status_code == 404  # admins cannot speak for them


def test_only_admins_see_the_judgement_of_each_answer(chat):
    api, use = chat
    use([output()])
    session_id = _start(api).json()["id"]
    _send(api, session_id)
    trainee_view = _get(api, session_id).json()["turns"][1]
    admin_view = _get(api, session_id, headers=ADMIN).json()["turns"][1]
    assert trainee_view["evaluation"] is None
    assert admin_view["evaluation"]["answer_quality"] == 0.3


def test_ending_a_session_is_safe_to_repeat(chat):
    api, use = chat
    use([])
    session_id = _start(api).json()["id"]
    ended = api.client.post(f"/api/v1/sessions/{session_id}/end", headers=ANNA)
    assert ended.json()["status"] == "ended"
    assert ended.json()["end_reason"] == "trainee_ended"
    again = api.client.post(f"/api/v1/sessions/{session_id}/end", headers=ANNA)
    # SQLite drops the time zone on the way back, PostgreSQL keeps it: compare without the "Z"
    assert again.json()["ended_at"].rstrip("Z") == ended.json()["ended_at"].rstrip("Z")


def test_an_admin_ending_someone_elses_session_is_recorded_as_such(chat):
    api, use = chat
    use([])
    session_id = _start(api).json()["id"]
    ended = api.client.post(f"/api/v1/sessions/{session_id}/end", headers=ADMIN)
    assert ended.json()["end_reason"] == "admin_ended"


def test_a_message_needs_text_and_an_idempotency_key(chat):
    api, use = chat
    use([])
    session_id = _start(api).json()["id"]
    assert _send(api, session_id, text="").status_code == 422
    no_key = api.client.post(f"/api/v1/sessions/{session_id}/turns", headers=ANNA,
                             json={"content": "hi"})
    assert no_key.status_code == 422


def test_planned_endpoints_answer_501_in_the_standard_shape(api):
    for method, path in (
        ("get", f"/api/v1/sessions/{uuid4()}/assessment"),
        ("get", "/api/v1/admin/review-queue"),
        ("post", f"/api/v1/admin/sessions/{uuid4()}/review"),
        ("post", f"/api/v1/admin/sessions/{uuid4()}/rescore"),
        ("get", f"/api/v1/admin/sessions/{uuid4()}/report"),
        ("get", "/api/v1/integration/signals"),
    ):
        response = getattr(api.client, method)(path, headers=ADMIN)
        assert response.status_code == 501, path
        assert response.json()["title"] == "Not Implemented"
