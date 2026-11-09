"""The fixed scoring rubric: four criteria that apply to every scenario.

The criteria and weights are not admin-editable. `samples/scoring/default.json` mirrors this
rubric and a test keeps the two equal. Weights, cutoffs and signal keys stay hidden from the
scoring model (see `app/scoring/prompts.py`); it sees each label and description only.
"""

from app.schemas.config import ConfidenceConfig, CriterionConfig, ScoringConfig
from app.scoring.signals import COMMITS, COMPOSED, GROUNDED, SPECIFIC

RUBRIC_VERSION = "r2"

CRITERIA = (
    CriterionConfig(
        id="C1",
        label="Answers directly and specifically",
        description=(
            "Answers the question asked, with concrete facts, figures, dates or examples. "
            "Does not deflect, ramble, or repeat keywords without substance."
        ),
        weight=0.25,
        signal_keys=[SPECIFIC],
    ),
    CriterionConfig(
        id="C2",
        label="Holds up under pressure",
        description=(
            "Stays composed and professional as the client escalates. Does not turn defensive "
            "or cave. Improves the answer after a push, and does not over-promise just to end "
            "the pressure."
        ),
        weight=0.30,
        signal_keys=[COMPOSED],
    ),
    CriterionConfig(
        id="C3",
        label="Credible and consistent",
        description=(
            "Claims match the trainee's own resume and the project proposal. Is honest about "
            "limits, gaps and trade-offs, and does not invent experience or hide what they do "
            "not know."
        ),
        weight=0.25,
        signal_keys=[GROUNDED],
    ),
    CriterionConfig(
        id="C4",
        label="Takes ownership and offers a next step",
        description=(
            "Owns the issue, and offers a concrete action, option or commitment the client can "
            "hold them to."
        ),
        weight=0.20,
        signal_keys=[COMMITS],
    ),
)


def default_scoring_config() -> ScoringConfig:
    return ScoringConfig(
        rubric_version=RUBRIC_VERSION,
        criteria=[criterion.model_copy() for criterion in CRITERIA],
        confidence=ConfidenceConfig(),
    )


def prompt_config(config: ScoringConfig) -> ScoringConfig:
    """A copy whose labels carry the descriptions, for the scoring prompt only.

    The prompt shows each criterion's id and label. Putting the description in the label gets it
    to the model without changing the prompt code. The report keeps using the original config.
    """
    criteria = [
        criterion.model_copy(
            update={
                "label": f"{criterion.label}. {criterion.description}"
                if criterion.description
                else criterion.label
            }
        )
        for criterion in config.criteria
    ]
    return config.model_copy(update={"criteria": criteria})
