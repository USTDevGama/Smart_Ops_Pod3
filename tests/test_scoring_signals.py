from app.schemas import Evaluation
from app.scoring.signals import (
    COMMITS,
    COMPOSED,
    GROUNDED,
    SPECIFIC,
    AnswerInput,
    Reference,
    answer_signals,
)
from app.scoring.text import content_words, flatten_text

DOCS = Reference.from_text(
    "Backend engineer, three years of Java. Led a billing service rewrite. "
    "Warehouse picking dashboard: fixed price INR 18 lakh, go-live in 10 weeks."
)


def _eval(quality=0.8, evasive=False, composure=0.9) -> Evaluation:
    return Evaluation(
        answer_quality=quality,
        evasive=evasive,
        composure=composure,
        quote="x",
        proposed_level=1,
    )


def _answer(text, evaluation=None, client="When will the dashboard go live?") -> AnswerInput:
    return AnswerInput(number=1, client_text=client, text=text, evaluation=evaluation or _eval())


def test_a_concrete_date_and_good_quality_is_specific():
    assert SPECIFIC in answer_signals(_answer("The new date is 14 March."), DOCS)


def test_a_vague_or_evasive_answer_is_not_specific():
    assert SPECIFIC not in answer_signals(_answer("We are looking at options."), DOCS)
    evasive = _answer("It will be done by Friday.", _eval(evasive=True))
    assert SPECIFIC not in answer_signals(evasive, DOCS)
    weak = _answer("It will be done by Friday.", _eval(quality=0.3))
    assert SPECIFIC not in answer_signals(weak, DOCS)


def test_composure_needs_a_calm_evaluation_and_no_over_promising():
    assert COMPOSED in answer_signals(_answer("I understand, here is the plan."), DOCS)
    assert COMPOSED not in answer_signals(_answer("Fair.", _eval(composure=0.3)), DOCS)
    assert COMPOSED not in answer_signals(_answer("I guarantee it will never slip."), DOCS)


def test_composure_is_not_claimed_without_a_saved_evaluation():
    answer = AnswerInput(number=1, client_text="q", text="Calm answer.", evaluation=None)
    assert COMPOSED not in answer_signals(answer, DOCS)


def test_a_commitment_phrase_marks_ownership():
    assert COMMITS in answer_signals(_answer("I will send a status every Friday."), DOCS)
    assert COMMITS not in answer_signals(_answer("These things happen."), DOCS)
    assert COMMITS not in answer_signals(
        _answer("I will look into it.", _eval(evasive=True)), DOCS
    )


def test_an_answer_that_uses_the_documents_is_grounded():
    text = "The dashboard has a fixed price and go-live in 10 weeks as agreed."
    assert GROUNDED in answer_signals(_answer(text), DOCS)


def test_an_experience_claim_with_an_unknown_figure_is_not_grounded():
    text = "I have 12 years of Java experience and led the billing service rewrite."
    assert GROUNDED not in answer_signals(_answer(text), DOCS)


def test_a_figure_the_client_gave_is_not_invented():
    client = "You have 12 years of Java, correct?"
    text = "Yes, I have 12 years of Java on the billing rewrite."
    assert GROUNDED in answer_signals(_answer(text, client=client), DOCS)


def test_admitting_a_limit_counts_as_grounded():
    assert GROUNDED in answer_signals(_answer("I'm not sure; I will confirm tomorrow."), DOCS)


def test_without_any_documents_nothing_is_grounded():
    assert GROUNDED not in answer_signals(
        _answer("I'm not sure about that."), Reference.from_text("")
    )


def test_flatten_text_reads_nested_extracted_json():
    value = {"text": "one", "items": ["two", {"x": "three"}], "n": None}
    assert flatten_text(value).split("\n") == ["one", "two", "three"]
    assert flatten_text(None) == ""


def test_content_words_ignores_short_words():
    assert content_words("The dashboard is due in 10 weeks") == {"dashboard", "weeks"}
