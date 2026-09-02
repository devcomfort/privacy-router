"""In-memory batch state for the local HTMX demo."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Literal
from uuid import uuid4

DemoStatus = Literal["queued", "running", "completed", "failed", "expired"]
_TERMINAL_STATUSES = {"completed", "failed", "expired"}


@dataclass(frozen=True)
class DemoCaseSnapshot:
    """Immutable public snapshot for one built-in demo case."""

    name: str
    text: str
    status: DemoStatus
    result: dict[str, object] | None


@dataclass(frozen=True)
class DemoBatchSnapshot:
    """Immutable public snapshot for one local demo batch."""

    batch_id: str
    status: DemoStatus
    total: int
    completed: int
    current_name: str | None
    cases: tuple[DemoCaseSnapshot, ...]


@dataclass
class _DemoCase:
    """Mutable case state owned by ``DemoBatchStore``."""

    name: str
    text: str
    status: DemoStatus = "queued"
    result: dict[str, object] | None = None


@dataclass
class _DemoBatch:
    """Mutable batch state protected by the store lock."""

    batch_id: str
    created_at: float
    status: DemoStatus
    cases: list[_DemoCase]
    current_name: str | None = None


class DemoBatchStore:
    """Coordinate short-lived, single-process demo batches."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 600.0,
        max_batches: int = 16,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_batches = max_batches
        self._lock = RLock()
        self._batches: dict[str, _DemoBatch] = {}
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="privacy-router-demo",
        )
        self._futures: set[Future[object]] = set()

    def create(self, cases: tuple[tuple[str, str], ...]) -> DemoBatchSnapshot:
        """Create a queued batch and return its initial snapshot."""
        batch = _DemoBatch(
            batch_id=uuid4().hex,
            created_at=monotonic(),
            status="queued",
            cases=[_DemoCase(name=name, text=text) for name, text in cases],
        )
        with self._lock:
            self._prune_locked()
            self._batches[batch.batch_id] = batch
            self._prune_capacity_locked()
            return self._snapshot_locked(batch)

    def submit(self, batch_id: str, runner: Callable[[str], None]) -> None:
        """Submit one guarded worker for an existing batch."""
        with self._lock:
            if batch_id not in self._batches:
                raise KeyError(f"Unknown demo batch: {batch_id}")
            future = self._executor.submit(self._run_guarded, batch_id, runner)
            self._futures.add(future)
            future.add_done_callback(self._futures.discard)

    def mark_running(self, batch_id: str, index: int) -> bool:
        """Mark one queued case as running, or reject an expired batch."""
        with self._lock:
            batch = self._get_live_batch_locked(batch_id)
            if batch is None or not 0 <= index < len(batch.cases):
                return False
            case = batch.cases[index]
            if case.status in _TERMINAL_STATUSES:
                return False
            batch.status = "running"
            batch.current_name = case.name
            case.status = "running"
            return True

    def finish_case(
        self,
        batch_id: str,
        index: int,
        status: Literal["completed", "failed"],
        result: dict[str, object],
    ) -> None:
        """Store one safe case result and close the batch when all finish."""
        with self._lock:
            batch = self._get_live_batch_locked(batch_id)
            if batch is None or not 0 <= index < len(batch.cases):
                return
            case = batch.cases[index]
            case.status = status
            case.result = dict(result)
            batch.current_name = None
            if all(item.status in {"completed", "failed"} for item in batch.cases):
                batch.status = "failed" if any(item.status == "failed" for item in batch.cases) else "completed"

    def snapshot(self, batch_id: str) -> DemoBatchSnapshot | None:
        """Return a safe immutable snapshot, expiring stale active batches."""
        with self._lock:
            self._prune_locked()
            batch = self._batches.get(batch_id)
            return self._snapshot_locked(batch) if batch is not None else None

    def _run_guarded(self, batch_id: str, runner: Callable[[str], None]) -> None:
        try:
            runner(batch_id)
        except Exception:
            with self._lock:
                batch = self._get_live_batch_locked(batch_id)
                if batch is not None:
                    batch.status = "failed"
                    batch.current_name = None
                    for case in batch.cases:
                        if case.status not in _TERMINAL_STATUSES:
                            case.status = "failed"
                            case.result = None

    def _get_live_batch_locked(self, batch_id: str) -> _DemoBatch | None:
        self._prune_locked()
        batch = self._batches.get(batch_id)
        if batch is None or batch.status == "expired":
            return None
        return batch

    def _prune_locked(self) -> None:
        now = monotonic()
        for batch in list(self._batches.values()):
            age = now - batch.created_at
            if age < self._ttl_seconds:
                continue
            if batch.status not in _TERMINAL_STATUSES:
                batch.status = "expired"
                batch.current_name = None
                for case in batch.cases:
                    case.status = "expired"
                    case.text = ""
                    case.result = None
            elif age >= self._ttl_seconds * 2:
                self._batches.pop(batch.batch_id, None)

    def _prune_capacity_locked(self) -> None:
        if len(self._batches) <= self._max_batches:
            return
        ordered = sorted(self._batches.values(), key=lambda batch: batch.created_at)
        for batch in ordered[: len(self._batches) - self._max_batches]:
            if batch.status in _TERMINAL_STATUSES:
                self._batches.pop(batch.batch_id, None)

    def _snapshot_locked(self, batch: _DemoBatch | None) -> DemoBatchSnapshot | None:
        if batch is None:
            return None
        completed = sum(case.status in {"completed", "failed"} for case in batch.cases)
        return DemoBatchSnapshot(
            batch_id=batch.batch_id,
            status=batch.status,
            total=len(batch.cases),
            completed=completed,
            current_name=batch.current_name,
            cases=tuple(
                DemoCaseSnapshot(
                    name=case.name,
                    text=case.text if batch.status != "expired" else "",
                    status=case.status,
                    result=dict(case.result) if case.result is not None else None,
                )
                for case in batch.cases
            ),
        )
