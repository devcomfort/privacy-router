from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from agents.llm import call_llm_structured, load_prompt, render_prompt
from config import is_trusted_local_api_base, load_config

from .normalizer import EntityNormalizer
from .parsers import DetectorParseError, LLMParser
from .schemas import (
    DetectionResult,
    DetectorRunProvenance,
    LLMDetectorRun,
    Requiredness,
)

_PROMPT_PATH = Path(__file__).with_name("llm_extract.prompt")
_DETECTOR_ID = "privacy-router-llm-extractor-v1-0-0"
_ADAPTER_VERSION = "privacy-router-llm-adapter-v1-0-0"
_PROMPT_VERSION = "privacy-router-llm-prompt-v1-0-0"


class LLMRecord(BaseModel):
    """Pydantic response shape requested from the LLM backend."""

    tag: str = Field(min_length=1)
    kind: str
    span: str = Field(min_length=1)
    offsets: tuple[int, int] | None = None
    reason: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    is_required: Requiredness = Field(default_factory=Requiredness)


class LLMExtractionOutput(BaseModel):
    """Complete structured response requested from the LLM backend."""

    records: list[LLMRecord] = Field(default_factory=list)


StructuredCall = Callable[..., object]


class LLMExtractor:
    """Extract privacy entities through a local-first LiteLLM backend."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_base: str | None = None,
        prompt_path: str | Path | None = None,
        max_tokens: int | None = None,
        allow_external: bool = False,
        call_structured: StructuredCall | None = None,
        normalizer: EntityNormalizer | None = None,
    ) -> None:
        prompt = load_prompt(str(prompt_path or _PROMPT_PATH))
        config = load_config()
        decision = config.decision
        self._model = model or decision.model or prompt["model"]
        self._api_base = api_base if api_base is not None else decision.api_base
        self._max_tokens = max_tokens if max_tokens is not None else decision.config.max_tokens
        self._allow_external = allow_external
        self._call_structured = call_structured or call_llm_structured
        self._normalizer = normalizer or EntityNormalizer()
        self._template = prompt["template"]

    def extract(self, text: str) -> DetectionResult:
        """Return normalized entities and the provenance of this detector run."""
        local = is_trusted_local_api_base(self._api_base)
        run = self._new_run(external_opt_in=bool(self._allow_external and not local))

        if not local and not self._allow_external:
            return self._failed(run, "EXTERNAL_BACKEND_NOT_ALLOWED", "External raw-input extraction requires explicit opt-in.")
        if not text or not text.strip():
            return DetectionResult(detector_runs=[run])

        try:
            rendered = render_prompt(self._template, text=text)
            raw = self._call_structured(
                [{"role": "user", "content": rendered}],
                LLMExtractionOutput,
                model=self._model,
                api_base=self._api_base,
                max_tokens=self._max_tokens,
                component="extractor",
            )
            candidates = LLMParser().parse(raw, text)
            return self._normalizer.normalize(text, candidates, run)
        except (DetectorParseError, ValueError, RuntimeError, TypeError) as exc:
            return self._failed(run, "EXTRACTOR_BACKEND_ERROR", str(exc))
        except Exception as exc:  # pragma: no cover - defensive boundary for provider failures
            return self._failed(run, "EXTRACTOR_BACKEND_ERROR", str(exc))

    def _new_run(self, *, external_opt_in: bool) -> DetectorRunProvenance:
        return LLMDetectorRun(
            detector_type="llm",
            detector_id=_DETECTOR_ID,
            status="complete",
            external_opt_in=external_opt_in,
            adapter_version=_ADAPTER_VERSION,
            model_id=self._model,
            prompt_version=_PROMPT_VERSION,
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
