"""Privacy Router extractor package.

The package contains the current pipeline compatibility surface and the new
backend-independent detector contract. ``LLMExtractor``, ``PresidioExtractor``,
``OPFExtractor``, and ``LFMExtractor`` all return ``DetectionResult`` objects
with normalized ``PrivacyEntity`` values. The current ``Extractor`` facade,
``ExtractorCore``, and ``Critic`` remain available until the planned Judge and
Router cutover.

No detector performs masking, unmasking, policy decisions, or persistence.
"""

from .critic import Critic
from .extractor import Extractor, extract
from .extractor_core import ExtractorCore, PrivacyAnalysisUnavailable, normalize_category
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
    ExtractionRecord,
    ExtractionResult,
    LFMDetectorRun,
    LLMDetectorRun,
    OPFDetectorRun,
    PresidioDetectorRun,
    PrivacyEntity,
    RecognizerDescriptor,
    Requiredness,
    Sensitivity,
    redact_extraction_records,
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
