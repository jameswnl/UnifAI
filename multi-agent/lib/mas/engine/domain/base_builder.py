from abc import ABC, abstractmethod
from typing import Any, Callable, Dict
from mas.graph.rt_graph_plan import RTGraphPlan
from mas.engine.domain.base_executor import BaseGraphExecutor


class BaseGraphBuilder(ABC):
    """
    Abstract interface for any graph execution engine.

    Subclasses must implement node/edge wiring and entry/exit.
    """

    @abstractmethod
    def add_node(self, uid: str, func: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        """
        Register a node in the engine under `uid` with its execution function.
        """
        ...

    @abstractmethod
    def add_edge(self, from_node: str, to_node: str) -> None:
        """
        Add an unconditional edge: from_node → to_node.
        """
        ...

    @abstractmethod
    def add_conditional_edge(
            self,
            from_node: str,
            condition: Callable[[Dict[str, Any]], Any],
            branches: Dict[Any, str]
    ) -> None:
        """
        Add one or more edges out of `from_node` guarded by `condition`.
        `branches` maps condition-output → next‐node uid.
        """
        ...

    @abstractmethod
    def set_entry(self, uid: str) -> None:
        """
        Mark `uid` as the graph's entry point.
        """
        ...

    @abstractmethod
    def set_exit(self, uid: str) -> None:
        """
        Mark `uid` as the graph's exit / finish point.
        """
        ...

    @abstractmethod
    def build_executor(self) -> BaseGraphExecutor:
        """
        Compile and return the engine's executable graph object.
        """
        ...

    def compile_from_plan(
            self,
            plan: RTGraphPlan) -> BaseGraphExecutor:
        """
        Default helper: wires up all steps, dependencies, conditionals,
        and identifies entry/exit, then builds.
        """
        from mas.engine.retry import wrap_step_func
        for step in plan.steps:
            # Per-step retry with failure history ([2.1], issue #11)
            self.add_node(step.uid, wrap_step_func(step.uid, step.func))

        for step in plan.steps:
            for dep in step.after:
                self.add_edge(dep, step.uid)

            if step.exit_condition and step.branches:
                self.add_conditional_edge(step.uid, step.exit_condition, step.branches)

        roots = plan.get_roots()
        leaves = plan.get_leaves()
        if not roots:
            raise ValueError("Plan has no root steps.")
        if not leaves:
            raise ValueError("Plan has no leaf steps.")
        self.set_entry(roots[0].uid)
        self.set_exit(leaves[0].uid)

        return self.build_executor()
