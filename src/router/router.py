"""Caller-owned privacy orchestration with metadata-only execution events."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter
from typing import Literal, Protocol, runtime_checkable
from uuid import uuid4

from agents.annotator import Annotator
from agents.extractor import Extractor
from cachier import Cachier
from contracts import ConfidentialityJudgment, HydrationResult, IntentAnnotation, MaskingResult, NecessityJudgment
from masker import Masker
from policy import HeuristicPolicy, Policy, PolicyRecommendation

Stage = Literal["run", "validation", "annotation", "cache", "extraction", "policy", "masking"]
EventState = Literal["started", "completed", "skipped", "failed"]
EventDetail = Literal["intent_provided", "cache_hit", "cache_miss"]


@dataclass(frozen=True, slots=True)
class RouterEvent:
    """Safe progress metadata; never includes source, model output or exceptions."""

    run_id: str
    sequence: int
    stage: Stage
    state: EventState
    elapsed_ms: float
    detail: EventDetail | None = None


@dataclass(frozen=True, slots=True)
class RouterRecord:
    start: int
    end: int
    category: str
    confidence: float | None
    confidentiality: ConfidentialityJudgment
    necessity: NecessityJudgment


@dataclass(frozen=True, slots=True)
class RouterResult:
    """Local result containing private data; not suitable as a progress event."""

    intent: IntentAnnotation
    intent_source: Literal["analyzed", "provided"]
    records: tuple[RouterRecord, ...]
    recommendation: PolicyRecommendation
    masking: MaskingResult
    hydration: HydrationResult
    cache_hit: bool
    masking_preserves_task: bool | None
    masking_reason: str | None


class RoutingError(RuntimeError):
    """A failed execution stage without private diagnostics."""

    def __init__(self, stage: Stage):
        self.stage = stage
        super().__init__(f"Privacy processing failed at stage: {stage}.")


@runtime_checkable
class Router(Protocol):
    def route(
        self,
        text: str,
        *,
        namespace: str,
        history: Sequence[str | bytes] = (),
        intent: IntentAnnotation | None = None,
        on_status: Callable[[RouterEvent], None] | None = None,
    ) -> RouterResult:
        """Recommend handling and prepare masks; do not execute external actions."""
        ...


class PrivacyRouter(Router):
    """Orchestrate injected privacy components, without choosing or calling a target model.

    Events are delivered synchronously before/after actual work. A callback
    failure propagates unchanged and stops further processing. Each invocation
    owns its event sequence; this instance retains no source or subscriber.
    Callers isolate/synchronize their cache and component dependencies when
    sharing them across threads. Results and masking contracts remain private
    caller-owned data; only RouterEvent is safe for generic progress consumers.
    """

    def __init__(
        self,
        *,
        annotator: Annotator,
        extractor: Extractor,
        cache: Cachier,
        detector_fingerprint: str,
        policy: Policy | None = None,
        masker: Masker | None = None,
    ):
        if not isinstance(detector_fingerprint, str) or not detector_fingerprint.strip():
            raise ValueError("detector_fingerprint must not be blank")
        self._annotator = annotator
        self._extractor = extractor
        self._cache = cache
        self._fingerprint = detector_fingerprint
        self._policy = policy if policy is not None else HeuristicPolicy()
        self._masker = masker if masker is not None else Masker()

    def route(
        self,
        text: str,
        *,
        namespace: str,
        history: Sequence[str | bytes] = (),
        intent: IntentAnnotation | None = None,
        on_status: Callable[[RouterEvent], None] | None = None,
    ) -> RouterResult:
        run_id = str(uuid4())
        started = perf_counter()
        sequence = 0
        stage: Stage = "run"
        observer_failed = False

        def emit(current_stage: Stage, state: EventState, detail: EventDetail | None = None):
            nonlocal sequence, observer_failed
            sequence += 1
            if on_status is not None:
                event = RouterEvent(run_id, sequence, current_stage, state, (perf_counter() - started) * 1000, detail)
                try:
                    on_status(event)
                except BaseException:
                    observer_failed = True
                    raise

        try:
            emit("run", "started")
            stage = "validation"
            emit(stage, "started")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Source must be nonblank text")
            if not isinstance(namespace, str) or not namespace.strip():
                raise ValueError("Namespace must not be blank")
            if isinstance(history, (str, bytes)) or not isinstance(history, Sequence):
                raise TypeError("History must be a sequence")
            if any(not isinstance(item, (str, bytes)) for item in history):
                raise TypeError("History items must be text or bytes")
            if intent is not None and (not isinstance(intent, IntentAnnotation) or not intent.matches_source(text)):
                raise ValueError("Intent does not match the source")
            emit(stage, "completed")

            stage = "annotation"
            intent_source = "provided" if intent is not None else "analyzed"
            if intent is None:
                emit(stage, "started")
                intent = self._annotator.annotate(text)
                if not isinstance(intent, IntentAnnotation) or not intent.matches_source(text):
                    raise ValueError("Analyzer returned intent for another source")
                emit(stage, "completed")
            else:
                emit(stage, "skipped", "intent_provided")

            stage = "cache"
            emit(stage, "started")
            key = self._cache.make_key(
                namespace=namespace,
                message=text,
                history=history,
                detector_fingerprint=self._fingerprint,
                intent=intent,
            )
            cached = self._cache.get(key)
            if cached is not None:
                for ref in cached.references:
                    if (
                        not 0 <= ref.start < ref.end <= len(text)
                        or sha256(text[ref.start : ref.end].encode()).hexdigest() != ref.value_hash
                    ):
                        self._cache.invalidate(namespace)
                        raise ValueError("Cached span does not match source")
                records = tuple(
                    RouterRecord(
                        ref.start,
                        ref.end,
                        ref.category,
                        ref.confidence,
                        ConfidentialityJudgment(value=ref.confidentiality),
                        NecessityJudgment(value=ref.necessity),
                    )
                    for ref in cached.references
                )
                evidence = cached
            emit(stage, "completed", "cache_hit" if cached is not None else "cache_miss")

            stage = "extraction"
            if cached is None:
                emit(stage, "started")
                evidence = self._extractor.extract(text, intent=intent)
                for record in evidence.records:
                    if (
                        not 0 <= record.start < record.end <= len(text)
                        or text[record.start : record.end] != record.span
                    ):
                        raise ValueError("Extracted span does not match source")
                records = tuple(
                    RouterRecord(
                        record.start,
                        record.end,
                        record.category,
                        record.confidence,
                        record.confidentiality,
                        record.necessity,
                    )
                    for record in evidence.records
                )
                emit(stage, "completed")
            else:
                emit(stage, "skipped", "cache_hit")

            stage = "policy"
            emit(stage, "started")
            recommendation = self._policy.recommend([evidence])
            emit(stage, "completed")

            stage = "masking"
            emit(stage, "started")
            masked = self._masker.mask(text, _masking_records(text, records))
            hydrated = self._masker.hydrate(masked.masked_text, masked.contract)
            if hydrated.hydrated_text != text:
                raise ValueError("Masking round trip did not preserve source")
            emit(stage, "completed")
            stage = "run"
            if cached is None:
                self._cache.put(key, evidence)
            result = RouterResult(
                intent=intent,
                intent_source=intent_source,
                records=records,
                recommendation=recommendation,
                masking=masked,
                hydration=hydrated,
                cache_hit=cached is not None,
                masking_preserves_task=evidence.masking_preserves_task,
                masking_reason=evidence.masking_reason if cached is None else None,
            )
            emit(stage, "completed")
            return result
        except Exception:
            if observer_failed:
                raise
            if stage != "run":
                emit(stage, "failed")
            emit("run", "failed")
            raise RoutingError(stage) from None


def _masking_records(source: str, records: tuple[RouterRecord, ...]) -> list[dict]:
    """Mask overlapping protected unions and repeats; public records contribute no mask."""
    intervals = set()
    for record in records:
        if record.confidentiality.value == "public":
            continue
        span = source[record.start : record.end]
        offset = source.find(span)
        while offset != -1:
            intervals.add((offset, offset + len(span)))
            offset = source.find(span, offset + 1)
    merged = []
    for start, end in sorted(intervals):
        if merged and start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [{"start": start, "end": end, "span": source[start:end]} for start, end in merged]
