"""Explicit local intent analysis, independent of sensitive-span extraction."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from config import load_config, resolve_local_api_base
from contracts import IntentAnnotation
from contracts.annotation import _IntentContent
from shared.llm import call_llm_structured, load_prompt

_PROMPT_PATH = Path(__file__).with_name("intent.prompt")


@runtime_checkable
class Annotator(Protocol):
    """Produce source-bound task evidence without authorizing downstream actions."""

    def annotate(self, text: str) -> IntentAnnotation:
        """Analyze the full unchanged source or raise when analysis is unavailable."""
        ...


class IntentAnalysisUnavailable(RuntimeError):
    """Intent analysis failed without a valid source-bound result."""


class IntentAnalyzer(Annotator):
    """Analyze intent in one explicit structured call to a trusted local model."""

    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        prompt_path: str | Path | None = None,
        max_tokens: int | None = None,
        call_structured: Callable[..., _IntentContent] | None = None,
    ) -> None:
        """Use decision-model configuration and the shared local endpoint boundary."""
        self._prompt = load_prompt(str(prompt_path or _PROMPT_PATH))
        config = load_config()
        decision = config.decision
        self._model = model or decision.model
        configured_api_base = api_base
        if configured_api_base is None and model is None:
            configured_api_base = decision.api_base
        self._api_base = resolve_local_api_base(config, self._model, configured_api_base)
        self._max_tokens = max_tokens if max_tokens is not None else decision.config.max_tokens
        self._call_structured = call_structured or call_llm_structured

    def annotate(self, text: str) -> IntentAnnotation:
        """Derive intent content, validate it, then bind the exact source locally."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Intent analysis requires nonblank source text.")
        messages = [
            {"role": "system", "content": self._prompt["template"]},
            {"role": "user", "content": text},
        ]
        try:
            output = self._call_structured(
                messages,
                _IntentContent,
                model=self._model,
                api_base=self._api_base,
                max_tokens=self._max_tokens,
                component="annotator",
            )
            content = _IntentContent.model_validate(output.model_dump() if isinstance(output, BaseModel) else output)
            return IntentAnnotation.for_text(text, **content.model_dump())
        except Exception:
            raise IntentAnalysisUnavailable("Intent analysis unavailable.") from None
