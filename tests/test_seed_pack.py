"""Checks that our schemas fit the program's real (confidential) seed pack.

Skipped unless PODC_SEED_DIR points at the pack, which lives OUTSIDE this repo.
"""

import json

import pytest

from app import seed

PACK = seed.seed_dir()

pytestmark = pytest.mark.skipif(
    PACK is None or not PACK.exists(), reason="PODC_SEED_DIR not set: seed pack not available"
)


def test_personas_load():
    for name in ("persona_strict.json", "persona_friendly_demo.json"):
        persona = seed.load_persona(PACK / name)
        assert persona.escalation_ladder and persona.main_concerns


def test_scenarios_load_and_have_a_checklist():
    scenarios = seed.load_scenarios(PACK / "scenarios.json")
    assert len(scenarios) == 3
    assert all(s.good_answer_contains and s.client_objections for s in scenarios)


def test_environment_settings_point_at_real_persona_files():
    for name in ("stage.settings.json", "prod.settings.json"):
        env = seed.load_environment_settings(PACK / "config" / name)
        assert (PACK / env.persona_file).exists()


def test_known_answer_cases_refer_to_real_scenarios():
    scenario_ids = {s.id for s in seed.load_scenarios(PACK / "scenarios.json")}
    cases = json.loads((PACK / "sample_trainee_responses.json").read_text("utf-8"))["samples"]
    assert len(cases) == 5
    assert {c["scenario_id"] for c in cases} <= scenario_ids
