"""
OpenTelemetry observability ([4.3], issue #25).

Session-level tracing spans + execution metrics, correlated by run_id.
Providers are configured once at startup; exporters are pluggable
(console for dev, OTLP when an endpoint is set). All instrumentation is
best-effort — a telemetry failure never breaks a workflow — and the
whole thing no-ops cleanly when disabled.

Kept deliberately thin: the spans/metrics are emitted from
SessionLifecycle (the one choke point every run passes through), so
observability rides the same seam as the audit trail ([1.3]).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

_SERVICE_NAME = "mas-harness"


class Telemetry:
    """Facade over an OTel tracer + meter. NULL instance no-ops."""

    def __init__(self, tracer=None, meter=None) -> None:
        self._tracer = tracer
        if meter is not None:
            self._started = meter.create_counter("mas.sessions.started")
            self._completed = meter.create_counter("mas.sessions.completed")
            self._failed = meter.create_counter("mas.sessions.failed")
            self._escalated = meter.create_counter("mas.sessions.escalated")
        else:
            self._started = self._completed = self._failed = self._escalated = None

    @property
    def enabled(self) -> bool:
        return self._tracer is not None

    @contextmanager
    def span(self, name: str, **attributes):
        if self._tracer is None:
            yield None
            return
        with self._tracer.start_as_current_span(name) as span:
            try:
                for k, v in attributes.items():
                    if v is not None:
                        span.set_attribute(k, v)
            except Exception:  # noqa: BLE001
                pass
            yield span

    def _incr(self, counter, run_id: str) -> None:
        if counter is not None:
            try:
                counter.add(1, {"run_id": run_id})
            except Exception:  # noqa: BLE001 — telemetry is best-effort
                logger.debug("metric emit failed", exc_info=True)

    def session_started(self, run_id: str) -> None:
        self._incr(self._started, run_id)

    def session_completed(self, run_id: str) -> None:
        self._incr(self._completed, run_id)

    def session_failed(self, run_id: str) -> None:
        self._incr(self._failed, run_id)

    def session_escalated(self, run_id: str) -> None:
        self._incr(self._escalated, run_id)


NULL_TELEMETRY = Telemetry(None, None)


def build_telemetry(cfg) -> Telemetry:
    """Configure OTel providers from config; return a Telemetry facade.

    Degrades to NULL_TELEMETRY on any setup failure. Exporter selection:
    ``otel_exporter`` = "none" (disabled), "console" (dev), or "otlp"
    (needs ``otel_endpoint`` and the OTLP exporter installed).
    """
    if not getattr(cfg, "otel_enabled", False):
        return NULL_TELEMETRY
    try:
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter, PeriodicExportingMetricReader,
        )

        resource = Resource.create({"service.name": _SERVICE_NAME})
        exporter = getattr(cfg, "otel_exporter", "console")

        span_exporter, metric_exporter = _make_exporters(exporter, cfg)
        if span_exporter is None:
            return NULL_TELEMETRY

        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        trace.set_tracer_provider(tracer_provider)

        reader = PeriodicExportingMetricReader(metric_exporter)
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        metrics.set_meter_provider(meter_provider)

        logger.info("OpenTelemetry enabled (exporter=%s)", exporter)
        return Telemetry(trace.get_tracer(_SERVICE_NAME),
                         metrics.get_meter(_SERVICE_NAME))
    except Exception:  # noqa: BLE001 — never block startup on telemetry
        logger.exception("failed to configure OpenTelemetry; disabled")
        return NULL_TELEMETRY


def _make_exporters(exporter: str, cfg):
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter
    from opentelemetry.sdk.metrics.export import ConsoleMetricExporter

    if exporter == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
            endpoint = getattr(cfg, "otel_endpoint", "")
            return (OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"),
                    OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"))
        except ImportError:
            logger.warning("otlp exporter not installed; falling back to console")
    return ConsoleSpanExporter(), ConsoleMetricExporter()
