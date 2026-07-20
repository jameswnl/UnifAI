"""Unit tests for escalation v1 ([2.5], issue #15)."""

import pytest

from mas.core.audit import AuditTrail
from mas.engine.retry import RetriesExhaustedError
from mas.session.domain.session_record import SessionRecord
from mas.session.domain.status import SessionStatus
from mas.session.execution.lifecycle import SessionLifecycle
from mas.core.execution_context import ExecutionContext
from mas.core.identity import Identity, IdentityType


class MemorySink:
    def __init__(self):
        self.events = {}

    def append(self, session_id, event):
        self.events.setdefault(session_id, []).append(event)

    def list_events(self, session_id, offset=0, limit=1000):
        return self.events.get(session_id, [])[offset:offset + limit]

    def count(self, session_id):
        return len(self.events.get(session_id, []))

    def delete_session(self, session_id):
        return len(self.events.pop(session_id, []))


class FakeRepo:
    def save(self, record):
        self.saved = record


def _record(run_id="run-esc"):
    return SessionRecord(
        run_id=run_id,
        identity=Identity(type=IdentityType.USER, id="alice"),
        blueprint_id="bp",
        run_context=ExecutionContext(),
    )


@pytest.mark.unit
def test_escalate_sets_status_and_packages_audit():
    sink = MemorySink()
    lifecycle = SessionLifecycle(repository=FakeRepo(), audit=AuditTrail(sink))
    record = _record()

    error = RetriesExhaustedError(
        "fix_step",
        attempts=[{"attempt": 1, "error": "ValueError: boom"},
                  {"attempt": 2, "error": "ValueError: boom"}],
        last=ValueError("boom"),
    )
    lifecycle.escalate(record, error)

    assert record.status == SessionStatus.ESCALATED
    assert "fix_step" in record.metadata.status_message

    events = sink.list_events("run-esc")
    esc = [e for e in events if e["type"] == "session.escalated"]
    assert len(esc) == 1
    assert esc[0]["node_uid"] == "fix_step"
    assert esc[0]["reason"] == "retries_exhausted"
    assert len(esc[0]["attempts"]) == 2
    assert esc[0]["identity"] == "alice"


@pytest.mark.unit
def test_escalate_noop_when_cancelled():
    sink = MemorySink()
    lifecycle = SessionLifecycle(repository=FakeRepo(), audit=AuditTrail(sink))
    record = _record("run-cancelled")
    record.status = SessionStatus.CANCELLED

    lifecycle.escalate(record, RetriesExhaustedError("s", [], ValueError("x")))
    assert record.status == SessionStatus.CANCELLED
    assert sink.list_events("run-cancelled") == []


@pytest.mark.unit
def test_escalated_is_a_distinct_state():
    # Modeled as a state (not a hard-coded terminate) so park-and-resume
    # (v2) stays an enhancement.
    assert SessionStatus.ESCALATED.value == "ESCALATED"
    assert SessionStatus.ESCALATED != SessionStatus.FAILED
