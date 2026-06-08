"""Privacy Router — observability bootstrap.

Self-hosted stack: OTel SDK → OTLP → OTel Collector → Prometheus / Loki / Grafana.
Zero cloud dependency.  Call ``setup_observability(app)`` once at startup.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

if TYPE_CHECKING:
    from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Bootstrap — called once at import time via server/__init__.py
# ---------------------------------------------------------------------------

_otel_configured = False


def setup_observability(app: FastAPI) -> None:
    """Configure self-hosted OTel stack and instrument FastAPI.

    Telemetry path (no cloud dependency):
        OTel SDK → OTLP gRPC → OTel Collector → Prometheus + Loki

    Override the collector endpoint with ``OTEL_EXPORTER_OTLP_ENDPOINT``.
    Defaults to ``http://otel-collector:4317`` (Docker) or
    ``http://localhost:4317`` (bare-metal).
    """
    global _otel_configured
    if _otel_configured:
        return
    _otel_configured = True

    otel_endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://otel-collector:4317",
    )

    # ── Traces ─────────────────────────────────────────────────────────
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=otel_endpoint))
    )
    trace.set_tracer_provider(tracer_provider)

    # ── Metrics ────────────────────────────────────────────────────────
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=otel_endpoint),
        export_interval_millis=10_000,
    )
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # ── Auto-instrument FastAPI ─────────────────────────────────────────
    FastAPIInstrumentor.instrument_app(app)


# ---------------------------------------------------------------------------
# Tracer / Meter — import these to create spans and record metrics.
# ---------------------------------------------------------------------------

def get_tracer(name: str = "privacy-router") -> trace.Tracer:
    """Return an OTel tracer."""
    return trace.get_tracer(name)


def get_meter(name: str = "privacy-router") -> metrics.Meter:
    """Return an OTel meter."""
    return metrics.get_meter(name)


# ---------------------------------------------------------------------------
# Metrics — lazy-initialised singletons so import doesn't require OTel to be
# configured first.  Call these after ``setup_observability()`` has run.
# ---------------------------------------------------------------------------

_m: metrics.Meter | None = None


def _meter() -> metrics.Meter:
    global _m
    if _m is None:
        _m = get_meter()
    return _m


def _histogram(name: str, unit: str, description: str) -> metrics.Histogram:
    return _meter().create_histogram(name, unit=unit, description=description)


def _counter(name: str, unit: str, description: str) -> metrics.Counter:
    return _meter().create_counter(name, unit=unit, description=description)


# ── Pipeline stage durations ───────────────────────────────────────────
pipeline_stage_duration = _histogram(
    "pipeline_stage_duration",
    unit="s",
    description="Wall-clock time spent in each pipeline stage",
)

# ── LLM latency metrics ───────────────────────────────────────────────
llm_ttft = _histogram(
    "llm_ttft",
    unit="s",
    description="Time to first token from the upstream LLM",
)

llm_tpot = _histogram(
    "llm_tpot",
    unit="s",
    description="Time per output token from the upstream LLM",
)

llm_itl = _histogram(
    "llm_itl",
    unit="s",
    description="Inter-token latency from the upstream LLM",
)

llm_throughput = _histogram(
    "llm_throughput",
    unit="tokens/s",
    description="Token generation throughput from the upstream LLM",
)

# ── PII counters ──────────────────────────────────────────────────────
pii_detected = _counter(
    "pii_detected",
    unit="records",
    description="Number of PII records detected by the extractor",
)

pii_masked = _counter(
    "pii_masked",
    unit="records",
    description="Number of PII records masked by the masker",
)


# ---------------------------------------------------------------------------
# Helpers for proxy.py — thin wrappers to keep call-sites clean.
# ---------------------------------------------------------------------------

def timed_span(name: str, attrs: dict[str, Any] | None = None):
    """Context manager that records an OTel span and its wall-clock duration
    into ``pipeline_stage_duration``.

    Usage::

        with timed_span("extractor", {"model": "ministral-3b"}):
            result = extractor.extract(text)
    """
    return _TimedSpan(name, attrs or {})


class _TimedSpan:
    """Context manager combining an OTel span with a duration histogram record."""

    __slots__ = ("_name", "_attrs", "_start", "_span")

    def __init__(self, name: str, attrs: dict[str, Any]):
        self._name = name
        self._attrs = attrs
        self._start = 0.0
        self._span: trace.Span | None = None

    def __enter__(self) -> _TimedSpan:
        tracer = get_tracer()
        self._span = tracer.start_span(self._name)
        for k, v in self._attrs.items():
            self._span.set_attribute(k, v)
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        duration = time.perf_counter() - self._start
        pipeline_stage_duration.record(duration, {"stage": self._name})
        if self._span is not None:
            self._span.set_attribute("duration_s", duration)
            if exc_type is not None:
                self._span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc_val)))
            else:
                self._span.set_status(trace.Status(trace.StatusCode.OK))
            self._span.end()

    def set_attribute(self, key: str, value: Any) -> None:
        if self._span is not None:
            self._span.set_attribute(key, value)
