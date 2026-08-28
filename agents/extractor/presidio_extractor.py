from __future__ import annotations

from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from threading import Lock
from typing import Any

from .normalizer import EntityNormalizer
from .parsers import DetectorParseError, PresidioParser
from .schemas import (
    DetectionResult,
    DetectorRunProvenance,
    PresidioDetectorRun,
    RecognizerDescriptor,
)

_ADAPTER_VERSION = "privacy-router-presidio-adapter-v1-0-0"
_DEFAULT_DETECTOR_ID = "microsoft-presidio-analyzer-v2-2-358"


class PresidioExtractor:
    """Extract structural privacy entities with Microsoft Presidio Analyzer."""

    def __init__(
        self,
        *,
        analyzer: Any | None = None,
        language: str = "en",
        entities: Sequence[str] | None = None,
        normalizer: EntityNormalizer | None = None,
    ) -> None:
        self._analyzer = analyzer
        self._analyzer_lock = Lock()
        self._language = language
        self._entities = list(entities) if entities is not None else None
        self._normalizer = normalizer or EntityNormalizer()

    def extract(self, text: str) -> DetectionResult:
        """Run Presidio and return normalized detector output."""
        analyzer = self._analyzer
        try:
            analyzer = self._get_analyzer()
            run = self._new_run(analyzer)
            raw = analyzer.analyze(
                text=text,
                entities=self._entities,
                language=self._language,
                return_decision_process=True,
            )
            candidates = PresidioParser().parse(raw, text)
            return self._normalizer.normalize(text, candidates, run)
        except (DetectorParseError, ValueError, RuntimeError, TypeError) as exc:
            run = self._new_run(analyzer)
            return self._failed(run, "PRESIDIO_BACKEND_ERROR", str(exc))
        except Exception as exc:  # pragma: no cover - defensive optional-backend boundary
            run = self._new_run(analyzer)
            return self._failed(run, "PRESIDIO_BACKEND_ERROR", str(exc))

    def _get_analyzer(self) -> Any:
        analyzer = self._analyzer
        if analyzer is not None:
            return analyzer
        with self._analyzer_lock:
            analyzer = self._analyzer
            if analyzer is None:
                analyzer = self._load_analyzer()
                self._analyzer = analyzer
        return analyzer

    @staticmethod
    def _load_analyzer() -> Any:
        try:
            from presidio_analyzer import AnalyzerEngine
        except ImportError as exc:  # pragma: no cover - depends on optional installation
            raise RuntimeError("Install presidio-analyzer to use PresidioExtractor") from exc
        return AnalyzerEngine()

    def _new_run(self, analyzer: Any | None) -> PresidioDetectorRun:
        package_version = _package_version()
        detector_id = _detector_id(package_version)
        return PresidioDetectorRun(
            detector_type="presidio",
            detector_id=detector_id,
            status="complete",
            external_opt_in=False,
            adapter_version=_ADAPTER_VERSION,
            configured_recognizers=_configured_recognizers(
                analyzer,
                language=self._language,
                entities=self._entities,
            ),
            package_version=package_version,
        )

    @staticmethod
    def _failed(run: DetectorRunProvenance, error_code: str, message: str) -> DetectionResult:
        failed = run.model_copy(update={"status": "failed", "error_code": error_code})
        return DetectionResult(
            status="failed",
            entities=[],
            detector_runs=[failed],
            diagnostics={"errors": [message]},
        )


def _package_version() -> str | None:
    try:
        return version("presidio-analyzer")
    except PackageNotFoundError:
        return None


def _detector_id(package_version: str | None) -> str:
    if not package_version:
        return _DEFAULT_DETECTOR_ID
    normalized = "-".join(part for part in package_version.split(".") if part)
    return f"microsoft-presidio-analyzer-v{normalized}"


def _configured_recognizers(
    analyzer: Any | None,
    *,
    language: str,
    entities: list[str] | None,
) -> list[RecognizerDescriptor]:
    registry = getattr(analyzer, "registry", None)
    get_recognizers = getattr(registry, "get_recognizers", None)
    if not callable(get_recognizers):
        return []

    descriptors: list[RecognizerDescriptor] = []
    for recognizer in get_recognizers(language=language, entities=entities, all_fields=True):
        name = getattr(recognizer, "name", None) or type(recognizer).__name__
        identifier = getattr(recognizer, "id", None) or getattr(recognizer, "identifier", None)
        recognizer_version = getattr(recognizer, "version", None)
        descriptors.append(
            RecognizerDescriptor(
                name=str(name),
                identifier=str(identifier) if identifier is not None else None,
                version=str(recognizer_version) if recognizer_version is not None else None,
            )
        )
    return descriptors
