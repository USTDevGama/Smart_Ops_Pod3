"""Value sets shared by the database models, the API and the agent code."""

from enum import StrEnum


class Role(StrEnum):
    TRAINEE = "trainee"
    ADMIN = "admin"
    INTEGRATOR = "integrator"


class ConfigKind(StrEnum):
    PERSONA = "persona"
    SCENARIO = "scenario"


class ConfigStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class FileType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"


class IngestStatus(StrEnum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    READY = "ready"
    FAILED = "failed"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"


class EndReason(StrEnum):
    TRAINEE_ENDED = "trainee_ended"
    TURN_CAP = "turn_cap"
    CONCERNS_RESOLVED = "concerns_resolved"
    TIME_LIMIT = "time_limit"
    ADMIN_ENDED = "admin_ended"


class TurnRole(StrEnum):
    PERSONA = "persona"
    TRAINEE = "trainee"


class AssessmentStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    FINALIZED = "finalized"
    FAILED = "failed"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Polarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    OVERRIDE = "override"


class ReportFormat(StrEnum):
    PDF = "pdf"
    HTML = "html"
