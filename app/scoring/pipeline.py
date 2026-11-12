"""After a session ends: score the chat, check it with code, and write the report.

    assess_session      transcript -> code checks (markers, question validity) -> scoring model
                        call -> `build_assessment` -> assessment JSON in blob storage
    render_report       reads that JSON -> Markdown, HTML and PDF in blob storage
    assess_and_render   both, in order. This is what the one Celery task (`run_assessment` in
                        `app/workers/tasks.py`) runs. If the assessment JSON is already saved, a
                        retry skips the model call and only renders, so a failure while writing
                        the PDF can never change a score that was already saved.

Every file has a fixed name under `reports/<session_id>/`, so a retried or repeated job overwrites
its own files and the stored JSON is the one snapshot of the score. Nothing here keeps
conversation text in logs.
"""

import json
import logging
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import models as m
from app.db.session import get_engine
from app.llm import LLMClient, get_llm_client
from app.reports.generator import ReportArtifacts, generate_report
from app.schemas import Assessment, Evaluation, PersonaConfig, ScoringConfig
from app.schemas.enums import EndReason, SessionStatus, TurnRole
from app.scoring.pod_d import build_pod_d_result, save_pod_d_result
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


def assess_and_render(
    db: Session,
    session_id: UUID,
    llm: LLMClient,
    store: BlobStore,
    config: ScoringConfig | None = None,
) -> ReportArtifacts:
    """Score, write the report, and sync its Pod D scores."""
    if store.exists(blob_key(session_id, ASSESSMENT_FILE)):
        log.info("assessment already saved for session %s; rendering only", session_id)
        snapshot = json.loads(store.read(blob_key(session_id, ASSESSMENT_FILE)))
        assessment = Assessment.model_validate(snapshot["assessment"])
    else:
        assessment = assess_session(db, session_id, llm, store, config)

    report = render_report(db, session_id, store)
    _sync_pod_d_scores(db, session_id, assessment)
    return report


def _sync_pod_d_scores(db: Session, session_id: UUID, assessment: Assessment) -> None:
    settings = get_settings()
    if settings.trainee_db_url is None:
        if settings.env == "prod":
            raise RuntimeError("TRAINEE_DB_URL must be configured in production")
        log.info("Pod D score sync skipped: TRAINEE_DB_URL is not configured")
        return

    session = db.get(m.RoleplaySession, session_id)
    if session is None:
        raise AssessmentNotReadyError(f"session {session_id} was not found")

    # The future Zitadel adapter must set this stored owner ref to the trusted Pod D trainee_id.
    result = build_pod_d_result(assessment, trainee_id=session.trainee_ref)
    save_pod_d_result(result, settings.trainee_db_url.get_secret_value())
    log.info("Pod D scores saved for session %s", session_id)


def assess_and_render_in_new_session(session_id: UUID) -> None:
    with Session(get_engine()) as db:
        assess_and_render(db, session_id, get_llm_client(), get_blob_store())


def report_ready(store: BlobStore, session_id: UUID | str) -> bool:
    return store.exists(blob_key(session_id, REPORT_FILES["pdf"]))


def assess_session(
    db: Session,
    session_id: UUID,
    llm: LLMClient,
    store: BlobStore,
    config: ScoringConfig | None = None,
) -> Assessment:
    """Score one ended session and save the snapshot. The model is called last, after every
    check that needs only our own data, so a bad row fails before any model cost."""
    config = config or default_scoring_config()
    session = db.get(m.RoleplaySession, session_id)
    if session is None:
        raise AssessmentNotReadyError(f"session {session_id} was not found")
    if session.status != SessionStatus.ENDED:
        raise AssessmentNotReadyError("a session must be ended before it is scored")
    persona_row = db.get(m.ConfigVersion, session.persona_version_id)
    if persona_row is None:
        raise AssessmentNotReadyError("the session's pinned persona version is missing")
    persona = PersonaConfig.model_validate(persona_row.config)

    rows = list(
        db.scalars(select(m.Turn).where(m.Turn.session_id == session.id).order_by(m.Turn.idx))
    )
    transcript = build_transcript(rows)
    documents = _document_text(db, session)
    answers, clients = _exchanges(rows)
    signals = trainee_signals(answers, documents)
    validity = question_validity(
        clients, persona.max_step, "\n".join([documents, *persona.main_concerns])
    )
    validation = ScoringValidationContext(
        client_exchange_numbers=transcript.client_numbers,
        trainee_exchange_numbers=transcript.trainee_numbers,
        question_validity=validity,
        trainee_signals=signals,
    )

    output = score_session(llm, prompt_config(config), transcript)
    assessment = build_assessment(
        output,
        config if documents else _without_signal(config, GROUNDED),
        validation,
        handled=derive_handled(output, config),
        ended_by_trainee=session.end_reason == EndReason.TRAINEE_ENDED,
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
    store.save(json.dumps(snapshot, indent=2).encode(), name=blob_key(session.id, ASSESSMENT_FILE))
    log.info("assessment saved for session %s", session.id)
    return assessment


def render_report(db: Session, session_id: UUID, store: BlobStore) -> ReportArtifacts:
    key = blob_key(session_id, ASSESSMENT_FILE)
    if not store.exists(key):
        raise AssessmentNotReadyError("the assessment has not been saved for this session")
    assessment = Assessment.model_validate(json.loads(store.read(key))["assessment"])

    artifacts = generate_report(db, session_id, assessment)
    contents = {
        "markdown": artifacts.markdown.encode(),
        "html": artifacts.html.encode(),
        "pdf": artifacts.pdf,
    }
    for kind, filename in REPORT_FILES.items():
        store.save(contents[kind], name=blob_key(session_id, filename))
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
