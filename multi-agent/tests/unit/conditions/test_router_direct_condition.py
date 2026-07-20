"""
Unit tests for RouterDirectCondition.

Tests the IEM-based routing logic with comprehensive coverage of:
- Basic routing scenarios
- Edge cases and error conditions
- State and context handling
- Performance characteristics
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timedelta
from typing import List, Dict, Any

from mas.elements.conditions.router_direct.router import RouterDirectCondition
from mas.elements.conditions.router_direct.config import RouterDirectConditionConfig
from mas.elements.conditions.router_direct.router_condition_factory import RouterDirectConditionFactory
from mas.elements.conditions.common.models import BranchType, DirectBranchDef
from mas.graph.state.state_view import StateView
from mas.graph.state.graph_state import GraphState, Channel
from mas.graph.models import StepContext
from mas.core.iem.packets import TaskPacket, SystemPacket
from mas.core.iem.models import ElementAddress
from tests.fixtures.iem_testing_tools import PacketFactory, create_test_step_context, create_test_state_view


class TestRouterDirectConditionBasic:
    """Test basic functionality of RouterDirectCondition."""

    @pytest.fixture
    def condition(self):
        """Create a RouterDirectCondition instance."""
        return RouterDirectCondition()

    @pytest.fixture
    def mock_context(self):
        """Create a mock step context."""
        return create_test_step_context(
            uid="test_node",
            adjacent_nodes=["node_a", "node_b", "node_c"]
        )

    @pytest.fixture
    def empty_state_view(self):
        """Create an empty state view."""
        return create_test_state_view()

    def test_condition_initialization(self, condition):
        """Test that condition initializes correctly."""
        assert condition is not None
        assert condition.READS == {Channel.INTER_PACKETS}

    def test_condition_repr(self, condition):
        """Test string representation."""
        repr_str = repr(condition)
        assert "RouterDirectCondition" in repr_str
        assert "IEM-based routing" in repr_str

    def test_get_output_schema(self):
        """Test output schema definition."""
        schema = RouterDirectCondition.get_output_schema()
        assert schema.branch_type == BranchType.DIRECT
        assert schema.direct_config is not None
        assert isinstance(schema.direct_config, DirectBranchDef)
        assert "IEM communication patterns" in schema.direct_config.description
        assert "IEM-based router" in schema.description

    def test_no_context_returns_empty_string(self, condition, empty_state_view):
        """Test that condition returns empty string when no context is set."""
        # Don't set context
        result = condition.run(empty_state_view)
        assert result == "END"

    def test_no_packets_returns_empty_string(self, condition, mock_context, empty_state_view):
        """Test that condition returns empty string when no packets exist."""
        condition.set_context(mock_context)
        result = condition.run(empty_state_view)
        assert result == "END"

    def test_no_outgoing_packets_returns_empty_string(self, condition, mock_context):
        """Test that condition returns empty string when no outgoing packets exist."""
        # Create state with packets not from our node
        state_view = create_test_state_view()
        packet = PacketFactory.create_task_packet(
            src_uid="other_node",  # Not our node
            dst_uid="node_a",
            task_content="Test task"
        )
        state_view.inter_packets = [packet]
        
        condition.set_context(mock_context)
        result = condition.run(state_view)
        assert result == "END"


class TestRouterDirectConditionRouting:
    """Test routing logic with various packet scenarios."""

    @pytest.fixture
    def condition(self):
        return RouterDirectCondition()

    @pytest.fixture
    def mock_context(self):
        return create_test_step_context(
            uid="orchestrator_node",
            adjacent_nodes=["worker_a", "worker_b", "worker_c", "storage_node"]
        )

    def test_single_target_returns_string(self, condition, mock_context):
        """Test routing to single target returns string."""
        state_view = create_test_state_view()
        
        # Create packet from our node to one adjacent node
        packet = PacketFactory.create_task_packet(
            src_uid="orchestrator_node",
            dst_uid="worker_a",
            task_content="Delegate task to worker A"
        )
        state_view.inter_packets = [packet]
        
        condition.set_context(mock_context)
        result = condition.run(state_view)
        
        assert result == "worker_a"
        assert isinstance(result, str)

    def test_multiple_targets_returns_tuple(self, condition, mock_context):
        """Test routing to multiple targets returns sorted tuple."""
        state_view = create_test_state_view()
        
        # Create packets from our node to multiple adjacent nodes
        packets = [
            PacketFactory.create_task_packet(
                src_uid="orchestrator_node",
                dst_uid="worker_c",
                task_content="Task for worker C"
            ),
            PacketFactory.create_task_packet(
                src_uid="orchestrator_node", 
                dst_uid="worker_a",
                task_content="Task for worker A"
            ),
            PacketFactory.create_system_packet(
                src_uid="orchestrator_node",
                dst_uid="storage_node",
                system_event="store_data"
            )
        ]
        state_view.inter_packets = packets
        
        condition.set_context(mock_context)
        result = condition.run(state_view)
        
        assert result == ("storage_node", "worker_a", "worker_c")
        assert isinstance(result, tuple)

    def test_filters_non_adjacent_nodes(self, condition, mock_context):
        """Test that condition filters out non-adjacent nodes."""
        state_view = create_test_state_view()
        
        # Create packets to both adjacent and non-adjacent nodes
        packets = [
            PacketFactory.create_task_packet(
                src_uid="orchestrator_node",
                dst_uid="worker_a",  # Adjacent
                task_content="Task for adjacent worker"
            ),
            PacketFactory.create_task_packet(
                src_uid="orchestrator_node",
                dst_uid="remote_node",  # Not adjacent
                task_content="Task for remote node"
            )
        ]
        state_view.inter_packets = packets
        
        condition.set_context(mock_context)
        result = condition.run(state_view)
        
        # Should only return adjacent node
        assert result == "worker_a"

    def test_filters_expired_packets(self, condition, mock_context):
        """Test that condition filters out expired packets."""
        state_view = create_test_state_view()
        
        # Create expired packet
        expired_packet = PacketFactory.create_expired_packet(
            src_uid="orchestrator_node",
            dst_uid="worker_a",
            expired_seconds_ago=120
        )
        
        # Create fresh packet
        fresh_packet = PacketFactory.create_task_packet(
            src_uid="orchestrator_node",
            dst_uid="worker_b",
            task_content="Fresh task"
        )
        
        state_view.inter_packets = [expired_packet, fresh_packet]
        
        condition.set_context(mock_context)
        result = condition.run(state_view)
        
        # Should only return target of fresh packet
        assert result == "worker_b"

    def test_handles_mixed_packet_types(self, condition, mock_context):
        """Test routing with different packet types."""
        state_view = create_test_state_view()
        
        # Create different types of packets
        packets = [
            PacketFactory.create_task_packet(
                src_uid="orchestrator_node",
                dst_uid="worker_a",
                task_content="Task packet"
            ),
            PacketFactory.create_system_packet(
                src_uid="orchestrator_node",
                dst_uid="worker_b", 
                system_event="system_event"
            ),
            PacketFactory.create_debug_packet(
                src_uid="orchestrator_node",
                dst_uid="worker_c",
                debug_info={"debug": True}
            )
        ]
        state_view.inter_packets = packets
        
        condition.set_context(mock_context)
        result = condition.run(state_view)
        
        assert result == ("worker_a", "worker_b", "worker_c")


class TestRouterDirectConditionEdgeCases:
    """Test edge cases and error scenarios."""

    @pytest.fixture
    def condition(self):
        return RouterDirectCondition()

    def test_malformed_packets_handled_gracefully(self, condition):
        """Test that malformed packets don't crash the condition."""
        context = create_test_step_context(
            uid="test_node",
            adjacent_nodes=["node_a"]
        )
        state_view = create_test_state_view()
        
        # Create malformed packet (missing required attributes)
        malformed_packet = Mock()
        malformed_packet.src = None  # Missing src
        malformed_packet.dst = ElementAddress(uid="node_a")
        malformed_packet.is_expired = False
        
        state_view.inter_packets = [malformed_packet]
        condition.set_context(context)
        
        # Should handle gracefully and return empty
        result = condition.run(state_view)
        assert result == "END"

    def test_packets_without_src_attribute(self, condition):
        """Test handling packets without src attribute."""
        context = create_test_step_context(
            uid="test_node", 
            adjacent_nodes=["node_a"]
        )
        state_view = create_test_state_view()
        
        # Create packet without src
        packet = Mock()
        packet.dst = ElementAddress(uid="node_a")
        packet.is_expired = False
        # No src attribute
        
        state_view.inter_packets = [packet]
        condition.set_context(context)
        
        result = condition.run(state_view)
        assert result == "END"

    def test_packets_without_dst_attribute(self, condition):
        """Test handling packets without dst attribute."""
        context = create_test_step_context(
            uid="test_node",
            adjacent_nodes=["node_a"]
        )
        state_view = create_test_state_view()
        
        # Create packet without dst
        packet = Mock()
        packet.src = ElementAddress(uid="test_node")
        packet.is_expired = False
        # No dst attribute
        
        state_view.inter_packets = [packet]
        condition.set_context(context)
        
        result = condition.run(state_view)
        assert result == "END"

    def test_empty_adjacent_nodes(self, condition):
        """Test behavior with empty adjacent nodes list."""
        context = create_test_step_context(
            uid="isolated_node",
            adjacent_nodes=[]  # No adjacent nodes
        )
        state_view = create_test_state_view()
        
        # Create packet to some node
        packet = PacketFactory.create_task_packet(
            src_uid="isolated_node",
            dst_uid="some_node",
            task_content="Task to unreachable node"
        )
        state_view.inter_packets = [packet]
        
        condition.set_context(context)
        result = condition.run(state_view)
        
        # Should return empty since no nodes are adjacent
        assert result == "END"

    def test_none_adjacent_nodes(self, condition):
        """Test behavior when adjacent_nodes is None."""
        context = Mock()
        context.uid = "test_node"
        context.adjacent_nodes = None
        
        state_view = create_test_state_view()
        packet = PacketFactory.create_task_packet(
            src_uid="test_node",
            dst_uid="some_node"
        )
        state_view.inter_packets = [packet]
        
        condition.set_context(context)
        
        # Should handle gracefully
        result = condition.run(state_view)
        assert result == "END"

    def test_state_without_inter_packets_attribute(self, condition):
        """Test handling state without inter_packets attribute."""
        context = create_test_step_context(
            uid="test_node",
            adjacent_nodes=["node_a"]
        )
        
        # Create state view without inter_packets attribute
        # When getattr(state, 'inter_packets', []) is called on a Mock,
        # it returns the Mock object itself, not the default []
        state_view = Mock()
        # Explicitly delete the attribute to ensure getattr returns default
        if hasattr(state_view, 'inter_packets'):
            delattr(state_view, 'inter_packets')
        
        condition.set_context(context)
        result = condition.run(state_view)
        
        # Should handle gracefully and return empty
        assert result == "END"


