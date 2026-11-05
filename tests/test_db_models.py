import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.db.base import Base
from app.db.models import (
    ConfigVersion,
    Profile,
    RoleplaySession,
    Turn,
)
from app.schemas.enums import (
    ConfigKind,
    ConfigStatus,
    FileType,
    ProfileStatus,
    SessionStatus,
    TurnRole,
)

EXPECTED_TABLES = {"config_version", "profile", "profile_segment", "session", "turn"}


def test_exactly_the_planned_tables():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_every_table_compiles_for_postgres():
    for table in Base.metadata.sorted_tables:
        assert "CREATE TABLE" in str(CreateTable(table).compile(dialect=postgresql.dialect()))


def _chain(db, with_profile: bool = True) -> tuple[RoleplaySession, Turn]:
    persona = ConfigVersion(
        kind=ConfigKind.PERSONA, key="verma", version_no=1, status=ConfigStatus.PUBLISHED, config={}
    )
    scenario = ConfigVersion(
        kind=ConfigKind.SCENARIO,
        key="vendor-delay",
        version_no=1,
        status=ConfigStatus.PUBLISHED,
        config={},
    )
    db.add_all([persona, scenario])
    db.flush()
    profile_id = None
    if with_profile:
        profile = Profile(
            owner_ref="dev-user",
            filename="p.txt",
            file_type=FileType.TXT,
            sha256="0" * 64,
            blob_uri="storage/p.txt",
            status=ProfileStatus.READY,
        )
        db.add(profile)
        db.flush()
        profile_id = profile.id
    session = RoleplaySession(
        trainee_ref="dev-user",
        profile_id=profile_id,
        persona_version_id=persona.id,
        scenario_version_id=scenario.id,
        status=SessionStatus.ACTIVE,
    )
    db.add(session)
    db.flush()
    turn = Turn(session_id=session.id, idx=1, role=TurnRole.TRAINEE, content="Labour is $280k")
    db.add(turn)
    db.flush()
    return session, turn


def test_turn_index_is_unique_per_session(db):
    session, _ = _chain(db)
    db.add(Turn(session_id=session.id, idx=1, role=TurnRole.PERSONA, content="dup"))
    with pytest.raises(IntegrityError):
        db.flush()


@pytest.mark.parametrize("bad_level", [0, 5, 9])
def test_escalation_level_is_limited_to_steps_1_to_4(db, bad_level):
    session, _ = _chain(db)
    db.add(
        Turn(
            session_id=session.id,
            idx=2,
            role=TurnRole.PERSONA,
            content="x",
            escalation_level=bad_level,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_a_session_can_run_without_a_profile(db):
    session, _ = _chain(db, with_profile=False)
    assert session.profile_id is None
