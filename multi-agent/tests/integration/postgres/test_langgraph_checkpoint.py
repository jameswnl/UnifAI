"""
LangGraph Postgres checkpointer + resume ([2.3], issue #13).

Requires a live PostgreSQL (POSTGRES_DSN); skipped otherwise. Uses the
real LangGraphBuilder / LangGraphExecutor with a PostgresSaver to prove:
  1. state persists across nodes and the run completes;
  2. a crash mid-graph leaves a checkpoint, and re-running the same
     session resumes from the last completed node (no node re-run).
"""

import os
import uuid

import pytest

DSN = os.environ.get("POSTGRES_DSN", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="POSTGRES_DSN not set"),
]


@pytest.fixture()
def saver():
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    from langgraph.checkpoint.postgres import PostgresSaver

    pool = ConnectionPool(DSN, min_size=1, max_size=3, open=True,
                          kwargs={"autocommit": True, "row_factory": dict_row})
    s = PostgresSaver(pool)
    s.setup()
    yield s
    pool.close()


def _build_executor(saver, n1, n2):
    from outbound.langgraph.builder import LangGraphBuilder
    from mas.graph.state.graph_state import GraphState

    builder = LangGraphBuilder(GraphState, checkpointer=saver)
    builder.add_node("n1", n1)
    builder.add_node("n2", n2)
    builder.set_entry("n1")
    builder.add_edge("n1", "n2")
    builder.set_exit("n2")
    return builder.build_executor()


def test_checkpointed_run_completes(saver):
    from mas.graph.state.graph_state import GraphState

    def n1(state):
        return {"nodes_output": {"n1": "ran"}}

    def n2(state):
        seen = dict(state.get("nodes_output") or {})
        return {"nodes_output": {"n2": "saw_n1" if "n1" in seen else "MISSING"}}

    executor = _build_executor(saver, n1, n2)
    result = executor.run(GraphState(user_prompt="hi"),
                          session_id=f"cp-{uuid.uuid4().hex[:8]}")
    out = dict(result.nodes_output)
    assert out == {"n1": "ran", "n2": "saw_n1"}


def test_crash_then_resume_skips_completed_node(saver):
    from mas.graph.state.graph_state import GraphState

    calls = {"n1": 0, "n2": 0}

    def n1(state):
        calls["n1"] += 1
        return {"nodes_output": {"n1": "ran"}}

    def n2(state):
        calls["n2"] += 1
        if calls["n2"] == 1:
            raise RuntimeError("simulated crash")
        return {"nodes_output": {"n2": "done"}}

    session_id = f"cp-{uuid.uuid4().hex[:8]}"
    executor = _build_executor(saver, n1, n2)

    with pytest.raises(RuntimeError, match="simulated crash"):
        executor.run(GraphState(user_prompt="hi"), session_id=session_id)

    # A fresh executor (new process) resumes from the checkpoint.
    resumed = _build_executor(saver, n1, n2)
    result = resumed.run(GraphState(user_prompt="hi"), session_id=session_id)

    assert dict(result.nodes_output) == {"n1": "ran", "n2": "done"}
    assert calls["n1"] == 1, "completed node must not re-run on resume"
    assert calls["n2"] == 2, "crashed node retries on resume"
