from uuid import uuid4

import pytest

from app.llm import LLMError
from app.scoring.scorer import ScoringError
from app.workers import tasks


@pytest.fixture
def calls(monkeypatch):
    seen = {"assess": [], "render": [], "queued": []}
    monkeypatch.setattr(
        "app.scoring.pipeline.run_assessment_in_new_session", lambda sid: seen["assess"].append(sid)
    )
    monkeypatch.setattr(
        "app.scoring.pipeline.render_report_in_new_session", lambda sid: seen["render"].append(sid)
    )
    monkeypatch.setattr(tasks.render_report, "delay", lambda sid: seen["queued"].append(sid))
    return seen


def test_run_assessment_scores_then_queues_the_report_with_the_id_only(calls):
    session_id = str(uuid4())

    tasks.run_assessment.apply(args=[session_id]).get()

    assert [str(s) for s in calls["assess"]] == [session_id]
    assert calls["queued"] == [session_id]
    assert calls["render"] == []  # rendering happens in its own job


@pytest.mark.parametrize("error", [ScoringError("x"), LLMError("x")])
def test_a_scoring_failure_is_retried_twice_and_no_report_is_queued(calls, monkeypatch, error):
    attempts = []

    def fail(_):
        attempts.append(1)
        raise error

    monkeypatch.setattr("app.scoring.pipeline.run_assessment_in_new_session", fail)
    result = tasks.run_assessment.apply(args=[str(uuid4())])

    assert len(attempts) == 3  # the first try and two retries, then it fails for good
    assert result.result is error
    assert calls["queued"] == []


def test_render_report_writes_the_report_for_the_session(calls):
    session_id = str(uuid4())

    tasks.render_report.apply(args=[session_id]).get()

    assert [str(s) for s in calls["render"]] == [session_id]
