from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from threading import Lock

from ..normalizer import EntityNormalizer
from ..schemas import DetectionResult, DetectorRunProvenance, LFMDetectorRun
from .parser import DetectorParseError, LFMParser

_ADAPTER_VERSION = "privacy-router-lfm-adapter-v1-0-0"
_DETECTOR_ID = "liquidai-lfm2-5-encoder-350m-pii-detector-v1-0-0"
_DEFAULT_MODEL_ID = "LiquidAI/LFM2.5-Encoder-350M-PII-Detector"
_DEFAULT_MODEL_REVISION = "b8c9cf3d2d6ae52501b35a27ba46f271449c9ce2"

Predictor = Callable[[str], object]


class LFMExtractor:
    """Extract structural privacy entities with LiquidAI's LFM2.5 detector."""

    def __init__(
        self,
        *,
        predictor: Predictor | None = None,
        model_id: str = _DEFAULT_MODEL_ID,
        model_revision: str = _DEFAULT_MODEL_REVISION,
        decoder_revision: str | None = None,
        device: str = "cpu",
        normalizer: EntityNormalizer | None = None,
    ) -> None:
        self._predictor = predictor
        self._predictor_lock = Lock()
        self._model_id = model_id
        self._model_revision = model_revision
        self._decoder_revision = decoder_revision
        self._device = device
        self._normalizer = normalizer or EntityNormalizer()

    def extract(self, text: str) -> DetectionResult:
        """Run LFM decoding and return normalized detector output."""
        try:
            predictor = self._get_predictor()
            run = self._new_run()
            candidates = LFMParser().parse(predictor(text), text)
            return self._normalizer.normalize(text, candidates, run)
        except (DetectorParseError, ImportError, ValueError, RuntimeError, TypeError) as exc:
            run = self._new_run()
            return self._failed(run, "LFM_BACKEND_ERROR", str(exc))
        except Exception as exc:  # pragma: no cover - defensive optional-backend boundary
            run = self._new_run()
            return self._failed(run, "LFM_BACKEND_ERROR", str(exc))

    def _get_predictor(self) -> Predictor:
        predictor = self._predictor
        if predictor is not None:
            return predictor
        with self._predictor_lock:
            predictor = self._predictor
            if predictor is None:
                predictor = self._load_predictor()
                self._predictor = predictor
        return predictor

    def _load_predictor(self) -> Predictor:
        try:
            from huggingface_hub import hf_hub_download
            from transformers import AutoModelForTokenClassification, AutoTokenizer
        except ImportError as exc:  # pragma: no cover - depends on optional installation
            raise RuntimeError("Install transformers and huggingface-hub to use LFMExtractor") from exc

        helper_path = hf_hub_download(
            self._model_id,
            "pii_hybrid_decode.py",
            revision=self._model_revision,
        )
        hf_hub_download(
            self._model_id,
            "context_cued.py",
            revision=self._model_revision,
        )
        helper_directory = helper_path.rsplit("/", 1)[0]
        if helper_directory not in sys.path:
            sys.path.insert(0, helper_directory)
        spec = importlib.util.spec_from_file_location("privacy_router_lfm_decoder", helper_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load the LFM decoder helper")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)

        tokenizer = AutoTokenizer.from_pretrained(
            self._model_id,
            revision=self._model_revision,
            trust_remote_code=True,
        )
        model = AutoModelForTokenClassification.from_pretrained(
            self._model_id,
            revision=self._model_revision,
            trust_remote_code=True,
        ).to(self._device)
        model.eval()
        predict = getattr(helper, "predict", None)
        if not callable(predict):
            raise RuntimeError("LFM decoder helper does not expose predict")
        return lambda text: predict(text, tokenizer, model)

    def _new_run(self) -> LFMDetectorRun:
        return LFMDetectorRun(
            detector_type="lfm",
            detector_id=_DETECTOR_ID,
            status="complete",
            external_opt_in=False,
            adapter_version=_ADAPTER_VERSION,
            model_id=self._model_id,
            model_revision=self._model_revision,
            decoder_revision=self._decoder_revision,
            device=self._device,
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
