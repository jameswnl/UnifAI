"""Unit tests for the audit trail ([1.3], issue #9)."""

import pytest

from mas.core.audit import AuditTrail, NULL_AUDIT


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


class ExplodingSink(MemorySink):
    def append(self, session_id, event):
        raise RuntimeError("db down")


@pytest.mark.unit
def test_typed_records():
    sink = MemorySink()
    audit = AuditTrail(sink)
    audit.session_started("s1", identity="alice", scope="public")
    audit.approval_requested("s1", request_id="r1", tool_name="ssh_exec",
                             node_uid="n1")
    audit.approval_resolved("s1", request_id="r1", decision="approve",
                            source="human")
    audit.session_completed("s1")

    types = [e["type"] for e in audit.list("s1")]
    assert types == ["session.started", "approval.requested",
                     "approval.resolved", "session.completed"]
    assert audit.list("s1")[0]["identity"] == "alice"
    assert all("ts" in e for e in audit.list("s1"))


@pytest.mark.unit
def test_audit_failure_is_swallowed():
    audit = AuditTrail(ExplodingSink())
    audit.session_started("s2", identity="a", scope="public")  # must not raise


@pytest.mark.unit
def test_null_audit_noops():
    assert not NULL_AUDIT.enabled
    NULL_AUDIT.session_completed("s3")
    assert NULL_AUDIT.list("s3") == []


@pytest.mark.unit
def test_lifecycle_emits_audit():
    from mas.session.execution.lifecycle import SessionLifecycle
    from mas.session.domain.session_record import SessionRecord
    from mas.core.execution_context import ExecutionContext
    from mas.core.identity import Identity, IdentityType

    class FakeRepo:
        def save(self, record):
            pass

    sink = MemorySink()
    lifecycle = SessionLifecycle(repository=FakeRepo(), audit=AuditTrail(sink))
    record = SessionRecord(
        run_id="run-1",
        identity=Identity(type=IdentityType.USER, id="alice"),
        blueprint_id="bp",
        run_context=ExecutionContext(),
    )
    lifecycle.begin(record, scope="public")
    lifecycle.complete(record, record.graph_state)

    types = [e["type"] for e in sink.list_events("run-1")]
    assert types == ["session.started", "session.completed"]
