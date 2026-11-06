import pytest

from app.agent.engine import get_engine
from app.main import app
from tests.ui.support import ScriptedEngine


@pytest.fixture
def engine():
    """`engine([...])` makes the API use a scripted agent for the rest of the test."""

    def use(outputs) -> ScriptedEngine:
        scripted = ScriptedEngine(outputs)
        app.dependency_overrides[get_engine] = lambda: scripted
        return scripted

    yield use
    app.dependency_overrides.pop(get_engine, None)
