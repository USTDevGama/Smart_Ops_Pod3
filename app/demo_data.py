"""Loads a small, made-up example so the tables are not empty when you browse them.

    uv run alembic upgrade head        # create the tables first
    uv run python -m app.demo_data     # then add the example rows

Every value comes from our own made-up files in samples/ (nothing from the confidential seed
pack). Ids are deterministic, so running it twice does not add duplicates. Local and dev
databases only.

The story: an admin uploaded the project demand document, and a trainee uploaded their profile
(resume). The trainee plays against Ms. Verma. The first chat is finished; the second is still
open. The scenarios are shared master data.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import models as m
from app.db.base import Base
from app.schemas import Evaluation, PersonaConfig, ScenarioConfig
from app.schemas.enums import (
    ConfigKind,
    ConfigStatus,
    EndReason,
    FileType,
    IngestStatus,
    SessionStatus,
    TurnRole,
)

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
_NAMESPACE = uuid.UUID("5b0f6a52-3c1e-4e0c-9a55-0c0de0000001")
_T0 = datetime(2026, 11, 3, 10, 0, 0, tzinfo=UTC)


def _id(name: str) -> uuid.UUID:
    """A fixed id per name, so the same example always gets the same ids."""
    return uuid.uuid5(_NAMESPACE, name)


def _at(minutes: float = 0, seconds: float = 0) -> datetime:
    return _T0 + timedelta(minutes=minutes, seconds=seconds)


def _load(relative: str) -> dict:
    return json.loads((SAMPLES / relative).read_text(encoding="utf-8"))


def row_counts(db: Session) -> dict[str, int]:
    return {
        t.name: db.scalar(select(func.count()).select_from(t)) or 0
        for t in Base.metadata.sorted_tables
    }


def load_demo_data(db: Session) -> dict[str, int]:
    """Adds the example rows (flushed, not committed). Returns the row count per table."""
    if db.get(m.ConfigVersion, _id("cfg-persona")) is not None:
        return row_counts(db)  # already loaded

    trainee_ref = "Demo Trainee"
    trainee_id = "T-DEMO-01"
    db.add(m.Trainee(trainee_id=trainee_id, display_name=trainee_ref))
    db.flush()

    # --- settings: persona and scenario (both validated by their schemas) ------------------
    persona_cfg = PersonaConfig.model_validate(_load("personas/ms_verma_strict.json"))
    scenario_cfg = ScenarioConfig.model_validate(
        _load("scenarios/vendor_delay.json")["scenarios"][0]
    )
    persona = m.ConfigVersion(
        id=_id("cfg-persona"), kind=ConfigKind.PERSONA, key="verma-strict", version_no=1,
        status=ConfigStatus.PUBLISHED, config=persona_cfg.model_dump(mode="json"),
        created_at=_at(-18),
    )
    scenario = m.ConfigVersion(
        id=_id("cfg-scenario"), kind=ConfigKind.SCENARIO, key="vendor-delay", version_no=1,
        status=ConfigStatus.PUBLISHED, config=scenario_cfg.model_dump(mode="json"),
        created_at=_at(-17),
    )
    db.add_all([persona, scenario])
    db.flush()

    # --- the demand document (admin) and a trainee profile; the extracted text is kept as JSON
    demand_raw = (SAMPLES / "demand" / "project_demand.txt").read_bytes()
    demand_sha = hashlib.sha256(demand_raw).hexdigest()
    demand = m.DemandDocument(
        id=_id("demand"), uploaded_by="demo-admin", filename="project_demand.txt",
        file_type=FileType.TXT, sha256=demand_sha, blob_uri=f"storage/{demand_sha[:12]}.txt",
        status=IngestStatus.READY, content={"text": demand_raw.decode("utf-8").strip()},
        created_at=_at(-16),
    )
    raw = (SAMPLES / "profiles" / "sample_resume.txt").read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    profile = m.Profile(
        id=_id("profile"), owner_ref=trainee_ref, filename="sample_resume.txt",
        trainee_id=trainee_id,
        file_type=FileType.TXT, sha256=sha, blob_uri=f"storage/{sha[:12]}.txt",
        status=IngestStatus.READY, content={"text": raw.decode("utf-8").strip()},
        created_at=_at(25),
    )
    db.add_all([demand, profile])
    db.flush()

    # --- two sessions on the profile: S1 finished, S2 still open -----------------------------
    s1 = m.RoleplaySession(
        id=_id("session-1"), trainee_ref=trainee_ref, profile_id=profile.id,
        trainee_id=trainee_id,
        persona_version_id=persona.id, demand_id=demand.id,
        status=SessionStatus.ENDED,
        end_reason=EndReason.TRAINEE_ENDED, started_at=_at(0), ended_at=_at(6),
    )
    s2 = m.RoleplaySession(
        id=_id("session-2"), trainee_ref=trainee_ref, profile_id=profile.id,
        trainee_id=trainee_id,
        persona_version_id=persona.id, demand_id=demand.id,
        status=SessionStatus.ACTIVE,
        started_at=_at(30),
    )
    db.add_all([s1, s2])
    db.flush()

    # --- the chat for S1 ------------------------------------------------------------------
    messages = [
        ("client", "The project is late again. Why was I not told earlier?"),
        (
            "trainee",
            "I should have raised the delay sooner. I found the supplier issue last Tuesday "
            "and own the late notice.",
        ),
        ("client", "I need a revised date, and what it will cost."),
        (
            "trainee",
            "We can deliver on 9 June after two extra days of testing. The delay adds 3 developer "
            "days, and our team absorbs that cost.",
        ),
        ("client", "How will you prevent this happening again?"),
    ]
    evaluations = {
        1: Evaluation(
            answer_quality=0.55,
            checklist_met=scenario_cfg.good_answer_contains[:1],
            composure=0.9,
            quote="own the late notice",
            proposed_level=3,
        ),
        3: Evaluation(
            answer_quality=0.85,
            checklist_met=scenario_cfg.good_answer_contains[:2],
            composure=0.9,
            quote="9 June",
            proposed_level=2,
        ),
    }
    levels = {0: 2, 2: 3, 4: 3}  # the client's step in each of its replies
    turns: dict[int, m.Turn] = {}
    for idx, (role, text) in enumerate(messages):
        is_client = role == "client"
        if idx in evaluations:  # the quote must really be in the message
            assert evaluations[idx].quote in text
        turns[idx] = m.Turn(
            id=_id(f"s1-turn-{idx}"), session_id=s1.id, idx=idx,
            role=TurnRole.PERSONA if is_client else TurnRole.TRAINEE, content=text,
            escalation_level=levels[idx] if is_client else None,
            evaluation=evaluations[idx].model_dump(mode="json") if idx in evaluations else None,
            idempotency_key=None if is_client else f"k-{idx:04d}",
            created_at=_at(0, 10 + 70 * idx),
        )
    s2_opening = m.Turn(
        id=_id("s2-turn-0"), session_id=s2.id, idx=0, role=TurnRole.PERSONA, escalation_level=1,
        content=("Your resume says the payments service shipped two weeks late, and our invoicing "
                 "release is due in ten days. Why should I believe this one will be on time?"),
        created_at=_at(30, 5),
    )
    db.add_all([*turns.values(), s2_opening])
    db.flush()

    db.flush()
    return row_counts(db)


def main() -> None:
    settings = get_settings()
    if settings.env not in ("local", "dev"):
        raise SystemExit(f"Refusing to load demo data when PODC_ENV={settings.env!r}")
    from app.db.session import get_engine

    with Session(get_engine()) as db:
        counts = load_demo_data(db)
        db.commit()
    print(f"Demo data is in {settings.database_url}")
    for table, count in counts.items():
        print(f"  {table:<22} {count} rows")


if __name__ == "__main__":
    main()
