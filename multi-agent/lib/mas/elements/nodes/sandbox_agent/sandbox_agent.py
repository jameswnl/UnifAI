"""Sandbox agent node — runs a step in an ephemeral container."""

from __future__ import annotations

import logging
from typing import Any

from mas.elements.nodes.common.base_node import BaseNode
from mas.graph.state.graph_state import Channel
from mas.graph.state.state_view import StateView
from mas.sandbox.client import (
    SandboxClient,
    SandboxRunRequest,
    SandboxRunResponse,
    TranscriptEvent,
)
from mas.sandbox.spawner import (
    SandboxSpawner,
    SpawnRequest,
    SpawnResult,
    compute_sandbox_name,
)

logger = logging.getLogger(__name__)


class SandboxAgentNode(BaseNode):
    READS = {Channel.USER_PROMPT}
    WRITES = {Channel.NODES_OUTPUT}

    def __init__(
        self,
        *,
        spawner: SandboxSpawner,
        image: str,
        system_prompt: str = "",
        output_schema: dict[str, Any] | None = None,
        allowed_tools: list[str] | None = None,
        denied_tools: list[str] | None = None,
        timeout_seconds: int = 300,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._spawner = spawner
        self._image = image
        self._system_prompt = system_prompt
        self._output_schema = output_schema
        self._allowed_tools = allowed_tools
        self._denied_tools = denied_tools
        self._timeout = timeout_seconds
        self._client = SandboxClient(timeout=float(timeout_seconds))

    def run(self, state: StateView) -> StateView:
        ctx = self.get_context()
        session_id = getattr(ctx, "session_id", "unknown")
        node_uid = ctx.uid
        attempt = state.get(Channel.FAILURE_HISTORY, {}).get(node_uid, {}).get("attempt", 0)

        sandbox_name = compute_sandbox_name(session_id, node_uid, attempt)

        prompt = state.get(Channel.USER_PROMPT, "")
        context = self._build_context(state)

        request = SpawnRequest(
            name=sandbox_name,
            image=self._image,
            env={"AGENT_EVENT_LOG": "/tmp/agent-events.jsonl"},
            labels={
                "session-id": session_id,
                "node-uid": node_uid,
            },
            timeout_seconds=self._timeout,
        )

        endpoint = ""
        try:
            result = self._spawner.spawn(request)
            endpoint = result.endpoint

            if not self._spawner.wait_ready(
                endpoint, timeout=float(self._timeout), health_path="/health"
            ):
                raise RuntimeError(
                    f"Sandbox '{sandbox_name}' never became ready"
                )

            run_request = SandboxRunRequest(
                query=prompt,
                context=context,
                systemPrompt=self._system_prompt,
                outputSchema=self._output_schema,
                allowedTools=self._allowed_tools,
                deniedTools=self._denied_tools,
            )

            response = self._client.run(endpoint, run_request)

            events = self._client.collect_events(endpoint)
            self._emit_transcript_events(state, events)

            if not response.success:
                raise RuntimeError(
                    f"Sandbox agent failed: {response.error}"
                )

            output = response.summary or str(response.output)
            state[Channel.NODES_OUTPUT] = output

        finally:
            if endpoint:
                try:
                    self._spawner.destroy(sandbox_name)
                except Exception:
                    logger.warning(
                        "Failed to destroy sandbox '%s'", sandbox_name, exc_info=True
                    )

        return state

    def _build_context(self, state: StateView) -> dict[str, Any]:
        context: dict[str, Any] = {}
        nodes_output = state.get(Channel.NODES_OUTPUT, None)
        if nodes_output:
            context["prior_output"] = nodes_output
        messages = state.get(Channel.MESSAGES, None)
        if messages:
            context["messages"] = [
                {"role": getattr(m, "role", "user"), "content": getattr(m, "content", str(m))}
                for m in (messages if isinstance(messages, list) else [messages])
            ]
        return context

    def _emit_transcript_events(
        self, state: StateView, events: list[TranscriptEvent]
    ) -> None:
        if not events:
            return
        for event in events:
            try:
                self._stream(
                    {
                        "type": "sandbox_event",
                        "event_type": event.type,
                        "ts": event.ts,
                        "data": event.data,
                    }
                )
            except Exception:
                pass