class TestRouterDirectConditionFactory:
    """Test the RouterDirectConditionFactory."""

    def test_factory_accepts_correct_type(self):
        """Test that factory accepts correct condition type."""
        factory = RouterDirectConditionFactory()
        config = RouterDirectConditionConfig()
        
        assert factory.accepts(config, "router_direct")

    def test_factory_rejects_wrong_type(self):
        """Test that factory rejects wrong condition type."""
        factory = RouterDirectConditionFactory()
        config = RouterDirectConditionConfig()
        
        assert not factory.accepts(config, "other_condition")

    def test_factory_creates_condition(self):
        """Test that factory creates condition successfully."""
        factory = RouterDirectConditionFactory()
        config = RouterDirectConditionConfig()
        
        condition = factory.create(config)
        
        assert isinstance(condition, RouterDirectCondition)
        assert condition.READS == {Channel.INTER_PACKETS}


class TestRouterDirectConditionConfig:
    """Test the RouterDirectConditionConfig."""

    def test_config_initialization(self):
        """Test that config initializes with correct type."""
        config = RouterDirectConditionConfig()
        assert config.type == "router_direct"

    def test_config_validation(self):
        """Test config validation."""
        # Should not raise any validation errors
        config = RouterDirectConditionConfig()
        assert config.model_validate(config.model_dump()) == config


