from uuid import uuid4

import pytest

from app.llm import LLMError
from app.scoring.scorer import ScoringError
from app.workers import tasks


@pytest.fixture
def ran(monkeypatch):
    seen = []
    monkeypatch.setattr("app.scoring.pipeline.assess_and_render_in_new_session", seen.append)
    return seen


def test_the_one_task_runs_scoring_and_the_report_with_the_id_only(ran):
    session_id = uuid4()

    tasks.run_assessment.apply(args=[str(session_id)]).get()

    assert ran == [session_id]


@pytest.mark.parametrize("error", [ScoringError("x"), LLMError("x")])
def test_a_scoring_failure_is_retried_twice_then_fails(monkeypatch, error):
    attempts = []

    def fail(_):
        attempts.append(1)
        raise error

    monkeypatch.setattr("app.scoring.pipeline.assess_and_render_in_new_session", fail)
    result = tasks.run_assessment.apply(args=[str(uuid4())])

    assert len(attempts) == 3  # the first try and two retries, then it fails for good
    assert result.result is error


def test_a_problem_that_a_retry_cannot_fix_is_not_retried(monkeypatch):
    attempts = []

    def fail(_):
        attempts.append(1)
        raise ValueError("the session is not ready")

    monkeypatch.setattr("app.scoring.pipeline.assess_and_render_in_new_session", fail)
    tasks.run_assessment.apply(args=[str(uuid4())])

    assert len(attempts) == 1
