"""The scoring model call: one finished chat in, a checked `ScoringOutput` out.

    score_session(llm, config, transcript)
      1. build the prompt   prompts.py     rubric (id, label) in `system`, chat as fenced data
      2. ONE model call     LLMClient      purpose="score", reply validated as ScoringOutput
      3. check the result   _check         what `build_assessment` would otherwise reject later
      4. return             ScoringOutput  weighted score and confidence: `processor.py`'s job

The model only judges. It never sees weights, cutoffs or code signals. A normal run is one call,
with exactly one retry when the result is unusable (a reply that does not match the schema,
criteria that differ from the rubric, or a citation of an exchange without a trainee reply).
After that, `ScoringError` is raised and nothing is guessed. Errors and logs carry reason codes
only, never the conversation or the model's text (BR-13).
"""

import logging

from app.llm.base import LLMClient, LLMError, LLMRequest, Message
from app.schemas import ScoringConfig, ScoringOutput
from app.scoring import prompts
from app.scoring.transcript import ScoringInputError, Transcript

log = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 1500


class ScoringError(Exception):
    """The model's reply could not be used, even after the one retry."""


class _Rejected(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def score_session(
    llm: LLMClient,
    config: ScoringConfig,
    transcript: Transcript,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> ScoringOutput:
    if not transcript.trainee_numbers:
        raise ScoringInputError("the trainee gave no answer, so there is nothing to score")

    system = prompts.system_prompt(config)
    user = prompts.user_message(transcript)
    code = ""
    for attempt in (1, 2):
        message = user if attempt == 1 else user + prompts.retry_note(code)
        try:
            output = _call(llm, system, message, max_tokens)
            _check(output, config, transcript)
        except _Rejected as bad:
            code = bad.code
        except LLMError as failure:
            # The client raises LLMError for a failed call and for a schema mismatch alike.
            code = "schema"
            # A reason code only (never the prompt or the model's text), so it is safe to log.
            log.warning("scoring attempt %d: %s", attempt, failure)
        else:
            log.info("scoring ok (attempt %d, prompt %s)", attempt, prompts.PROMPT_VERSION)
            return output
        log.warning("scoring attempt %d rejected: %s", attempt, code)
    raise ScoringError(f"the model's reply could not be used ({code})")


def _call(llm: LLMClient, system: str, user: str, max_tokens: int) -> ScoringOutput:
    request = LLMRequest(
        purpose="score",
        system=system,
        messages=[Message(role="user", content=user)],
        response_schema=ScoringOutput,
        max_tokens=max_tokens,
    )
    response = llm.complete(request)
    if not isinstance(response.parsed, ScoringOutput):
        raise _Rejected("schema")
    log.info("scoring call tokens_in=%s tokens_out=%s", response.tokens_in, response.tokens_out)
    return response.parsed


def _check(output: ScoringOutput, config: ScoringConfig, transcript: Transcript) -> None:
    if {c.id for c in output.criteria} != {c.id for c in config.criteria}:
        raise _Rejected("criteria_mismatch")

    replies = transcript.trainee_numbers
    for criterion in output.criteria:
        if any(item.turn not in replies for item in criterion.evidence):
            raise _Rejected("bad_evidence_turn")
    for note in [*output.strengths, *output.gaps]:
        if any(turn not in replies for turn in note.evidence_turns):
            raise _Rejected("bad_note_turn")
