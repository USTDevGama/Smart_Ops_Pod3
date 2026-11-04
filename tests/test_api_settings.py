from tests.conftest import ADMIN, ANNA, load_sample, publish_sample_settings

PERSONA = load_sample("personas/ms_verma_strict.json")
BASE = "/api/v1/admin/config/persona"


def _create(client, key="verma", config=None):
    return client.post(BASE, headers=ADMIN, json={"key": key, "config": config or PERSONA})


def _publish(client, version_no=1, key="verma"):
    return client.post(f"{BASE}/{key}/versions/{version_no}/publish", headers=ADMIN)


def test_admin_creates_a_draft_and_publishes_it(api):
    created = _create(api.client)
    assert created.status_code == 201
    assert created.json()["status"] == "draft"
    assert created.json()["version_no"] == 1
    assert _publish(api.client).json()["status"] == "published"


def test_a_published_version_can_no_longer_be_edited_or_republished(api):
    _create(api.client)
    _publish(api.client)
    edit = api.client.put(f"{BASE}/verma/versions/1", headers=ADMIN, json={"config": PERSONA})
    assert edit.status_code == 409
    assert _publish(api.client).status_code == 409


def test_publishing_a_new_version_retires_the_old_one(api):
    _create(api.client)
    _publish(api.client)
    v2 = api.client.post(f"{BASE}/verma/versions", headers=ADMIN)
    assert v2.status_code == 201
    assert v2.json()["version_no"] == 2
    first = api.client.get(f"{BASE}/verma/versions/1", headers=ADMIN).json()
    assert v2.json()["config"] == first["config"]  # copied from the latest
    _publish(api.client, version_no=2)

    keys = api.client.get(BASE, headers=ADMIN).json()
    statuses = {v["version_no"]: v["status"] for v in keys[0]["versions"]}
    assert statuses == {1: "retired", 2: "published"}


def test_a_draft_can_be_edited(api):
    _create(api.client)
    edited = api.client.put(
        f"{BASE}/verma/versions/1", headers=ADMIN, json={"config": PERSONA | {"max_turns": 5}}
    )
    assert edited.status_code == 200
    assert edited.json()["config"]["max_turns"] == 5


def test_invalid_settings_are_refused_with_the_reason(api):
    bad = _create(api.client, config=PERSONA | {"min_turns": 9, "max_turns": 2})
    assert bad.status_code == 422
    assert "min_turns cannot exceed max_turns" in str(bad.json()["detail"])


def test_a_key_can_only_be_created_once(api):
    _create(api.client)
    assert _create(api.client).status_code == 409


def test_scoring_profiles_are_not_a_setting_yet(api):
    response = api.client.get("/api/v1/admin/config/scoring_profile", headers=ADMIN)
    assert response.status_code == 422


def test_only_admins_edit_settings(api):
    assert api.client.get(BASE, headers=ANNA).status_code == 403
    body = {"key": "x", "config": PERSONA}
    assert api.client.post(BASE, headers=ANNA, json=body).status_code == 403


def test_trainees_see_only_published_personas_and_scenarios(api):
    _create(api.client, key="draft-only")
    assert api.client.get("/api/v1/personas", headers=ANNA).json() == []
    publish_sample_settings(api.client)
    personas = api.client.get("/api/v1/personas", headers=ANNA).json()
    scenarios = api.client.get("/api/v1/scenarios", headers=ANNA).json()
    assert [p["key"] for p in personas] == ["verma-strict"]
    assert personas[0]["title"] == "Ms. Verma"
    assert scenarios[0]["title"] == "Vendor late with a component"


def test_errors_use_one_shape(api):
    response = api.client.get(BASE)
    assert response.status_code == 401
    assert set(response.json()) >= {"type", "title", "status", "detail"}
