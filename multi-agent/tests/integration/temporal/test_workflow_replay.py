"""
Temporal workflow determinism / replay test ([2.7], issue #17).

The worker runs with ``UnsandboxedWorkflowRunner`` (the Pydantic data
converter and shared domain imports need it), which disables Temporal's
determinism sandbox. That puts replay-correctness of ``GraphTraversal``
(the shared traversal algorithm driving ``GraphTraversalWorkflow``) on
us. This test:

  1. runs the workflow once against an in-process time-skipping test
     server with mocked activities, capturing real event history, then
  2. replays that history through ``Replayer`` and asserts no
     non-determinism error is raised.

A code change that makes the workflow path non-deterministic (e.g.
iterating an unordered set without sorting, wall-clock branching) fails
step 2. Self-contained — no external Temporal server, no network.
"""

import asyncio
import uuid

import pytest

pytestmark = pytest.mark.integration


def _linear_two_node_params():
    """A minimal entry→exit graph: two nodes, one edge."""
    from mas.engine.domain.models import GraphDefinition, NodeDef
    from mas.graph.state.graph_state import GraphState
    from temporal.models import GraphExecutionParams

    graph = GraphDefinition(
        nodes={
            "n1": NodeDef(uid="n1", rid="r1", node_blueprint={"uid": "n1"}),
            "n2": NodeDef(uid="n2", rid="r2", node_blueprint={"uid": "n2"}),
        },
        edges={"n1": ["n2"]},
        entry="n1",
        exit_node="n2",
    )
    return GraphExecutionParams(
        state=GraphState(user_prompt="replay-test"),
        graph_definition=graph,
        session_id="replay-session",
    )


async def _run_and_replay() -> None:
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker, Replayer, UnsandboxedWorkflowRunner
    from temporalio.activity import defn as activity_defn
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.client import Client

    from mas.graph.state.graph_state import GraphState
    from temporal.models import ExecuteNodeParams, EvaluateConditionParams
    from inbound.temporal.workflows import GraphTraversalWorkflow

    # Mocked activities: echo the incoming state (no real node execution).
    @activity_defn(name="execute_graph_node")
    async def execute_graph_node(params: ExecuteNodeParams) -> GraphState:
        return params.state

    @activity_defn(name="evaluate_condition")
    async def evaluate_condition(params: EvaluateConditionParams) -> str:
        return ""

    task_queue = f"replay-tq-{uuid.uuid4().hex[:8]}"

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter,
    ) as env:
        client: Client = env.client
        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[GraphTraversalWorkflow],
            activities=[execute_graph_node, evaluate_condition],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await client.start_workflow(
                GraphTraversalWorkflow.run,
                _linear_two_node_params(),
                id=f"replay-wf-{uuid.uuid4().hex[:8]}",
                task_queue=task_queue,
                result_type=GraphState,
            )
            await handle.result()
            history = await handle.fetch_history()

    # Replay the captured history — raises on any non-determinism.
    replayer = Replayer(
        workflows=[GraphTraversalWorkflow],
        workflow_runner=UnsandboxedWorkflowRunner(),
        data_converter=pydantic_data_converter,
    )
    await replayer.replay_workflow(history)


def test_graph_traversal_workflow_replays_deterministically():
    asyncio.run(_run_and_replay())
