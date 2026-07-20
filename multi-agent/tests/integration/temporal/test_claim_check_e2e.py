"""
End-to-end claim-check codec test ([2.4], issue #14).

Proves a payload larger than Temporal's ~2MB gRPC cap survives a real
workflow+activity round-trip when the claim-check codec offloads it to a
blob store. Runs against an in-process time-skipping test server; no
external Temporal server needed.
"""

import asyncio
import uuid
from datetime import timedelta

import pytest
from temporalio import activity, workflow

pytestmark = pytest.mark.integration


# Workflow/activity must be module-level (Temporal rejects local classes).
@activity.defn
async def echo_activity(data: str) -> str:
    return data + "!"


@workflow.defn
class EchoWorkflow:
    @workflow.run
    async def run(self, data: str) -> str:
        return await workflow.execute_activity(
            echo_activity, data, start_to_close_timeout=timedelta(seconds=30))


class _MemStore:
    def __init__(self):
        self.blobs = {}

    def put(self, key, data):
        self.blobs[key] = data

    def get(self, key):
        return self.blobs.get(key)

    def delete(self, key):
        self.blobs.pop(key, None)


async def _run() -> None:
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker, UnsandboxedWorkflowRunner

    from temporal.claim_check_codec import build_data_converter

    store = _MemStore()
    # 100KB threshold; 3MB payload — exceeds Temporal's ~2MB cap uncompressed.
    dc = build_data_converter(store, threshold_bytes=100_000)
    big = "A" * 3_000_000

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=dc,
    ) as env:
        tq = f"cc-tq-{uuid.uuid4().hex[:8]}"
        async with Worker(
            env.client, task_queue=tq,
            workflows=[EchoWorkflow], activities=[echo_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                EchoWorkflow.run, big,
                id=f"cc-wf-{uuid.uuid4().hex[:8]}", task_queue=tq)

    assert result == big + "!"
    assert store.blobs, "large payloads were not offloaded"


def test_large_payload_survives_temporal_via_claim_check():
    asyncio.run(_run())
