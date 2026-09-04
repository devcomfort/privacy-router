"""Privacy Router shared data contracts."""

from .extraction import ExtractionRecord, ExtractionResult, Requiredness, Sensitivity, redact_extraction_records
from .judgment import Judgment, MeaningfulnessAssessment
from .masking import HydrationResult, MaskingContract, MaskingResult
from .routing import (
    ChatChoice,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatUsage,
    PipelineResult,
    PlaceholderRepairDecision,
    RouteResult,
)

__all__ = [
    "ChatChoice",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ChatUsage",
    "ExtractionRecord",
    "ExtractionResult",
    "HydrationResult",
    "Judgment",
    "MeaningfulnessAssessment",
    "MaskingContract",
    "MaskingResult",
    "PipelineResult",
    "PlaceholderRepairDecision",
    "Requiredness",
    "RouteResult",
    "Sensitivity",
    "redact_extraction_records",
]
