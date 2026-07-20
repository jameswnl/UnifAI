from typing import ClassVar, List, Optional

from mas.elements.nodes.common.base_node import BaseNode
from mas.elements.nodes.common.capabilities.iem_capable import IEMCapableMixin
from mas.elements.nodes.common.workload import AgentResult
from mas.elements.nodes.common.workload.task import Task
from mas.graph.state.graph_state import Channel
from mas.graph.state.state_view import StateView


class MockAgentNode(IEMCapableMixin, BaseNode):
    """
    Test stub: replies to every incoming TaskPacket with a fixed echo
    message (or an echo of the task content), following the same IEM
    contract as real agent nodes so downstream nodes (e.g. final_answer)
    can collect its AgentResult.
    """

    READS: ClassVar[set[str]] = {Channel.USER_PROMPT, Channel.INTER_PACKETS}
    WRITES: ClassVar[set[str]] = {Channel.NODES_OUTPUT, Channel.INTER_PACKETS}

    def __init__(self,
                 *,
                 name: str = "mock_agent",
                 echo_message: Optional[str] = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.echo_message = echo_message
        self._responses: List[AgentResult] = []

    def run(self, state: StateView) -> StateView:
        self._responses = []
        self.process_packets(state)

        if self._responses:
            # nodes_output is a Dict[str, str] channel keyed by node uid
            state[Channel.NODES_OUTPUT] = {self.uid: self._responses[-1].content}
        return state

    def handle_task_packet(self, packet) -> None:
        task = packet.extract_task()
        response = (self.echo_message
                    if self.echo_message is not None
                    else f"Mock echo: {task.content}")

        result = AgentResult(
            content=response,
            agent_id=self.uid,
            agent_name=self.display_name or self.name,
            success=True,
        )
        self.broadcast_task(Task.respond_success(task, result, processed_by=self.uid))
        self._responses.append(result)
