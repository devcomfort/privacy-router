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
        Override the model identifier from the prompt.
    api_base : str or None
        Override the API base URL.
    prompt_path : str | Path | None
        Override the critic prompt file path.
    """

    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        prompt_path: str | Path | None = None,
    ) -> None:
        path = str(prompt_path or _CRITIC_PROMPT_PATH)
        prompt_dict = load_prompt(path)
        self._model = model or prompt_dict["model"]
        self._api_base = api_base
        self._template = prompt_dict["template"]

    def review(
        self, text: str, existing_records: list[ExtractionRecord]
    ) -> CriticOutput:
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
        tagged = "\n".join(
            f"- {r.category}: \"{r.span}\"" for r in existing_records
        ) or "(none)"

        rendered = render_prompt(
            self._template, text=text, tagged_spans=tagged
        )
        messages = [{"role": "user", "content": rendered}]

        try:
            return call_llm_structured(
                messages, CriticOutput, model=self._model, api_base=self._api_base
            )
        except Exception:
            return CriticOutput(found_missed=False, missed_records=[])
