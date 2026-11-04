import pytest
from sqlalchemy import select

from app import demo_data
from app.config import Settings
from app.db import models as m
from app.db.base import Base

EXPECTED = {
    "config_version": 2, "proposal": 1, "proposal_segment": 2, "session": 2, "turn": 6,
}


def test_every_table_gets_example_rows(db):
    counts = demo_data.load_demo_data(db)
    assert counts == EXPECTED
    assert set(counts) == set(Base.metadata.tables)


def test_running_it_twice_adds_nothing(db):
    demo_data.load_demo_data(db)
    assert demo_data.load_demo_data(db) == EXPECTED


def test_the_persona_cites_a_real_proposal_chunk(db):
    demo_data.load_demo_data(db)
    citing = [t for t in db.scalars(select(m.Turn)) if t.refs]
    segment_ids = {str(s) for s in db.scalars(select(m.ProposalSegment.id))}
    assert len(citing) == 1
    assert set(citing[0].refs) <= segment_ids


def test_empty_json_values_are_real_nulls(db):
    demo_data.load_demo_data(db)
    session_id = demo_data._id("session-1")
    trainee_turn = db.scalar(
        select(m.Turn).where(m.Turn.idx == 1, m.Turn.session_id == session_id)
    )
    assert trainee_turn.refs is None
    assert db.scalar(select(m.Turn.id).where(m.Turn.id == trainee_turn.id, m.Turn.refs.is_(None)))


def test_refuses_to_run_outside_local_and_dev(monkeypatch):
    monkeypatch.setattr(demo_data, "get_settings", lambda: Settings(env="prod"))
    with pytest.raises(SystemExit):
        demo_data.main()
