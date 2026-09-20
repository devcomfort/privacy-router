"""Privacy Router extractor package.

The package contains the extraction facade and backend-independent detector
contract. ``LLMExtractor``, ``PresidioExtractor``, ``OPFExtractor``, and
``LFMExtractor`` all return ``DetectionResult`` objects with normalized
``PrivacyEntity`` values. ``Extractor`` uses ``ExtractorCore`` for single-pass
extraction.

No detector performs masking, unmasking, policy decisions, or persistence.
"""

from .extractor import Extractor, extract
from .extractor_core import ExtractorCore, PrivacyAnalysisUnavailable, normalize_category
from .lfm import LFMExtractor, LFMParser
from .llm import LLMExtractionOutput, LLMExtractor, LLMParser, LLMRecord
from .normalizer import EntityNormalizer, SpanReconciliationError
from .opf import OPFExtractor, OPFParser
from .parser import DetectorParseError, DetectorParser, ParsedEntity
from .presidio import PresidioExtractor, PresidioParser
from .registry import DetectorRegistry, PrivacyExtractor
from .schemas import (
    ConfidentialityJudgment,
    DetectionResult,
    DetectorRunBase,
    DetectorRunProvenance,
    ExtractionRecord,
    ExtractionResult,
    LFMDetectorRun,
    LLMDetectorRun,
    NecessityJudgment,
    OPFDetectorRun,
    PresidioDetectorRun,
    PrivacyEntity,
    RecognizerDescriptor,
    Sensitivity,
    redact_extraction_records,
)

__all__ = [
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
    "ConfidentialityJudgment",
    "NecessityJudgment",
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
    "LLMParser",
    "PresidioParser",
    "PresidioExtractor",
    "OPFParser",
    "OPFExtractor",
    "LFMParser",
    "LFMExtractor",
    "PrivacyExtractor",
    "DetectorRegistry",
]
