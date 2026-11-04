"""The hand-written migrations must produce exactly the schema the models describe."""

import uuid

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.db.base import Base
from tests.conftest import ROOT


def _config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_first_migration_downgrades_cleanly(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "0001")
    command.downgrade(cfg, "base")
    remaining = set(inspect(create_engine(url)).get_table_names()) - {"alembic_version"}
    assert remaining == set()


def test_upgrade_matches_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    command.upgrade(_config(url), "head")

    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert tables == {"config_version", "proposal", "proposal_segment", "session", "turn"}


def test_trim_keeps_existing_rows_and_turns_user_links_into_text(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "0001")
    user, persona, scenario, scoring, session = (str(uuid.uuid4()) for _ in range(5))
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO app_user (id, idp_sub) VALUES (:id, 'dev-anna')"),
                     {"id": user})
        for cid, kind, key in ((persona, "persona", "p"), (scenario, "scenario", "s"),
                               (scoring, "scoring_profile", "default")):
            conn.execute(
                text("INSERT INTO config_version (id, kind, key, version_no, status, config) "
                     "VALUES (:id, :kind, :key, 1, 'published', '{}')"),
                {"id": cid, "kind": kind, "key": key},
            )
        conn.execute(
            text("INSERT INTO session (id, trainee_id, persona_version_id, scenario_version_id, "
                 "scoring_profile_version_id, status) "
                 "VALUES (:id, :u, :p, :s, :sc, 'active')"),
            {"id": session, "u": user, "p": persona, "s": scenario, "sc": scoring},
        )

    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT trainee_ref FROM session")).scalar_one() == "dev-anna"
        kinds = {r[0] for r in conn.execute(text("SELECT kind FROM config_version"))}
    assert kinds == {"persona", "scenario"}  # the scoring-profile row is gone
