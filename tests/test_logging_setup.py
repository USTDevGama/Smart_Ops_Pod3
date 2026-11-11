import logging

from app.config import Settings
from app.main import configure_logging


def test_the_log_level_setting_is_passed_to_the_root_logger(monkeypatch):
    seen = {}
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: seen.update(kwargs))

    configure_logging("debug")

    assert seen["level"] == "DEBUG"


def test_the_default_log_level_shows_the_app_info_lines():
    assert Settings().log_level == "INFO"
