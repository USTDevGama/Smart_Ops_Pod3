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


def test_trainees_see_only_published_personas(api):
    _create(api.client, key="draft-only")
    assert api.client.get("/api/v1/personas", headers=ANNA).json() == []
    publish_sample_settings(api.client)
    personas = api.client.get("/api/v1/personas", headers=ANNA).json()
    assert [p["key"] for p in personas] == ["verma-strict"]
    assert personas[0]["title"] == "Ms. Verma"
    assert api.client.get("/api/v1/scenarios", headers=ANNA).status_code == 404  # no longer chosen


DEMAND = load_sample("demand/project_demand.json")
SCENARIOS = load_sample("scenarios/vendor_delay.json")
IMPORT = "/api/v1/admin/scenarios/import"


def test_the_demand_is_a_setting_with_its_own_shape(api):
    base = "/api/v1/admin/config/demand"
    created = api.client.post(base, headers=ADMIN, json={"key": "gama-project", "config": DEMAND})
    assert created.status_code == 201
    no_expectations = DEMAND | {"expectations": []}
    refused = api.client.post(base, headers=ADMIN, json={"key": "x", "config": no_expectations})
    assert refused.status_code == 422


def test_scenarios_cannot_be_created_or_edited_by_hand(api):
    api.client.post(IMPORT, headers=ADMIN, json=SCENARIOS)
    scenario = SCENARIOS["scenarios"][0]
    base = "/api/v1/admin/config/scenario"
    calls = [
        api.client.post(base, headers=ADMIN, json={"key": "new", "config": scenario}),
        api.client.post(f"{base}/vd-01/versions", headers=ADMIN, json={"config": scenario}),
        api.client.put(f"{base}/vd-01/versions/1", headers=ADMIN, json={"config": scenario}),
        api.client.post(f"{base}/vd-01/versions/1/publish", headers=ADMIN),
    ]
    assert [c.status_code for c in calls] == [422, 422, 422, 422]
    assert api.client.get(base, headers=ADMIN).status_code == 200  # reading is still fine
    assert api.client.get(f"{base}/vd-01/versions/1", headers=ADMIN).status_code == 200


def test_scenarios_are_loaded_once_in_bulk(api):
    first = api.client.post(IMPORT, headers=ADMIN, json=SCENARIOS)
    assert first.status_code == 200
    assert first.json() == {"created": ["vd-01"], "updated": [], "unchanged": []}
    listed = api.client.get("/api/v1/admin/config/scenario", headers=ADMIN).json()
    assert [(k["key"], [v["status"] for v in k["versions"]]) for k in listed] == [
        ("vd-01", ["published"])
    ]


def test_sending_the_same_scenario_file_again_changes_nothing(api):
    api.client.post(IMPORT, headers=ADMIN, json=SCENARIOS)
    again = api.client.post(IMPORT, headers=ADMIN, json=SCENARIOS)
    assert again.json() == {"created": [], "updated": [], "unchanged": ["vd-01"]}


def test_a_changed_scenario_becomes_the_next_version(api):
    api.client.post(IMPORT, headers=ADMIN, json=SCENARIOS)
    changed = {"scenarios": [SCENARIOS["scenarios"][0] | {"title": "Vendor very late"}]}
    result = api.client.post(IMPORT, headers=ADMIN, json=changed)
    assert result.json()["updated"] == ["vd-01"]
    versions = api.client.get("/api/v1/admin/config/scenario", headers=ADMIN).json()[0]["versions"]
    assert [(v["version_no"], v["status"]) for v in versions] == [(1, "retired"), (2, "published")]


def test_the_scenario_import_checks_its_input_and_who_sends_it(api):
    assert api.client.post(IMPORT, headers=ANNA, json=SCENARIOS).status_code == 403
    assert api.client.post(IMPORT, headers=ADMIN, json={"scenarios": []}).status_code == 422
    broken = {"scenarios": [{"id": "X-1", "title": "no objections"}]}
    assert api.client.post(IMPORT, headers=ADMIN, json=broken).status_code == 422
    twice = {"scenarios": SCENARIOS["scenarios"] * 2}
    assert api.client.post(IMPORT, headers=ADMIN, json=twice).status_code == 422
    nothing_saved = api.client.get("/api/v1/admin/config/scenario", headers=ADMIN).json()
    assert nothing_saved == []


def test_errors_use_one_shape(api):
    response = api.client.get(BASE)
    assert response.status_code == 401
    assert set(response.json()) >= {"type", "title", "status", "detail"}
