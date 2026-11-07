from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.db import models as m
from app.reports.generator import (
    ReportDataError,
    ReportNotReadyError,
    generate_report,
    load_report_data,
)
from app.reports.schemas import ValidatedAssessment
from app.schemas.enums import (
    ConfigKind,
    ConfigStatus,
    EndReason,
    SessionStatus,
    TurnRole,
)


def _assessment(**overrides) -> ValidatedAssessment:
    data = {
        "rubric_version": "r1",
        "criteria": [
            {
                "id": "C1",
                "label": "Owns the delay",
                "weight": 0.5,
                "points": 0.7,
                "status": "met",
                "confidence": 82,
                "reason": "Accepted responsibility.",
                "evidence": [{"turn": 1, "polarity": "positive"}],
            },
            {
                "id": "C2",
                "label": "Gives a prevention plan",
                "weight": 0.5,
                "points": 0.2,
                "status": "not_met",
                "confidence": 60,
                "reason": "No concrete prevention step.",
                "evidence": [{"turn": 2, "polarity": "negative"}],
            },
        ],
        "handled": "partly",
        "confidence_score": 71,
        "strengths": [{"text": "Accepted responsibility", "evidence_turns": [1]}],
        "gaps": [{"text": "No prevention plan", "evidence_turns": [2]}],
        "unanswered_objections": ["Who pays for the delay?"],
        "human_review_required": True,
    }
    data.update(overrides)
    return ValidatedAssessment.model_validate(data)


def _ended_session(db, *, status=SessionStatus.ENDED, unsafe_text=False):
    persona = m.ConfigVersion(
        kind=ConfigKind.PERSONA,
        key="strict",
        version_no=1,
        status=ConfigStatus.PUBLISHED,
        config={
            "version": "strict-1.0",
            "name": "Ms. Example",
            "role": "Sponsor",
            "style": "Formal",
            "main_concerns": ["Delivery"],
            "escalation_ladder": [{"step": 1, "move": "Ask a question"}],
        },
    )
    scenario = m.ConfigVersion(
        kind=ConfigKind.SCENARIO,
        key="delivery",
        version_no=2,
        status=ConfigStatus.PUBLISHED,
        config={
            "id": "SC-01",
            "title": "Delivery slipping",
            "situation": "A delivery is late.",
            "client_objections": ["Why is it late?"],
            "good_answer_contains": ["Owns the delay"],
        },
    )
    db.add_all([persona, scenario])
    db.flush()
    session = m.RoleplaySession(
        trainee_ref="report-test-user",
        persona_version_id=persona.id,
        scenario_version_id=scenario.id,
        status=status,
        end_reason=EndReason.TURN_CAP if status == SessionStatus.ENDED else None,
        ended_at=datetime.now(UTC) if status == SessionStatus.ENDED else None,
    )
    db.add(session)
    db.flush()
    trainee_content = (
        "<script>alert('unsafe')</script>" if unsafe_text else "We will monitor it."
    )
    db.add_all(
        [
            m.Turn(
                session_id=session.id,
                idx=0,
                role=TurnRole.PERSONA,
                content="Why is the delivery late?",
                escalation_level=1,
            ),
            m.Turn(
                session_id=session.id,
                idx=1,
                role=TurnRole.TRAINEE,
                content="I own the delay.",
            ),
            m.Turn(
                session_id=session.id,
                idx=2,
                role=TurnRole.PERSONA,
                content="How will you prevent a repeat?",
                escalation_level=2,
            ),
            m.Turn(
                session_id=session.id,
                idx=3,
                role=TurnRole.TRAINEE,
                content=trainee_content,
            ),
        ]
    )
    db.flush()
    return session


def test_generates_markdown_html_and_pdf_for_completed_session(db):
    session = _ended_session(db)

    report = generate_report(db, session.id, _assessment())

    assert "Overall score: **45.0 / 100**" in report.markdown
    assert "Persona: strict-1.0 | Rubric: r1" in report.markdown
    assert "- Confidence score: 71" in report.markdown
    assert "Scenario version:" not in report.markdown
    assert "### Turn 1" in report.markdown
    assert "**Client:** Why is the delivery late?" in report.markdown
    assert "**Trainee:** I own the delay." in report.markdown
    assert "Turn 2 (-): No concrete prevention step." in report.markdown
    assert "<table>" in report.html
    assert "<script>" not in report.html
    assert report.pdf.startswith(b"%PDF-")


def test_turn_citations_refer_to_exchange_numbers_and_must_exist(db):
    session = _ended_session(db)
    assessment = _assessment(
        criteria=[
            {
                "id": "C1",
                "label": "Owns the delay",
                "weight": 1,
                "points": 1,
                "status": "met",
                "confidence": 90,
                "reason": "Evidence on missing exchange.",
                "evidence": [{"turn": 3, "polarity": "positive"}],
            }
        ]
    )

    with pytest.raises(ReportDataError, match="missing trainee exchanges: 3"):
        load_report_data(db, session.id, assessment)


def test_report_requires_an_ended_session(db):
    session = _ended_session(db, status=SessionStatus.ACTIVE)

    with pytest.raises(ReportNotReadyError, match="ended session"):
        load_report_data(db, session.id, _assessment())


def test_untrusted_transcript_markup_is_escaped_before_html_and_pdf(db):
    session = _ended_session(db, unsafe_text=True)

    report = generate_report(db, session.id, _assessment())

    assert "<script>" not in report.html
    assert "<script>" not in report.markdown
    assert report.pdf.startswith(b"%PDF-")


def test_weights_must_sum_to_one():
    with pytest.raises(ValidationError, match="weights must sum to 1"):
        _assessment(
            criteria=[
                {
                    "id": "C1",
                    "label": "One",
                    "weight": 0.2,
                    "points": 0.5,
                    "status": "partly",
                    "confidence": 75,
                    "reason": "Reason",
                }
            ]
        )
