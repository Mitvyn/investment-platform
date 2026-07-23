"""Generic primary-source collection contracts for the biotech workflow."""

from .temporal import PublicationTimeAssessment, assess_publication_time

__all__ = ["PublicationTimeAssessment", "assess_publication_time"]
