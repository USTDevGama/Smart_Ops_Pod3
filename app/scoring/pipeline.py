"""After a session ends: score the chat, check it with code, and write the report.

    run_assessment   transcript -> scoring model call -> signals and question validity (code)
                     -> `build_assessment` -> assessment JSON in blob storage
    render_report    reads that JSON -> Markdown, HTML and PDF in blob storage

The two steps are separate Celery tasks (see `app/workers/tasks.py`). Every file has a fixed name
under `reports/<session_id>/`, so a retried or repeated task overwrites its own files and the
stored JSON is the one snapshot of the score. Nothing here keeps conversation text in logs.
"""

import json
import logging
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import get_engine
from app.llm import LLMClient, get_llm_client
from app.reports.generator import ReportArtifacts, generate_report
from app.schemas import Assessment, Evaluation, PersonaConfig, ScoringConfig
from app.schemas.enums import SessionStatus, TurnRole
from app.scoring.processor import ScoringValidationContext, build_assessment, derive_handled
from app.scoring.rubric import default_scoring_config, prompt_config
from app.scoring.scorer import score_session
from app.scoring.signals import GROUNDED, AnswerInput, trainee_signals
from app.scoring.text import flatten_text
from app.scoring.transcript import build_transcript
from app.scoring.validity import ClientMessage, question_validity
from app.storage import BlobStore, get_blob_store

log = logging.getLogger(__name__)

ASSESSMENT_FILE = "assessment.json"
REPORT_FILES = {"markdown": "report.md", "html": "report.html", "pdf": "report.pdf"}


class AssessmentNotReadyError(ValueError):
    """The session is missing, still active, or has no stored assessment yet."""


def blob_key(session_id: UUID | str, filename: str) -> str:
    return f"reports/{session_id}/{filename}"


def run_assessment_in_new_session(session_id: UUID) -> None:
    with Session(get_engine()) as db:
        run_assessment(db, session_id, get_llm_client(), get_blob_store())


def render_report_in_new_session(session_id: UUID) -> None:
    with Session(get_engine()) as db:
        render_report(db, session_id, get_blob_store())


def assess_and_render_in_new_session(session_id: UUID) -> None:
    run_assessment_in_new_session(session_id)
    render_report_in_new_session(session_id)


def report_ready(store: BlobStore, session_id: UUID | str) -> bool:
    return store.exists(blob_key(session_id, REPORT_FILES["pdf"]))


def run_assessment(
    db: Session,
    session_id: UUID,
    llm: LLMClient,
    store: BlobStore,
    config: ScoringConfig | None = None,
) -> Assessment:
    config = config or default_scoring_config()
    session = db.get(m.RoleplaySession, session_id)
    if session is None:
        raise AssessmentNotReadyError(f"session {session_id} was not found")
    if session.status != SessionStatus.ENDED:
        raise AssessmentNotReadyError("a session must be ended before it is scored")

    rows = list(
        db.scalars(select(m.Turn).where(m.Turn.session_id == session.id).order_by(m.Turn.idx))
    )
    transcript = build_transcript(rows)
    persona_row = db.get(m.ConfigVersion, session.persona_version_id)
    persona = PersonaConfig.model_validate(persona_row.config)

    documents = _document_text(db, session)
    reference = "\n".join(part for part in [documents, *persona.main_concerns] if part)
    effective = config if documents else _without_signal(config, GROUNDED)

    output = score_session(llm, prompt_config(config), transcript)

    answers, clients = _exchanges(rows)
    signals = trainee_signals(answers, documents)
    validity = question_validity(clients, persona.max_step, reference)
    validation = ScoringValidationContext(
        client_exchange_numbers=transcript.client_numbers,
        trainee_exchange_numbers=transcript.trainee_numbers,
        question_validity=validity,
        trainee_signals=signals,
    )
    assessment = build_assessment(
        output, effective, validation, handled=derive_handled(output, config)
    )

    snapshot = {
        "session_id": str(session.id),
        "assessment": assessment.model_dump(mode="json"),
        "overall_score": assessment.overall_score,
        "scoring_output": output.model_dump(mode="json"),
        "signals": {str(n): sorted(found) for n, found in signals.items()},
        "question_validity": {str(n): ok for n, ok in validity.items()},
        "grounding_documents_found": bool(documents),
    }
    store.save(
        json.dumps(snapshot, indent=2).encode(),
        ".json",
        name=blob_key(session.id, ASSESSMENT_FILE),
    )
    log.info("assessment saved for session %s", session.id)
    return assessment


def render_report(db: Session, session_id: UUID, store: BlobStore) -> ReportArtifacts:
    key = blob_key(session_id, ASSESSMENT_FILE)
    if not store.exists(key):
        raise AssessmentNotReadyError("the assessment has not been saved for this session")
    snapshot = json.loads(store.read(key))
    assessment = Assessment.model_validate(snapshot["assessment"])

    artifacts = generate_report(db, session_id, assessment)
    contents = {
        "markdown": artifacts.markdown.encode(),
        "html": artifacts.html.encode(),
        "pdf": artifacts.pdf,
    }
    for kind, filename in REPORT_FILES.items():
        store.save(contents[kind], "", name=blob_key(session_id, filename))
    log.info("report saved for session %s", session_id)
    return artifacts


def _document_text(db: Session, session: m.RoleplaySession) -> str:
    """The trainee's resume and the demand document as plain text. Either may be missing."""
    parts = []
    if session.profile_id:
        profile = db.get(m.Profile, session.profile_id)
        if profile is not None:
            parts.append(flatten_text(profile.content))
    if session.demand_id:
        demand = db.get(m.DemandDocument, session.demand_id)
        if demand is not None:
            parts.append(flatten_text(demand.content))
    return "\n".join(part for part in parts if part)


def _without_signal(config: ScoringConfig, key: str) -> ScoringConfig:
    """With no documents to compare against, a signal cannot be checked, so it is not used."""
    criteria = [
        criterion.model_copy(
            update={"signal_keys": [k for k in criterion.signal_keys if k != key]}
        )
        for criterion in config.criteria
    ]
    return config.model_copy(update={"criteria": criteria})


def _exchanges(rows: list[m.Turn]) -> tuple[list[AnswerInput], list[ClientMessage]]:
    """Pair the saved rows the way `build_transcript` numbers them: a client message opens an
    exchange and the trainee reply that follows shares its number."""
    answers: list[AnswerInput] = []
    clients: list[ClientMessage] = []
    for row in rows:
        if row.role == TurnRole.PERSONA:
            clients.append(ClientMessage(len(clients) + 1, row.content, row.escalation_level))
        elif clients:
            answers.append(
                AnswerInput(
                    number=clients[-1].number,
                    client_text=clients[-1].text,
                    text=row.content,
                    evaluation=_evaluation(row.evaluation),
                )
            )
    return answers, clients


def _evaluation(raw: dict | None) -> Evaluation | None:
    if not raw:
        return None
    try:
        return Evaluation.model_validate(raw)
    except ValidationError:
        return None
