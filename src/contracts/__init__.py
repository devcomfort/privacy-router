"""Privacy Router shared data contracts."""

from .annotation import IntentAnnotation
from .extraction import (
    ConfidentialityJudgment,
    ExtractionRecord,
    ExtractionResult,
    NecessityJudgment,
    Sensitivity,
    redact_extraction_records,
)
from .masking import HydrationResult, MaskingContract, MaskingResult

__all__ = [
    "ExtractionRecord",
    "ExtractionResult",
    "HydrationResult",
    "IntentAnnotation",
    "MaskingContract",
    "MaskingResult",
    "ConfidentialityJudgment",
    "NecessityJudgment",
    "Sensitivity",
    "redact_extraction_records",
]
