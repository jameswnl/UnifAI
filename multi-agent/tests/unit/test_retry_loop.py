"""Unit tests for the app-level retry loop ([2.1], issue #11)."""

import pytest

from mas.engine.retry import (
    RetriesExhaustedError,
    run_node_with_retry,
    wrap_step_func,
)
from mas.graph.state.graph_state import GraphState
from mas.blueprints.models.blueprint import StepMeta


def _flaky(fail_times: int):
    calls = {"n": 0}

    def run():
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise ValueError(f"boom {calls['n']}")
        return "ok"

    return run, calls


@pytest.mark.unit
def test_no_retry_by_default():
    state = GraphState()
    run, calls = _flaky(fail_times=1)
    with pytest.raises(ValueError):
        run_node_with_retry("step1", run, state, StepMeta())
    assert calls["n"] == 1
    assert len(state["failure_history"]) == 1
    # no retry => no adaptation message
    assert state["messages"] == []


@pytest.mark.unit
def test_retry_succeeds_with_failure_context():
    state = GraphState()
    run, calls = _flaky(fail_times=2)
    result = run_node_with_retry("step1", run, state,
                                 StepMeta(max_retries=2))
    assert result == "ok"
    assert calls["n"] == 3
    assert [r["attempt"] for r in state["failure_history"]] == [1, 2]
    # each failed-but-retriable attempt leaves an adaptation message
    retry_msgs = [m for m in state["messages"]
                  if m.metadata.get("retry_context")]
    assert len(retry_msgs) == 2
    assert "boom 1" in retry_msgs[0].content
    assert "Do not repeat" in retry_msgs[0].content


@pytest.mark.unit
def test_exhaustion_raises_with_history():
    state = GraphState()
    run, calls = _flaky(fail_times=99)
    with pytest.raises(RetriesExhaustedError) as ei:
        run_node_with_retry("fix_step", run, state, StepMeta(max_retries=1))
    assert calls["n"] == 2
    assert ei.value.node_uid == "fix_step"
    assert len(ei.value.attempts) == 2
    assert len(state["failure_history"]) == 2


@pytest.mark.unit
def test_step_meta_declared_in_blueprint_yaml():
    meta = StepMeta(max_retries=2, retry_backoff_s=1.5)
    assert meta.max_retries == 2
    assert meta.retry_backoff_s == 1.5


@pytest.mark.unit
def test_wrap_step_func_without_context_runs_once():
    state = GraphState()

    class Node:
        calls = 0

        def __call__(self, s, config=None):
            Node.calls += 1
            raise RuntimeError("nope")

    wrapped = wrap_step_func("u1", Node())
    with pytest.raises(RuntimeError):
        wrapped(state, config={})
    assert Node.calls == 1
