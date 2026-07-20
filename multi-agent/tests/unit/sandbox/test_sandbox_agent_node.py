"""Unit tests for sandbox_agent_node catalog element."""

from unittest.mock import MagicMock, patch

import pytest

from mas.sandbox.spawner import SpawnResult
from mas.sandbox.client import SandboxRunResponse
from mas.elements.nodes.sandbox_agent.sandbox_agent import SandboxAgentNode
from mas.elements.nodes.sandbox_agent.config import SandboxAgentNodeConfig
from mas.elements.nodes.sandbox_agent.identifiers import Identifier
from mas.elements.nodes.sandbox_agent.sandbox_agent_node_factory import (
    SandboxAgentNodeFactory,
)
from mas.graph.state.graph_state import Channel


@pytest.fixture
def mock_spawner():
    spawner = MagicMock()
    spawner.spawn.return_value = SpawnResult(name="sb-abc", endpoint="http://localhost:9999")
    spawner.wait_ready.return_value = True
    spawner.destroy.return_value = None
    return spawner


@pytest.fixture
def node(mock_spawner):
    return SandboxAgentNode(
        spawner=mock_spawner,
        image="sandbox:latest",
        system_prompt="You are a diagnostic agent.",
        timeout_seconds=60,
    )


class TestSandboxAgentNodeConfig:
    def test_defaults(self):
        cfg = SandboxAgentNodeConfig()
        assert cfg.type == "sandbox_agent_node"
        assert cfg.timeout_seconds == 300
        assert cfg.allowed_tools is None
        assert cfg.denied_tools is None

    def test_custom(self):
        cfg = SandboxAgentNodeConfig(
            image="custom:v1",
            system_prompt="Be careful.",
            allowed_tools=["kubectl"],
            timeout_seconds=120,
        )
        assert cfg.image == "custom:v1"
        assert cfg.allowed_tools == ["kubectl"]


class TestSandboxAgentNodeFactory:
    def test_accepts_correct_type(self):
        f = SandboxAgentNodeFactory()
        assert f.accepts(SandboxAgentNodeConfig(), Identifier.TYPE)

    def test_rejects_wrong_type(self):
        f = SandboxAgentNodeFactory()
        assert not f.accepts(SandboxAgentNodeConfig(), "mock_agent_node")

    def test_create_requires_spawner(self):
        f = SandboxAgentNodeFactory()
        with pytest.raises(ValueError, match="sandbox_spawner"):
            f.create(SandboxAgentNodeConfig(image="img"))

    def test_create_requires_image(self):
        f = SandboxAgentNodeFactory()
        with pytest.raises(ValueError, match="image"):
            f.create(SandboxAgentNodeConfig(), sandbox_spawner=MagicMock())

    def test_create_success(self):
        f = SandboxAgentNodeFactory()
        node = f.create(
            SandboxAgentNodeConfig(image="sandbox:v1"),
            sandbox_spawner=MagicMock(),
        )
        assert isinstance(node, SandboxAgentNode)


class TestSandboxAgentNodeExecution:
    @patch("mas.elements.nodes.sandbox_agent.sandbox_agent.SandboxClient")
    def test_run_success(self, MockClient, mock_spawner):
        client_instance = MockClient.return_value
        client_instance.run.return_value = SandboxRunResponse(
            success=True,
            output={"diagnosis": "healthy"},
            summary="All systems operational",
        )
        client_instance.collect_events.return_value = []

        node = SandboxAgentNode(
            spawner=mock_spawner,
            image="sandbox:latest",
        )

        # Set up context
        mock_ctx = MagicMock()
        mock_ctx.uid = "diag_node"
        mock_ctx.session_id = "sess-1"
        mock_ctx.adjacent_nodes = []
        node.set_context(mock_ctx)

        # Build state
        from mas.graph.state.graph_state import Channel
        state = MagicMock()
        state.get.side_effect = lambda ch, default=None: {
            Channel.USER_PROMPT: "Check system health",
            Channel.FAILURE_HISTORY: {},
            Channel.NODES_OUTPUT: None,
            Channel.MESSAGES: None,
        }.get(ch, default)
        state.__setitem__ = MagicMock()
        state.__getitem__ = MagicMock(return_value=[])

        result = node.run(state)

        mock_spawner.spawn.assert_called_once()
        mock_spawner.wait_ready.assert_called_once()
        client_instance.run.assert_called_once()
        mock_spawner.destroy.assert_called_once()
        state.__setitem__.assert_called_with(
            Channel.NODES_OUTPUT, "All systems operational"
        )

    @patch("mas.elements.nodes.sandbox_agent.sandbox_agent.SandboxClient")
    def test_run_destroys_on_failure(self, MockClient, mock_spawner):
        client_instance = MockClient.return_value
        client_instance.run.return_value = SandboxRunResponse(
            success=False,
            error="agent crashed",
        )
        client_instance.collect_events.return_value = []

        node = SandboxAgentNode(
            spawner=mock_spawner,
            image="sandbox:latest",
        )

        mock_ctx = MagicMock()
        mock_ctx.uid = "node_a"
        mock_ctx.session_id = "sess-1"
        mock_ctx.adjacent_nodes = []
        node.set_context(mock_ctx)

        state = MagicMock()
        state.get.side_effect = lambda ch, default=None: {
            Channel.USER_PROMPT: "test",
            Channel.FAILURE_HISTORY: {},
            Channel.NODES_OUTPUT: None,
            Channel.MESSAGES: None,
        }.get(ch, default)

        with pytest.raises(RuntimeError, match="agent crashed"):
            node.run(state)

        # Must still destroy even on failure
        mock_spawner.destroy.assert_called_once()

    @patch("mas.elements.nodes.sandbox_agent.sandbox_agent.SandboxClient")
    def test_run_destroys_on_spawn_failure(self, MockClient, mock_spawner):
        mock_spawner.wait_ready.return_value = False

        node = SandboxAgentNode(
            spawner=mock_spawner,
            image="sandbox:latest",
        )

        mock_ctx = MagicMock()
        mock_ctx.uid = "node_a"
        mock_ctx.session_id = "sess-1"
        mock_ctx.adjacent_nodes = []
        node.set_context(mock_ctx)

        state = MagicMock()
        state.get.side_effect = lambda ch, default=None: {
            Channel.USER_PROMPT: "test",
            Channel.FAILURE_HISTORY: {},
        }.get(ch, default)

        with pytest.raises(RuntimeError, match="never became ready"):
            node.run(state)

        mock_spawner.destroy.assert_called_once()


class TestSandboxAgentNodeAutoDiscovery:
    def test_spec_registers(self):
        from mas.catalog.element_registry import ElementRegistry
        registry = ElementRegistry.__new__(ElementRegistry)
        registry._specs = {}
        registry.auto_discover()
        assert registry.has_spec("nodes", "sandbox_agent_node")