class TestRouterDirectConditionPerformance:
    """Test performance characteristics."""

    @pytest.fixture
    def condition(self):
        return RouterDirectCondition()

    @pytest.fixture
    def large_context(self):
        """Create context with many adjacent nodes."""
        adjacent_nodes = [f"node_{i}" for i in range(100)]
        return create_test_step_context(
            uid="hub_node",
            adjacent_nodes=adjacent_nodes
        )

    def test_performance_with_many_packets(self, condition, large_context):
        """Test performance with large number of packets."""
        state_view = create_test_state_view()
        
        # Create many packets to different nodes
        packets = []
        for i in range(50):  # 50 packets to different nodes
            packet = PacketFactory.create_task_packet(
                src_uid="hub_node",
                dst_uid=f"node_{i}",
                task_content=f"Task {i}"
            )
            packets.append(packet)
        
        state_view.inter_packets = packets
        condition.set_context(large_context)
        
        # Should complete quickly and return sorted tuple
        result = condition.run(state_view)
        
        assert isinstance(result, tuple)
        assert len(result) == 50
        # String sorting: node_0, node_1, node_10, node_11, ..., node_19, node_2, node_20, ...
        expected_sorted = tuple(sorted(f"node_{i}" for i in range(50)))
        assert result == expected_sorted

    def test_performance_with_many_irrelevant_packets(self, condition, large_context):
        """Test performance when most packets are irrelevant."""
        state_view = create_test_state_view()
        
        # Create many packets from other nodes (irrelevant)
        packets = []
        for i in range(100):
            packet = PacketFactory.create_task_packet(
                src_uid=f"other_node_{i}",  # Not our node
                dst_uid=f"node_{i}",
                task_content=f"Irrelevant task {i}"
            )
            packets.append(packet)
        
        # Add one relevant packet
        relevant_packet = PacketFactory.create_task_packet(
            src_uid="hub_node",
            dst_uid="node_0",
            task_content="Relevant task"
        )
        packets.append(relevant_packet)
        
        state_view.inter_packets = packets
        condition.set_context(large_context)
        
        # Should filter efficiently and return only relevant target
        result = condition.run(state_view)
        assert result == "node_0"

    def test_deduplication_of_targets(self, condition):
        """Test that duplicate targets are deduplicated."""
        context = create_test_step_context(
            uid="test_node",
            adjacent_nodes=["node_a", "node_b"]
        )
        state_view = create_test_state_view()
        
        # Create multiple packets to same nodes
        packets = [
            PacketFactory.create_task_packet(
                src_uid="test_node",
                dst_uid="node_a",
                task_content="Task 1 to A"
            ),
            PacketFactory.create_task_packet(
                src_uid="test_node", 
                dst_uid="node_a",
                task_content="Task 2 to A"
            ),
            PacketFactory.create_task_packet(
                src_uid="test_node",
                dst_uid="node_b", 
                task_content="Task to B"
            ),
            PacketFactory.create_task_packet(
                src_uid="test_node",
                dst_uid="node_a",
                task_content="Task 3 to A"
            )
        ]
        state_view.inter_packets = packets
        condition.set_context(context)
        
        result = condition.run(state_view)
        
        # Should deduplicate and return sorted
        assert result == ("node_a", "node_b")
        assert isinstance(result, tuple)
