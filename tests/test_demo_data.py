import pytest
from sqlalchemy import select

from app import demo_data
from app.config import Settings
from app.db import models as m
from app.db.base import Base

EXPECTED = {
    "config_version": 2, "demand_document": 1, "profile": 1, "session": 2, "turn": 6,
}


def test_every_table_gets_example_rows(db):
    counts = demo_data.load_demo_data(db)
    assert counts == EXPECTED
    assert set(counts) == set(Base.metadata.tables)


def test_running_it_twice_adds_nothing(db):
    demo_data.load_demo_data(db)
    assert demo_data.load_demo_data(db) == EXPECTED


def test_the_uploads_have_extracted_content_and_sessions_use_them(db):
    demo_data.load_demo_data(db)
    demand = db.get(m.DemandDocument, demo_data._id("demand"))
    profile = db.get(m.Profile, demo_data._id("profile"))
    assert "ten days" in demand.content["text"]
    assert "payments service" in profile.content["text"]
    sessions = db.scalars(select(m.RoleplaySession)).all()
    assert {s.demand_id for s in sessions} == {demand.id}
    assert {s.profile_id for s in sessions} == {profile.id}


def test_empty_json_values_are_real_nulls(db):
    demo_data.load_demo_data(db)
    session_id = demo_data._id("session-1")
    client_turn = db.scalar(
        select(m.Turn).where(m.Turn.idx == 0, m.Turn.session_id == session_id)
    )
    assert client_turn.evaluation is None  # only trainee turns are judged
    assert db.scalar(
        select(m.Turn.id).where(m.Turn.id == client_turn.id, m.Turn.evaluation.is_(None))
    )


def test_refuses_to_run_outside_local_and_dev(monkeypatch):
    monkeypatch.setattr(demo_data, "get_settings", lambda: Settings(env="prod"))
    with pytest.raises(SystemExit):
        demo_data.main()
