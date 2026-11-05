import pytest

from app.agent.escalation import last_trainee_evaluation, move_for, next_level
from tests.agent_fixtures import evaluation, persona, persona_turn, trainee_turn

# The sample persona: t_escalate 0.5, t_deescalate 0.7, ladder steps 1 to 4.
P = persona()


@pytest.mark.parametrize(
    ("level", "quality", "expected"),
    [(1, 0.2, 2), (2, 0.49, 3), (3, 0.0, 4), (4, 0.1, 4)],  # weak: one step tougher, capped
)
def test_a_weak_answer_makes_the_client_one_step_tougher(level, quality, expected):
    assert next_level(P, level, evaluation(quality), None) == expected


def test_an_evasive_answer_counts_as_weak_even_when_it_scores_well():
    assert next_level(P, 2, evaluation(0.9, evasive=True), evaluation(0.9)) == 3


def test_a_middling_answer_keeps_the_level():
    assert next_level(P, 3, evaluation(0.6), evaluation(0.9)) == 3  # between 0.5 and 0.7


def test_boundaries_are_inclusive_where_the_docs_say_so():
    assert next_level(P, 2, evaluation(0.5), None) == 2  # 0.5 is not below t_escalate
    assert next_level(P, 2, evaluation(0.7), evaluation(0.7)) == 1  # 0.7 reaches t_deescalate


def test_one_good_answer_is_not_enough_to_ease_off():
    assert next_level(P, 3, evaluation(0.9), None) == 3  # the first answer ever
    assert next_level(P, 3, evaluation(0.9), evaluation(0.2)) == 3  # after a weak one
    assert next_level(P, 3, evaluation(0.9), evaluation(0.6)) == 3  # after a middling one


def test_two_good_answers_in_a_row_ease_off_one_step_but_never_below_one():
    assert next_level(P, 3, evaluation(0.9), evaluation(0.8)) == 2
    assert next_level(P, 1, evaluation(0.9), evaluation(0.8)) == 1


def test_an_evasive_previous_answer_does_not_count_as_good():
    assert next_level(P, 3, evaluation(0.9), evaluation(0.9, evasive=True)) == 3


def test_a_level_outside_the_ladder_is_pulled_back_into_range():
    assert next_level(P, 9, evaluation(0.6), None) == 4


def test_the_top_step_follows_the_persona_not_a_fixed_four():
    short = persona(escalation_ladder=[{"step": 1, "move": "ask"}, {"step": 2, "move": "press"}])
    assert next_level(short, 2, evaluation(0.1), None) == 2


def test_last_trainee_evaluation_skips_client_turns_and_is_none_before_the_first_answer():
    assert last_trainee_evaluation([persona_turn("Hello", 1)]) is None
    turns = [
        persona_turn("Q1", 1),
        trainee_turn("A1", 0.2),
        persona_turn("Q2", 2),
        trainee_turn("A2", 0.8),
        persona_turn("Q3", 2),
    ]
    assert last_trainee_evaluation(turns).answer_quality == 0.8


def test_move_for_gives_the_ladder_rung_for_a_level():
    assert move_for(P, 1) == "Ask a short clarifying question"
    assert move_for(P, 4).startswith("Say plainly that she is losing confidence")
    assert move_for(P, 9).startswith("Say plainly")  # above the ladder: the top rung
