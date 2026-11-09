import pytest

from app.config import Settings
from app.llm import FakeLLM, LLMError, LLMRequest, Message, ProviderLLM, get_llm_client
from app.schemas import Evaluation, TurnOutput


def _request(purpose: str = "turn", schema=None) -> LLMRequest:
    return LLMRequest(
        purpose=purpose,
        system="You are Meera.",
        messages=[Message(role="user", content="We'll manage it efficiently.")],
        response_schema=schema,
    )


def test_scripted_replies_come_back_in_order_and_calls_are_recorded():
    llm = FakeLLM({"turn": ["first", "second"]})
    assert llm.complete(_request()).text == "first"
    assert llm.complete(_request()).text == "second"
    assert len(llm.calls) == 2


def test_structured_reply_is_parsed():
    reply = TurnOutput(
        evaluation=Evaluation(answer_quality=0.2, quote="efficiently", proposed_level=1),
        reply="'Efficiently' isn't a number.",
    )
    result = FakeLLM({"turn": [reply]}).complete(_request(schema=TurnOutput))
    assert isinstance(result.parsed, TurnOutput)
    assert result.parsed.evaluation.proposed_level == 1


def test_reply_that_does_not_match_the_schema_raises():
    with pytest.raises(LLMError):
        FakeLLM({"turn": ['{"nope": 1}']}).complete(_request(schema=TurnOutput))


def test_strict_mode_fails_when_the_script_runs_out():
    with pytest.raises(LLMError):
        FakeLLM().complete(_request())


def test_stream_yields_the_reply_in_pieces():
    assert "".join(FakeLLM({"turn": ["hello there"]}).stream(_request())).strip() == "hello there"


def test_factory_returns_fake_by_default_and_the_real_client_for_other_providers():
    # _env_file=None: never read a developer's real .env (it may hold a live key) in a test
    assert isinstance(get_llm_client(Settings(_env_file=None, llm_provider="fake")), FakeLLM)
    other = Settings(_env_file=None, llm_provider="anything-else")
    assert isinstance(get_llm_client(other), ProviderLLM)
    with pytest.raises(LLMError, match="no model key"):  # no key configured, so no call is made
        ProviderLLM(other).complete(_request())
