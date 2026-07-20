from typing import Type, Callable, Any, Dict, Optional
from langgraph.graph import StateGraph, END
from mas.engine.domain.base_builder import BaseGraphBuilder
from mas.engine.domain.base_executor import BaseGraphExecutor
from mas.graph.state.graph_state import GraphState
from outbound.langgraph.executor import LangGraphExecutor


class LangGraphBuilder(BaseGraphBuilder):
    """
    Concrete GraphBuilder that targets LangGraph's StateGraph API.

    An optional ``checkpointer`` ([2.3], issue #13) makes execution
    durable: LangGraph persists state after every node keyed by the
    session id (thread_id), so a crashed run resumes from the last
    completed node instead of restarting the graph.
    """

    def __init__(self, state_cls: Type[GraphState],
                 checkpointer: Optional[object] = None) -> None:
        self._graph = StateGraph(state_cls)
        self._checkpointer = checkpointer

    def add_node(self, uid: str, func: Any) -> None:
        self._graph.add_node(uid, func)

    def add_edge(self, from_node: str, to_node: str) -> None:
        self._graph.add_edge(from_node, to_node)

    def add_conditional_edge(
            self,
            from_node: str,
            condition: Callable[[Dict[str, Any]], Any],
            branches: Dict[Any, str]
    ) -> None:
        self._graph.add_conditional_edges(
            from_node,
            condition,
            branches
        )

    def set_entry(self, uid: str) -> None:
        self._graph.set_entry_point(uid)

    def set_exit(self, uid: str) -> None:
        self._graph.set_finish_point(uid or END)

    def build_executor(self) -> BaseGraphExecutor:
        compiled = self._graph.compile(checkpointer=self._checkpointer)
        return LangGraphExecutor(compiled, checkpointed=self._checkpointer is not None)
