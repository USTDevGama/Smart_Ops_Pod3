"""Admin-editable settings. Stored as JSON inside `config_version.config`.

PersonaConfig, ScenarioConfig and EnvironmentSettings follow the shape of the program's seed
files. The seed pack itself is confidential and is never committed here: our own made-up
examples in the same shape live in samples/, and app/seed.py loads the real pack from a local
folder.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EscalationStep(BaseModel):
    step: int = Field(ge=1, le=4)
    move: str


class PersonaConfig(BaseModel):
    """The AI client: who they are, their rules and how they get tougher."""

    model_config = ConfigDict(extra="ignore")  # seed files carry extra bookkeeping fields

    name: str
    role: str
    style: str
    main_concerns: list[str] = Field(min_length=1)
    rules: list[str] = Field(default_factory=list)
    escalation_ladder: list[EscalationStep] = Field(min_length=1)
    version: str | None = None  # label such as "strict-1.0", echoed in the result
    dataset_ref: str | None = None  # traceability back to the seed pack
    # Our own tuning knobs. Not in the seed files; the defaults are placeholders.
    t_escalate: float = Field(default=0.5, ge=0, le=1)  # quality below this -> one step tougher
    t_deescalate: float = Field(default=0.7, ge=0, le=1)  # at/above this twice -> one step easier
    min_turns: int = Field(default=3, ge=1)
    max_turns: int = Field(default=8, ge=1)
    grace_turns: int = Field(default=0, ge=0)  # extra turns allowed while answers are improving

    @model_validator(mode="after")
    def _check(self) -> "PersonaConfig":
        steps = [s.step for s in self.escalation_ladder]
        if steps != sorted(set(steps)):
            raise ValueError("escalation_ladder steps must be unique and in order")
        if self.min_turns > self.max_turns:
            raise ValueError("min_turns cannot exceed max_turns")
        if self.t_deescalate < self.t_escalate:
            raise ValueError("t_deescalate must be >= t_escalate")
        return self

    @property
    def max_step(self) -> int:
        return max(s.step for s in self.escalation_ladder)


class ScenarioConfig(BaseModel):
    """The situation the client is upset about, and what a good answer must contain."""

    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    situation: str
    client_objections: list[str] = Field(min_length=1)
    good_answer_contains: list[str] = Field(min_length=1)  # the checklist for a good answer


class EnvironmentSettings(BaseModel):
    """Per-environment defaults (the seed pack's config/stage|prod.settings.json)."""

    model_config = ConfigDict(extra="ignore")

    environment: str
    persona_file: str
    max_turns: int = Field(ge=1)


class CriterionConfig(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    weight: float = Field(ge=0, le=1)
    signal_keys: list[str] = Field(default_factory=list)


class StatusCutoffs(BaseModel):
    partly: float = Field(default=0.3, ge=0, le=1)
    met: float = Field(default=0.7, ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> "StatusCutoffs":
        if self.partly >= self.met:
            raise ValueError("the partly cutoff must be below the met cutoff")
        return self


class ConfidenceConfig(BaseModel):
    evidence_weight: float = Field(default=0.4, ge=0, le=1)
    question_weight: float = Field(default=0.35, ge=0, le=1)
    margin_weight: float = Field(default=0.25, ge=0, le=1)
    status_margin: float = Field(default=0.1, gt=0, le=1)
    invalid_question_penalty: float = Field(default=10, ge=0, le=100)
    short_session_turns: int = Field(default=3, ge=1)
    short_session_cap: float = Field(default=60, ge=0, le=100)
    high_band: float = Field(default=75, ge=0, le=100)
    medium_band: float = Field(default=50, ge=0, le=100)

    @model_validator(mode="after")
    def _valid_ranges(self) -> "ConfidenceConfig":
        total = self.evidence_weight + self.question_weight + self.margin_weight
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"confidence weights must sum to 1 (got {total})")
        if self.question_weight + self.margin_weight == 0:
            raise ValueError("question and margin weights cannot both be zero")
        if self.medium_band >= self.high_band:
            raise ValueError("the medium confidence cutoff must be below the high cutoff")
        return self


class ScoringConfig(BaseModel):
    rubric_version: str = Field(min_length=1)
    criteria: list[CriterionConfig] = Field(min_length=1)
    status_cutoffs: StatusCutoffs = Field(default_factory=StatusCutoffs)
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)

    @model_validator(mode="after")
    def _valid_rubric(self) -> "ScoringConfig":
        total = sum(criterion.weight for criterion in self.criteria)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"criterion weights must sum to 1 (got {total})")
        if len({criterion.id for criterion in self.criteria}) != len(self.criteria):
            raise ValueError("criterion ids must be unique")
        return self
