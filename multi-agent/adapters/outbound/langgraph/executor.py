from typing import Any

from mas.engine.domain.base_executor import BaseGraphExecutor
from mas.engine.domain.types import DEFAULT_RECURSION_LIMIT
from mas.graph.state.graph_state import GraphState


class LangGraphExecutor(BaseGraphExecutor):
    """
    Wraps a LangGraph compiled graph (which has .invoke),
    exposing it as a BaseGraphExecutor with .run().

    When ``checkpointed`` is set ([2.3], issue #13), the run is keyed by
    ``session_id`` as the LangGraph ``thread_id`` and state is persisted
    after every node. If a checkpoint with pending work already exists
    for the session (a crashed run being resumed), execution continues
    from the last completed node — invoke(None) — instead of restarting.
    """

    def __init__(
        self,
        compiled_graph: Any,
        recursion_limit: int = DEFAULT_RECURSION_LIMIT,
        checkpointed: bool = False,
    ) -> None:
        self._compiled = compiled_graph
        self._recursion_limit = recursion_limit
        self._checkpointed = checkpointed

    def run(self, initial_state: GraphState, *, session_id: str = "") -> GraphState:
        config: dict = {"recursion_limit": self._recursion_limit}
        graph_input: Any = initial_state

        if self._checkpointed and session_id:
            config["configurable"] = {"thread_id": session_id}
            # Resume: if a checkpoint has pending next nodes, continue from
            # it rather than re-seeding the initial state.
            snapshot = self._compiled.get_state(config)
            if snapshot is not None and getattr(snapshot, "next", ()):
                graph_input = None

        result = self._compiled.invoke(graph_input, config=config)
        return GraphState.model_validate(result) if isinstance(result, dict) else result

    def get_state(self) -> Any:
        return self._compiled.get_state(None)
