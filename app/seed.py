"""Loads the program's seed pack from a local folder.

The pack is UST CONFIDENTIAL practice data ("do not copy outside the project"), and this repo
is public, so the pack must live OUTSIDE the repo. Point PODC_SEED_DIR at it. Everything is
validated against our own schemas, which also tells us early if the pack and our model drift.
"""

import json
from pathlib import Path

from app.config import get_settings
from app.schemas import EnvironmentSettings, PersonaConfig, RoleplayResult, ScenarioConfig


def seed_dir() -> Path | None:
    configured = get_settings().seed_dir
    return Path(configured) if configured else None


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_persona(path: Path) -> PersonaConfig:
    return PersonaConfig.model_validate(_read(path))


def load_scenarios(path: Path) -> list[ScenarioConfig]:
    return [ScenarioConfig.model_validate(s) for s in _read(path)["scenarios"]]


def load_environment_settings(path: Path) -> EnvironmentSettings:
    return EnvironmentSettings.model_validate(_read(path))


def load_result(path: Path) -> RoleplayResult:
    return RoleplayResult.model_validate(_read(path))
