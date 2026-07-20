"""
Lazy graph builder factory.

Uses string-based registration to avoid eagerly importing engine
implementations (and their heavy dependencies) at module load time.
"""
from typing import Dict, Tuple, Type
from mas.engine.domain.base_builder import BaseGraphBuilder
from mas.graph.state.graph_state import GraphState


class GraphBuilderFactory:
    """
    Factory for creating graph execution engine builders.

    Builders are registered lazily by module path + class name
    so that their dependencies (e.g., temporalio, langgraph) are
    only imported when actually needed.
    """

    _BUILT_IN_BUILDERS: Dict[str, Tuple[str, str]] = {
        "langgraph": ("outbound.langgraph.builder", "LangGraphBuilder"),
        "temporal": ("outbound.temporal.builder", "TemporalGraphBuilder"),
    }

    def __init__(self, state_cls: Type[GraphState],
                 checkpointer: object = None) -> None:
        self._state_cls = state_cls
        # LangGraph durability ([2.3], issue #13): passed to builders that
        # accept it; engines that don't checkpoint (Temporal) ignore it.
        self._checkpointer = checkpointer
        self._registry: Dict[str, Tuple[str, str]] = dict(self._BUILT_IN_BUILDERS)

    def register(self, key: str, module_path: str, class_name: str) -> None:
        self._registry[key] = (module_path, class_name)

    def create(self, key: str) -> BaseGraphBuilder:
        if key not in self._registry:
            raise ValueError(f"Unknown graph builder type: {key}")

        module_path, class_name = self._registry[key]

        import importlib
        import inspect
        module = importlib.import_module(module_path)
        builder_cls = getattr(module, class_name)

        if not issubclass(builder_cls, BaseGraphBuilder):
            raise TypeError(f"{builder_cls} must inherit from BaseGraphBuilder")

        if "checkpointer" in inspect.signature(builder_cls.__init__).parameters:
            return builder_cls(self._state_cls, checkpointer=self._checkpointer)
        return builder_cls(self._state_cls)
