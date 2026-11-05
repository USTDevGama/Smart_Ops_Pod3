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


class DemandConfig(BaseModel):
    """What the project needs, from the Gama team. The agent always knows it and compares it
    with each trainee's profile."""

    model_config = ConfigDict(extra="ignore")

    name: str
    description: str
    stack: list[str] = Field(default_factory=list)  # for example "Spring Boot", "React"
    expectations: list[str] = Field(min_length=1)  # what the client expects of the person


class EnvironmentSettings(BaseModel):
    """Per-environment defaults (the seed pack's config/stage|prod.settings.json)."""

    model_config = ConfigDict(extra="ignore")

    environment: str
    persona_file: str
    max_turns: int = Field(ge=1)


class DimensionConfig(BaseModel):
    key: str
    label: str
    weight: float = Field(ge=0, le=1)
    alpha: float = Field(default=0.4, ge=0, le=1)  # share of the code score in the blend


class BandCutoffs(BaseModel):
    """Placeholder cutoffs (not from the BRD): score >= value gets that band."""

    production_ready: float = 90
    enterprise_ready: float = 75
    needs_remediation: float = 50  # below this: not ready


class ScoringConfig(BaseModel):
    dimensions: list[DimensionConfig] = Field(min_length=1)
    band_cutoffs: BandCutoffs = Field(default_factory=BandCutoffs)
    agreement_gap: float = Field(default=25, ge=0, le=100)  # code-vs-LLM gap that flags a dimension
    min_findings_pass_rate: float = Field(default=0.8, ge=0, le=1)  # citations that must pass
    scoring_runs: int = Field(default=1, ge=1, le=5)
    pass_cutoff: float = Field(default=50, ge=0, le=100)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "ScoringConfig":
        total = sum(d.weight for d in self.dimensions)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"dimension weights must sum to 1 (got {total})")
        if len({d.key for d in self.dimensions}) != len(self.dimensions):
            raise ValueError("dimension keys must be unique")
        return self
