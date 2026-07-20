"""Unit tests for durable HITL ([2.2], issue #12)."""

import pytest

from mas.core.hitl.pending_store import PendingApproval, PendingApprovalStore


class MemPendingStore(PendingApprovalStore):
    def __init__(self):
        self.items = {}

    def create(self, approval):
        self.items[(approval.session_id, approval.request_id)] = approval

    def resolve(self, session_id, request_id, *, decision, resolved_by=""):
        key = (session_id, request_id)
        if key not in self.items:
            return False
        self.items[key].status = "resolved"
        self.items[key].decision = decision
        self.items[key].resolved_by = resolved_by
        return True

    def get(self, session_id, request_id):
        return self.items.get((session_id, request_id))

    def list_pending(self, session_id):
        return [a for (s, _), a in self.items.items()
                if s == session_id and a.status == "pending"]


class FakeChannel:
    def __init__(self, session_id, response):
        self._sid = session_id
        self._response = response
        self.emitted = []

    @property
    def session_id(self):
        return self._sid

    def emit(self, data):
        self.emitted.append(data)

    def wait_for(self, request_id, timeout):
        return self._response  # None => timeout


def _request(request_id="r1", session_id="s1"):
    from mas.core.hitl.models import (
        ApprovalRequest, ApprovalType, RequestOrigin, ToolAccessMode,
    )
    return ApprovalRequest(
        request_id=request_id,
        type=ApprovalType.TOOL_EXECUTION,
        origin=RequestOrigin(node_uid="n1", node_display_name="Node 1",
                             session_id=session_id),
        tool_name="ssh_exec",
        tool_args={"cmd": "ls"},
        tool_description="run ls",
        tool_access_mode=ToolAccessMode.WRITE,
        reasoning="need to inspect",
    )


def _gate(channel, store, timeout=60.0):
    from outbound.hitl.channel_gate import ChannelApprovalGate
    from mas.core.hitl.models import HITLConfig
    return ChannelApprovalGate(
        channel=channel,
        config=HITLConfig(enabled=True, timeout_seconds=timeout),
        pending_store=store,
    )


@pytest.mark.unit
def test_pending_persisted_on_request_and_resolved_on_response():
    store = MemPendingStore()
    channel = FakeChannel("s1", {"decision": "approve"})
    gate = _gate(channel, store)

    resp = gate.request_approval(_request())
    assert resp.decision.value == "approve"

    rec = store.get("s1", "r1")
    assert rec is not None
    assert rec.status == "resolved"
    assert rec.decision == "approve"
    assert rec.resolved_by == "human"
    assert rec.tool_name == "ssh_exec"


@pytest.mark.unit
def test_timeout_marks_resolved_with_timeout_source():
    store = MemPendingStore()
    channel = FakeChannel("s2", None)  # no human response
    gate = _gate(channel, store, timeout=0.01)

    gate.request_approval(_request("r2", "s2"))

    rec = store.get("s2", "r2")
    assert rec.status == "resolved"
    assert rec.resolved_by == "timeout"


@pytest.mark.unit
def test_list_pending_before_resolution():
    store = MemPendingStore()
    store.create(PendingApproval(request_id="r3", session_id="s3",
                                 tool_name="oc_exec", node_uid="n2"))
    pending = store.list_pending("s3")
    assert len(pending) == 1
    assert pending[0].request_id == "r3"


@pytest.mark.unit
def test_gate_without_store_still_works():
    channel = FakeChannel("s4", {"decision": "reject"})
    gate = _gate(channel, store=None)
    resp = gate.request_approval(_request("r4", "s4"))
    assert resp.decision.value == "reject"
