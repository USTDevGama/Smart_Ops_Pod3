"""Compatibility name for the shared, validated assessment report contract."""

from app.schemas.assessment import Assessment as ValidatedAssessment
from app.schemas.assessment import ScoringNote as ReportNote

__all__ = ["ReportNote", "ValidatedAssessment"]
