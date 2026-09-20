"""LiteLLM-backed structured LLM privacy extractor."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from config import is_trusted_local_api_base, load_config
from shared.llm import call_llm_structured, load_prompt, render_prompt

from ..normalizer import EntityNormalizer
from ..parser import confidentiality_judgment, necessity_judgment
from ..schemas import ConfidentialityJudgment, DetectionResult, DetectorRunProvenance, LLMDetectorRun, NecessityJudgment
from .parser import DetectorParseError, LLMParser

_PROMPT_PATH = Path(__file__).with_name("llm_extract.prompt")
_DETECTOR_ID = "privacy-router-llm-extractor-v2-0-0"
_ADAPTER_VERSION = "privacy-router-llm-adapter-v2-0-0"
_PROMPT_VERSION = "privacy-router-llm-prompt-v2-0-0"


class LLMRecord(BaseModel):
    """Pydantic response shape requested from the LLM backend."""

    tag: str = Field(min_length=1)
    kind: str
    span: str = Field(min_length=1)
    offsets: tuple[int, int] | None = None
    confidentiality: ConfidentialityJudgment
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    necessity: NecessityJudgment

    @field_validator("confidentiality", mode="before")
    @classmethod
    def require_confidentiality_reason(cls, value: object) -> ConfidentialityJudgment:
        return confidentiality_judgment(value)

    @field_validator("necessity", mode="before")
    @classmethod
    def require_necessity_reason(cls, value: object) -> NecessityJudgment:
        return necessity_judgment(value)


class LLMExtractionOutput(BaseModel):
    """Complete structured response requested from the LLM backend."""

    records: list[LLMRecord] = Field(...)


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
        call_structured: StructuredCall | None = None,
        normalizer: EntityNormalizer | None = None,
    ) -> None:
        """Configure the LLM backend and normalization dependencies.

        Args:
            model: LiteLLM model identifier. Defaults to the configured
                decision model.
            api_base: Provider endpoint. Trusted local endpoints are allowed
                by default; external endpoints require request-level opt-in.
            prompt_path: Optional path to the structured extraction prompt.
            max_tokens: Optional completion-token limit.
            call_structured: Injectable structured-call function for tests or
                alternate LiteLLM clients.
            normalizer: Injectable candidate normalizer.
        """
        prompt = load_prompt(str(prompt_path or _PROMPT_PATH))
        config = load_config()
        decision = config.decision
        self._model = model or decision.model or prompt["model"]
        self._api_base = api_base if api_base is not None else decision.api_base
        self._max_tokens = max_tokens if max_tokens is not None else decision.config.max_tokens
        self._call_structured = call_structured or call_llm_structured
        self._normalizer = normalizer or EntityNormalizer()
        self._template = prompt["template"]

    def extract(self, text: str, *, allow_external: bool = False) -> DetectionResult:
        """Extract privacy entities through the configured LLM.

        Args:
            text: Original input text.
            allow_external: Per-request opt-in for sending raw text to an
                untrusted external endpoint.

        Returns:
            Normalized entities, run provenance, and diagnostics.
        """
        local = is_trusted_local_api_base(self._api_base)
        run = self._new_run(external_opt_in=bool(allow_external and not local))

        if not local and not allow_external:
            return self._failed(
                run, "EXTERNAL_BACKEND_NOT_ALLOWED", "External raw-input extraction requires explicit opt-in."
            )
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
