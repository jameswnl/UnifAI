"""Unit tests for OTel observability ([4.3], issue #25)."""

import pytest

from mas.core.telemetry import Telemetry, NULL_TELEMETRY


def _in_memory_tracer():
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


def _in_memory_meter():
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    return provider.get_meter("test"), reader


@pytest.mark.unit
def test_null_telemetry_noops():
    assert not NULL_TELEMETRY.enabled
    with NULL_TELEMETRY.span("x", run_id="r") as s:
        assert s is None
    NULL_TELEMETRY.session_started("r")  # no error


@pytest.mark.unit
def test_span_emitted_with_attributes():
    tracer, exporter = _in_memory_tracer()
    telemetry = Telemetry(tracer, None)

    with telemetry.span("session.begin", run_id="r1", blueprint_id="bp1"):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "session.begin"
    assert spans[0].attributes["run_id"] == "r1"
    assert spans[0].attributes["blueprint_id"] == "bp1"


@pytest.mark.unit
def test_none_attributes_skipped():
    tracer, exporter = _in_memory_tracer()
    with Telemetry(tracer, None).span("s2", run_id="r", node_uid=None):
        pass
    span = exporter.get_finished_spans()[0]
    assert "node_uid" not in span.attributes  # None attrs dropped
    assert span.attributes["run_id"] == "r"


@pytest.mark.unit
def test_counters_increment():
    tracer, _ = _in_memory_tracer()
    meter, reader = _in_memory_meter()
    telemetry = Telemetry(tracer, meter)

    telemetry.session_started("r1")
    telemetry.session_completed("r1")
    telemetry.session_failed("r2")
    telemetry.session_escalated("r3")

    data = reader.get_metrics_data()
    names = set()
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                names.add(m.name)
    assert {"mas.sessions.started", "mas.sessions.completed",
            "mas.sessions.failed", "mas.sessions.escalated"} <= names


@pytest.mark.unit
def test_build_telemetry_disabled_by_default():
    class Cfg:
        otel_enabled = False

    assert build_disabled(Cfg()) is NULL_TELEMETRY


def build_disabled(cfg):
    from mas.core.telemetry import build_telemetry
    return build_telemetry(cfg)


@pytest.mark.unit
def test_lifecycle_emits_telemetry():
    from mas.session.execution.lifecycle import SessionLifecycle
    from mas.session.domain.session_record import SessionRecord
    from mas.core.execution_context import ExecutionContext
    from mas.core.identity import Identity, IdentityType

    tracer, exporter = _in_memory_tracer()
    telemetry = Telemetry(tracer, None)

    class Repo:
        def save(self, r):
            pass

    lifecycle = SessionLifecycle(repository=Repo(), telemetry=telemetry)
    record = SessionRecord(
        run_id="run-otel",
        identity=Identity(type=IdentityType.USER, id="alice"),
        blueprint_id="bp",
        run_context=ExecutionContext(),
    )
    lifecycle.begin(record, scope="public")
    lifecycle.complete(record, record.graph_state)

    span_names = [s.name for s in exporter.get_finished_spans()]
    assert "session.begin" in span_names
    assert "session.complete" in span_names
