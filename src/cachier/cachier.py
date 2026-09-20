"""Bounded, session-scoped caching of privacy assessment metadata.

Raw messages, detected values, model reasoning, and placeholder maps are never
retained. Value hashes are internal references, not encryption: low-entropy
values can be guessed, so these references must not be sent to external agents.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Literal

from contracts.annotation import IntentAnnotation
from contracts.extraction import ExtractionResult

if TYPE_CHECKING:
    from agents.extractor.schemas import DetectionResult


@dataclass(frozen=True, slots=True)
class DetectionReference:
    """Immutable metadata locating an information item in the caller's message."""

    value_hash: str
    category: str
    start: int
    end: int
    confidentiality: Literal["public", "private"] | None
    necessity: Literal["required", "optional"] | None
    confidence: float | None


@dataclass(frozen=True, slots=True)
class CachedAssessment:
    """Sensitivity and task impact without raw values or model explanations."""

    is_sensitive: bool
    references: tuple[DetectionReference, ...]
    masking_preserves_task: bool | None = None


@dataclass(frozen=True, slots=True)
class CacheKey:
    """Content address isolated by session, full context, detector rules, and intent."""

    namespace: str
    message_hash: str
    history_hash: str
    detector_fingerprint: str
    intent_hash: str

    def __post_init__(self) -> None:
        _require_nonblank(self.namespace, "namespace")
        _require_nonblank(self.detector_fingerprint, "detector_fingerprint")


def _require_nonblank(value: str, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must not be blank")


def _hash_content(values: Sequence[str | bytes]) -> str:
    """Hash ordered, type-tagged, length-framed content without serialization."""
    digest = sha256(b"cachier-content-v1")
    for value in values:
        if isinstance(value, str):
            tag, payload = b"s", value.encode("utf-8")
        elif isinstance(value, bytes):
            tag, payload = b"b", value
        else:
            raise TypeError("message and history items must be str or bytes")
        digest.update(tag)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


class Cachier:
    """In-memory LRU of immutable privacy references, bounded by entry count.

    Callers supply a distinct namespace for each session and a fingerprint
    covering the detector model, prompt, and rules. Every lookup matches the
    complete prior history, including for pattern detections, because cached
    confidentiality, necessity, and joint masking impact can depend on context. There is no message-only fallback.
    Original messages and Masker contracts remain owned by the caller.
    """

    def __init__(self, max_entries: int = 256) -> None:
        if isinstance(max_entries, bool) or not isinstance(max_entries, int):
            raise TypeError("max_entries must be an integer")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._entries: OrderedDict[CacheKey, CachedAssessment] = OrderedDict()

    @staticmethod
    def make_key(
        *,
        namespace: str,
        message: str | bytes,
        history: Sequence[str | bytes],
        detector_fingerprint: str,
        intent: IntentAnnotation | None = None,
    ) -> CacheKey:
        """Address a message and its prior context without retaining either.

        ``history`` excludes the current message. Order, boundaries, and text
        versus bytes affect its hash. No files, attachments, SDK conversions,
        or semantic normalization are involved. Task annotations contribute only
        their fingerprint; no annotation strings are retained.
        """
        _require_nonblank(namespace, "namespace")
        _require_nonblank(detector_fingerprint, "detector_fingerprint")
        if isinstance(history, (str, bytes)) or not isinstance(history, Sequence):
            raise TypeError("history must be a sequence of str or bytes items")
        return CacheKey(
            namespace=namespace,
            message_hash=_hash_content((message,)),
            history_hash=_hash_content(history),
            detector_fingerprint=detector_fingerprint,
            intent_hash=intent.fingerprint() if intent is not None else _hash_content(("intent:absent",)),
        )

    def put(self, key: CacheKey, result: ExtractionResult | DetectionResult) -> None:
        """Store a metadata-only projection of an existing validated result.

        Failed or partial detection results evict any previous assessment for
        the key. Native offsets come from the result schemas; this cache does
        not infer positions or retain source text to revalidate substrings.
        """
        if isinstance(result, ExtractionResult):
            if result.status != "complete":
                self._entries.pop(key, None)
                return
            is_sensitive = result.sensitivity.is_sensitive
            references = tuple(
                DetectionReference(
                    value_hash=sha256(record.span.encode("utf-8")).hexdigest(),
                    category=record.category,
                    start=record.start,
                    end=record.end,
                    confidentiality=record.confidentiality.value,
                    necessity=record.necessity.value,
                    confidence=record.confidence,
                )
                for record in result.records
            )
        else:
            from agents.extractor.schemas import DetectionResult

            if not isinstance(result, DetectionResult):
                raise TypeError("result must be ExtractionResult or DetectionResult")
            if result.status != "complete":
                self._entries.pop(key, None)
                return
            is_sensitive = False
            references = tuple(
                DetectionReference(
                    value_hash=sha256(entity.span.encode("utf-8")).hexdigest(),
                    category=entity.tag,
                    start=entity.offsets[0],
                    end=entity.offsets[1],
                    confidentiality=entity.confidentiality.value,
                    necessity=entity.necessity.value,
                    confidence=entity.confidence,
                )
                for entity in result.entities
            )
        self._entries[key] = CachedAssessment(
            is_sensitive=is_sensitive or any(reference.confidentiality != "public" for reference in references),
            references=references,
            masking_preserves_task=result.masking_preserves_task,
        )
        self._entries.move_to_end(key)
        if len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def get(self, key: CacheKey) -> CachedAssessment | None:
        """Return immutable metadata and mark a cache hit as recently used."""
        assessment = self._entries.get(key)
        if assessment is not None:
            self._entries.move_to_end(key)
        return assessment

    def invalidate(self, namespace: str) -> int:
        """Remove one session's entries and return the number removed."""
        _require_nonblank(namespace, "namespace")
        keys = tuple(key for key in self._entries if key.namespace == namespace)
        for key in keys:
            del self._entries[key]
        return len(keys)

    def clear(self) -> None:
        """Discard every cached assessment."""
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
