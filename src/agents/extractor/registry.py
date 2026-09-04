"""Protocol and registry for backend-independent privacy extractors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from .schemas import DetectionResult


@runtime_checkable
class PrivacyExtractor(Protocol):
    """Common interface implemented by every privacy detector backend."""

    def extract(self, text: str) -> DetectionResult:
        """Detect privacy entities in one text input."""
        ...


class DetectorRegistry:
    """Dispatch extraction requests to named detector implementations."""

    def __init__(self, detectors: Mapping[str, PrivacyExtractor] | None = None) -> None:
        """Create a registry and optionally register initial detectors.

        Args:
            detectors: Mapping from public detector names to implementations.
        """
        self._detectors: dict[str, PrivacyExtractor] = {}
        for name, detector in (detectors or {}).items():
            self.register(name, detector)

    def register(self, name: str, detector: PrivacyExtractor) -> None:
        """Register or replace a detector under a public name.

        Args:
            name: Non-empty name used by :meth:`extract`.
            detector: Object implementing ``PrivacyExtractor``.

        Raises:
            TypeError: If ``detector`` does not implement the protocol.
            ValueError: If ``name`` is empty.
        """
        if not name or not name.strip():
            raise ValueError("detector name must be non-empty")
        if not isinstance(detector, PrivacyExtractor):
            raise TypeError("detector must implement PrivacyExtractor")
        self._detectors[name] = detector

    def names(self) -> tuple[str, ...]:
        """Return registered names in lexicographic order."""
        return tuple(sorted(self._detectors))

    def extract(self, name: str, text: str) -> DetectionResult:
        """Run one registered detector.

        Args:
            name: Registered detector name.
            text: Input text to analyze.

        Returns:
            The detector's normalized result.

        Raises:
            KeyError: If no detector is registered under ``name``.
        """
        try:
            detector = self._detectors[name]
        except KeyError as exc:
            raise KeyError(f"Unknown detector: {name!r}") from exc
        return detector.extract(text)
