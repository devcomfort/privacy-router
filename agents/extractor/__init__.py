"""Privacy Router — Extractor package.

SLM-based sensitive information detection.  The Extractor analyses
raw text and returns structured :class:`ExtractionResult` objects
that feed into the Judge.

Public API
----------
Extractor
    Main detection class.
ExtractionResult
    Full output of the extraction phase.
ExtractionRecord
    A single detected sensitive span.
Sensitivity
    Assessment of whether sensitive information was found.
extract
    Module-level convenience function that reuses a global instance.

Examples
--------
>>> from agents.extractor import extract
>>> result = extract("주민등록번호 901212-1234567")
>>> result.sensitivity.is_sensitive
True
"""

from .critic import Critic
from .extractor import Extractor, extract
from .extractor_core import ExtractorCore, PrivacyAnalysisUnavailable, normalize_category
from .schemas import ExtractionRecord, ExtractionResult, Sensitivity, redact_extraction_records

__all__ = [
    "Critic",
    "ExtractorCore",
    "PrivacyAnalysisUnavailable",
    "Extractor",
    "ExtractionResult",
    "ExtractionRecord",
    "Sensitivity",
    "normalize_category",
    "redact_extraction_records",
    "extract",
]
