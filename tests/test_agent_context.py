from app.agent.context import (
    MAX_DOC_CHARS,
    doc_text,
    find_scenario,
    history_lines,
    legal_levels,
    met_items,
    redact,
    settled_scenario,
)
from tests.agent_fixtures import client, ctx, ev, persona, scenarios, trainee

# --- documents -----------------------------------------------------------------------------------


def test_the_text_key_ingestion_produces_is_read_as_it_is():
    assert doc_text({"text": "Billing modernisation."}) == "Billing modernisation."


def test_other_shapes_are_tolerated():
    assert doc_text("plain string") == "plain string"
    assert doc_text({"markdown": "# Title"}) == "# Title"
    nested = {"pages": [{"n": 1, "text": "First page."}, {"n": 2, "text": "Second page."}]}
    assert doc_text(nested) == "First page.\n\nSecond page."
    assert doc_text({"sections": ["A", {"body": "B"}], "count": 2}) == "A\n\nB"


def test_a_missing_or_empty_document_is_an_empty_string():
    for content in (None, {}, {"text": ""}, [], 42, True):
        assert doc_text(content) == ""


def test_page_markers_are_kept_as_plain_text_and_other_comments_dropped():
    text = doc_text({"text": "<!-- page 1 -->\n\nHello\n\n<!-- hidden note -->\n\n\n\nWorld"})
    assert "[page 1]" in text
    assert "hidden note" not in text
    assert "<!--" not in text
    assert "\n\n\n" not in text


def test_a_very_long_document_is_cut_with_a_note():
    text = doc_text({"text": "word " * (MAX_DOC_CHARS // 2)})
    assert len(text) < MAX_DOC_CHARS + 100
    assert text.endswith("was cut here]")


# --- privacy -------------------------------------------------------------------------------------


def test_contact_details_and_id_like_numbers_are_removed_from_a_resume():
    resume = (
        "Mail me: trainee@example.com or call +00 00000 00000. "
        "Profile: https://example.com/in/trainee and www.example.com/me. "
        "ID 1234 5678 9012, tax AAAAA0000A, passport A0000000."
    )
    clean = redact(resume)
    for secret in ("trainee@example.com", "00000", "example.com", "5678", "AAAAA0000A", "A0000000"):
        assert secret not in clean
    assert "[email]" in clean
    assert "[link]" in clean
    assert "[number]" in clean
    assert "[id]" in clean


def test_dates_years_and_ordinary_figures_survive_redaction():
    text = "Worked 2019-2023, then 2021 2022 2023. Led 3 developers for 6 months, budget 12000."
    assert redact(text) == text


# --- scenario and checklist ----------------------------------------------------------------------


def test_a_scenario_is_found_by_its_id_whatever_the_case_or_spacing():
    assert find_scenario(scenarios(), " vd-01 ").id == "VD-01"
    assert find_scenario(scenarios(), "nope") is None


def test_before_any_item_is_met_the_scenario_is_not_settled():
    assert settled_scenario(ctx()) is None


def test_the_scenario_is_the_one_that_owns_the_items_already_met():
    vendor, scope = scenarios()
    turns = [client("q"), trainee("a", ev(met=[scope.good_answer_contains[0]]))]
    assert settled_scenario(ctx(turns=turns)).id == "SR-01"
    turns = [client("q"), trainee("a", ev(met=vendor.good_answer_contains[:2]))]
    assert settled_scenario(ctx(turns=turns)).id == "VD-01"


def test_a_tie_between_scenarios_is_not_settled():
    vendor, scope = scenarios()
    met = [vendor.good_answer_contains[0], scope.good_answer_contains[0]]
    assert settled_scenario(ctx(turns=[client("q"), trainee("a", ev(met=met))])) is None


def test_items_met_in_any_earlier_answer_are_collected():
    vendor = scenarios()[0]
    first, second = vendor.good_answer_contains[0], vendor.good_answer_contains[1]
    turns = [
        client("q1"),
        trainee("a1", ev(met=[first])),
        client("q2"),
        trainee("a2", ev(met=[second])),
    ]
    assert met_items(ctx(turns=turns)) == {first, second}


# --- levels and history --------------------------------------------------------------------------


def test_the_client_may_move_one_step_either_way_inside_the_ladder():
    assert legal_levels(ctx(level=1)) == (1, 2)
    assert legal_levels(ctx(level=2)) == (1, 3)
    assert legal_levels(ctx(level=4)) == (3, 4)


def test_a_short_ladder_limits_the_range():
    two_steps = persona(escalation_ladder=[{"step": 1, "move": "ask"}, {"step": 2, "move": "push"}])
    assert legal_levels(ctx(level=2, persona_=two_steps)) == (1, 2)
    assert legal_levels(ctx(level=4, persona_=two_steps)) == (1, 2)  # a stale level is pulled in


def test_history_says_how_each_answer_was_judged_and_how_the_client_then_spoke():
    turns = [
        client("q1", level=1),
        trainee("a1", ev(quality=0.3, evasive=True, composure=0.6)),
        client("q2", level=2),
        trainee("a2", ev(quality=0.8)),
    ]
    lines = history_lines(ctx(turns=turns, level=2))
    assert lines == [
        "Answer 1: quality 0.30, evasive, composure 0.60; you then spoke at level 2",
        "Answer 2: quality 0.80, not evasive, composure 0.90",
    ]
    assert history_lines(ctx()) == []
