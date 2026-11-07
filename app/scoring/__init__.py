"""Scoring pipeline (owner: Dev C): criterion validation, signals, weighted score, confidence.

`ScoringOutput` is the raw scoring-model response. Code validates its exchange citations and
combines it with the versioned rubric and validation signals to produce an `Assessment`.
"""

from app.scoring.processor import ScoringValidationContext, build_assessment

__all__ = ["ScoringValidationContext", "build_assessment"]
