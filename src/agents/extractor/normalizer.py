"""Normalize parsed detector candidates into privacy entities."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence
from uuid import UUID, uuid4

from .parser import ParsedEntity
from .schemas import DetectionResult, DetectorRunProvenance, PrivacyEntity

type UidFactory = Callable[[], str]
type IdFactory = Callable[[], UUID]


class SpanReconciliationError(ValueError):
    """Raised when a candidate cannot be reconciled with the source text."""


class EntityNormalizer:
    """Validate candidate spans and assign per-occurrence identities."""

    def __init__(
        self,
        *,
        uid_factory: UidFactory | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        """Configure factories used for entity and occurrence-token IDs.

        Args:
            uid_factory: Callable that returns a fresh opaque occurrence token.
            id_factory: Callable that returns the internal entity UUID.
        """
        self._uid_factory = uid_factory or (lambda: secrets.token_hex(16))
        self._id_factory = id_factory or uuid4

    def normalize(
        self,
        text: str,
        candidates: Sequence[ParsedEntity],
        run: DetectorRunProvenance,
    ) -> DetectionResult:
        """Normalize candidates against the original text.

        Args:
            text: Original input text in Unicode code-point indexing.
            candidates: Backend-neutral parser candidates.
            run: Provenance record for the detector execution.

        Returns:
            A complete, partial, or failed-compatible detection result with
            occurrence-specific entity identifiers.

        Raises:
            SpanReconciliationError: If a candidate cannot be located in
                ``text``.
        """
        entities: list[PrivacyEntity] = []
        used_offsets: set[tuple[int, int]] = set()
        used_uids: set[str] = set()

        for candidate in candidates:
            offsets = self._reconcile_offsets(text, candidate, used_offsets)
            uid = self._issue_uid(used_uids)
            entities.append(
                PrivacyEntity(
                    id=self._id_factory(),
                    kind=candidate.kind,
                    tag=candidate.tag,
                    uid=uid,
                    span=candidate.span,
                    offsets=offsets,
                    confidentiality=candidate.confidentiality,
                    confidence=candidate.confidence,
                    native_label=candidate.native_label,
                    native_metadata=candidate.native_metadata,
                    detection_method=candidate.detection_method,
                    run_id=run.run_id,
                    necessity=candidate.necessity,
                )
            )

        return DetectionResult(
            status=run.status,
            entities=entities,
            detector_runs=[run],
        )

    def _reconcile_offsets(
        self,
        text: str,
        candidate: ParsedEntity,
        used_offsets: set[tuple[int, int]],
    ) -> tuple[int, int]:
        span = candidate.span
        supplied = candidate.offsets
        if supplied is not None and self._matches(text, span, supplied):
            used_offsets.add(supplied)
            return supplied

        cursor = 0
        while True:
            start = text.find(span, cursor)
            if start < 0:
                break
            offsets = (start, start + len(span))
            if offsets not in used_offsets:
                used_offsets.add(offsets)
                return offsets
            cursor = start + 1

        raise SpanReconciliationError(f"Could not reconcile span with source text: {span!r}")

    @staticmethod
    def _matches(text: str, span: str, offsets: tuple[int, int]) -> bool:
        start, end = offsets
        return 0 <= start < end <= len(text) and text[start:end] == span

    def _issue_uid(self, used_uids: set[str]) -> str:
        for _ in range(64):
            uid = self._uid_factory()
            if uid not in used_uids:
                used_uids.add(uid)
                return uid
        raise RuntimeError("Unable to issue a unique occurrence uid")
