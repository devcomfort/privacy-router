"""OpenAI Privacy Filter privacy extractor."""

from __future__ import annotations

from threading import Lock
from typing import Any

from ..normalizer import EntityNormalizer
from ..schemas import DetectionResult, DetectorRunProvenance, OPFDetectorRun
from .parser import DetectorParseError, OPFParser

_ADAPTER_VERSION = "privacy-router-opf-adapter-v1-0-0"
_DETECTOR_ID = "openai-privacy-filter-v1-0-0"
_MODEL_ID = "openai/privacy-filter"


class OPFExtractor:
    """Extract structural privacy entities with OpenAI Privacy Filter."""

    def __init__(
        self,
        *,
        opf: Any | None = None,
        model: str | None = None,
        device: str = "cpu",
        decode_mode: str = "viterbi",
        normalizer: EntityNormalizer | None = None,
    ) -> None:
        """Configure the typed OPF runtime.

        Args:
            opf: Optional initialized OPF runtime. When omitted, OPF is loaded
                lazily on first extraction.
            model: Optional OPF checkpoint path.
            device: Runtime device, such as ``"cpu"`` or ``"cuda"``.
            decode_mode: OPF decode mode.
            normalizer: Injectable candidate normalizer.
        """
        self._opf = opf
        self._opf_lock = Lock()
        self._model = model
        self._device = device
        self._decode_mode = decode_mode
        self._normalizer = normalizer or EntityNormalizer()

    def extract(self, text: str) -> DetectionResult:
        """Extract typed entities with OPF without applying masking.

        Args:
            text: Original input text.

        Returns:
            Normalized entities, run provenance, and diagnostics.
        """
        opf = self._opf
        try:
            opf = self._get_opf()
            run = self._new_run(opf)
            raw = opf.redact(text)
            candidates = OPFParser().parse(raw, text)
            return self._normalizer.normalize(text, candidates, run)
        except (DetectorParseError, ValueError, RuntimeError, TypeError) as exc:
            run = self._new_run(opf)
            return self._failed(run, "OPF_BACKEND_ERROR", str(exc))
        except Exception as exc:  # pragma: no cover - defensive optional-backend boundary
            run = self._new_run(opf)
            return self._failed(run, "OPF_BACKEND_ERROR", str(exc))

    def _get_opf(self) -> Any:
        opf = self._opf
        if opf is not None:
            return opf
        with self._opf_lock:
            opf = self._opf
            if opf is None:
                opf = self._load_opf()
                self._opf = opf
        return opf

    def _load_opf(self) -> Any:
        try:
            from opf import OPF
        except ImportError as exc:  # pragma: no cover - depends on optional installation
            raise RuntimeError("Install OpenAI Privacy Filter to use OPFExtractor") from exc
        return OPF(
            model=self._model,
            device=self._device,
            output_mode="typed",
            decode_mode=self._decode_mode,
        )

    def _new_run(self, opf: Any | None = None) -> OPFDetectorRun:
        decoder_config = getattr(opf, "_decoder_config", None)
        configured_mode = getattr(decoder_config, "decode_mode", None)
        decode_mode = configured_mode if configured_mode in {"viterbi", "argmax"} else self._decode_mode
        return OPFDetectorRun(
            detector_type="opf",
            detector_id=_DETECTOR_ID,
            status="complete",
            external_opt_in=False,
            adapter_version=_ADAPTER_VERSION,
            model_id=_MODEL_ID,
            model_revision=self._model,
            output_mode="typed",
            decode_mode=decode_mode,
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
