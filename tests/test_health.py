import pytest
from fastapi.testclient import TestClient

from app.api import health
from app.config import Settings
from app.main import app, create_app

client = TestClient(app)


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_meta_has_registration_info():
    body = client.get("/api/v1/meta").json()
    assert body["name"] == "pod-c-stakeholder-roleplay"
    assert body["signal_schema_version"] == "1.0"
    assert body["fallback_mode"] is False


def test_readyz_reflects_database(monkeypatch):
    monkeypatch.setattr(health.db_session, "check_database", lambda: True)
    assert client.get("/readyz").status_code == 200
    monkeypatch.setattr(health.db_session, "check_database", lambda: False)
    assert client.get("/readyz").status_code == 503


def test_dev_auth_refused_outside_local_and_dev(monkeypatch):
    monkeypatch.setattr(
        "app.main.get_settings", lambda: Settings(env="prod", dev_auth_enabled=True)
    )
    with pytest.raises(RuntimeError):
        create_app()
