"""Single-pass extraction facade and module-level convenience entry point."""

from __future__ import annotations

from contracts.annotation import IntentAnnotation

from .extractor_core import ExtractorCore
from .schemas import ExtractionResult

_DEFAULT_EXTRACTOR: Extractor | None = None
"""Module-level singleton, populated on first call to :func:`extract`."""


# ── Extractor ────────────────────────────────────────────────────────────────


class Extractor:
    """Facade for the extraction pipeline.

    Parameters
    ----------
    model : str or None
        Override the model for extraction.
    api_base : str or None
        Override the API base URL.
    max_tokens : int or None
        Override the configured completion-token budget.
    core : ExtractorCore or None
        Inject a custom ExtractorCore (for testing).
    """

    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        prompt_path: str | None = None,
        core: ExtractorCore | None = None,
        max_tokens: int | None = None,
    ) -> None:
        """Configure single-pass extraction.

        Args:
            model: Optional extraction model override.
            api_base: Optional model endpoint override.
            prompt_path: Optional ExtractorCore prompt path.
            core: Optional injected ExtractorCore.
            max_tokens: Optional completion-token limit.
        """
        self._core = core or ExtractorCore(
            model=model,
            api_base=api_base,
            prompt_path=prompt_path,
            max_tokens=max_tokens,
        )

    def extract(self, text: str, *, intent: IntentAnnotation | None = None) -> ExtractionResult:
        """Extract public and private information with independent task judgments.

        Parameters
        ----------
        text : str
            The raw text to analyse.
        intent : IntentAnnotation or None
            Source-bound task evidence; absent intent leaves necessity unassessed.

        Returns:
        -------
        ExtractionResult
            Sensitivity assessment and validated records.
        """
        return self._core.extract(text, intent=intent)


# ── Module-level convenience ─────────────────────────────────────────────────


def extract(text: str, *, intent: IntentAnnotation | None = None) -> ExtractionResult:
    """One-shot extraction using a shared :class:`Extractor` instance.

    Parameters
    ----------
    text : str
        The raw text to analyse.
    intent : IntentAnnotation or None
        Source-bound task evidence; absent intent leaves necessity unassessed.

    Returns:
    -------
    ExtractionResult
        Sensitivity assessment and validated records.
    """
    global _DEFAULT_EXTRACTOR
    if _DEFAULT_EXTRACTOR is None:
        _DEFAULT_EXTRACTOR = Extractor()
    return _DEFAULT_EXTRACTOR.extract(text, intent=intent)
