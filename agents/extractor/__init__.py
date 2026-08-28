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
from .lfm_extractor import LFMExtractor
from .llm_extractor import LLMExtractionOutput, LLMExtractor, LLMRecord
from .normalizer import EntityNormalizer, SpanReconciliationError
from .opf_extractor import OPFExtractor
from .parser import DetectorParser, ParsedEntity
from .parsers import DetectorParseError, LFMParser, LLMParser, OPFParser, PresidioParser
from .presidio_extractor import PresidioExtractor
from .registry import DetectorRegistry, PrivacyExtractor
from .schemas import (
    DetectionResult,
    DetectorRunBase,
    DetectorRunProvenance,
    LFMDetectorRun,
    LLMDetectorRun,
    OPFDetectorRun,
    PrivacyEntity,
    PresidioDetectorRun,
    RecognizerDescriptor,
    Requiredness,
)

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
    # detector contract
    "Requiredness",
    "PrivacyEntity",
    "DetectionResult",
    "DetectorRunBase",
    "DetectorRunProvenance",
    "LLMDetectorRun",
    "PresidioDetectorRun",
    "OPFDetectorRun",
    "LFMDetectorRun",
    "RecognizerDescriptor",
    "ParsedEntity",
    "DetectorParser",
    "DetectorParseError",
    "EntityNormalizer",
    "SpanReconciliationError",
    "LLMRecord",
    "LLMExtractionOutput",
    "LLMExtractor",
    "PresidioParser",
    "PresidioExtractor",
    "OPFParser",
    "OPFExtractor",
    "LFMParser",
    "LFMExtractor",
    "PrivacyExtractor",
    "DetectorRegistry",
]
