"""Critic — Second-pass review to catch missed sensitive spans.

The Critic receives the original text + already-tagged spans from
the Extractor and finds what was missed.

Standalone component — can be used independently or injected into Extractor.

Examples
--------
>>> from agents.extractor.extractor_core import ExtractorCore
>>> core = ExtractorCore()
>>> result = core.extract("주민등록번호 901212-1234567")
>>> critic = Critic()
>>> review = critic.review("주민등록번호 901212-1234567", result.records)
>>> review.found_missed
False
"""

from __future__ import annotations

from pathlib import Path

from agents.llm import call_llm_structured, load_prompt, render_prompt
from config import load_config, resolve_local_api_base

from .extractor_core import PrivacyAnalysisUnavailable
from .schemas import CriticOutput, ExtractionRecord

# ── Constants ────────────────────────────────────────────────────────────────

_CRITIC_PROMPT_PATH = Path(__file__).parent / "critic.prompt"
"""Path to the critic prompt file."""


# ── Critic ───────────────────────────────────────────────────────────────────


class Critic:
    """Second-pass review to catch missed sensitive spans.

    Parameters
    ----------
    model : str or None
        Override the configured Decision Model identifier.
    api_base : str or None
        Override the API base URL.
    max_tokens : int or None
        Override the configured completion-token budget.
    prompt_path : str | Path | None
        Override the critic prompt file path.
    """

    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        prompt_path: str | Path | None = None,
        max_tokens: int | None = None,
    ) -> None:
        path = str(prompt_path or _CRITIC_PROMPT_PATH)
        prompt_dict = load_prompt(path)
        config = load_config()
        decision = config.decision
        self._model = model or decision.model
        configured_api_base = api_base
        if configured_api_base is None and model is None:
            configured_api_base = decision.api_base
        self._api_base = resolve_local_api_base(config, self._model, configured_api_base)
        self._max_tokens = max_tokens if max_tokens is not None else decision.config.max_tokens
        self._template = prompt_dict["template"]

    def review(self, text: str, existing_records: list[ExtractionRecord]) -> CriticOutput:
        """Review text for missed sensitive spans.

        Parameters
        ----------
        text : str
            The original input text.
        existing_records : list[ExtractionRecord]
            Already-tagged spans from the Extractor.

        Returns
        -------
        CriticOutput
            Whether missed spans were found, and what they are.
        """
        tagged = "\n".join(f'- {r.category}: "{r.span}"' for r in existing_records) or "(none)"

        rendered = render_prompt(self._template, text=text, tagged_spans=tagged)
        messages = [{"role": "user", "content": rendered}]

        try:
            return call_llm_structured(
                messages,
                CriticOutput,
                model=self._model,
                api_base=self._api_base,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:
            raise PrivacyAnalysisUnavailable("Sensitive-information analysis unavailable.") from exc
