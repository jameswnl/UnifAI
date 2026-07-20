"""
Unit tests for IEM routing utilities.

Tests the get_outgoing_targets function with comprehensive coverage of:
- Basic packet analysis
- Edge cases and error conditions
- Performance characteristics
- Integration with RouterDirectCondition
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timedelta
from typing import List, Dict, Any, Set

from mas.core.iem.utils import get_outgoing_targets
from mas.core.iem.packets import TaskPacket, SystemPacket, DebugPacket
from mas.core.iem.models import ElementAddress
from mas.graph.state.state_view import StateView
from mas.graph.models import StepContext
from tests.fixtures.iem_testing_tools import (
    PacketFactory, create_test_step_context, create_test_state_view
)


class TestGetOutgoingTargetsBasic:
    """Test basic functionality of get_outgoing_targets."""

    def test_empty_packets_returns_empty_set(self):
        """Test that empty packet list returns empty set."""
        state = Mock()
        state.inter_packets = []
        
        context = create_test_step_context(
            uid="test_node",
            adjacent_nodes=["node_a", "node_b"]
        )
        
        result = get_outgoing_targets(state, context)
        assert result == set()

    def test_no_inter_packets_attribute_returns_empty_set(self):
        """Test handling when state has no inter_packets attribute."""
        state = Mock()
        # No inter_packets attribute
        
        context = create_test_step_context(
            uid="test_node",
            adjacent_nodes=["node_a"]
        )
        
        result = get_outgoing_targets(state, context)
        assert result == set()

    def test_single_outgoing_packet_returns_target(self):
        """Test single outgoing packet returns correct target."""
        state = Mock()
        packet = PacketFactory.create_task_packet(
            src_uid="my_node",
            dst_uid="target_node",
            task_content="Test task"
        )
        state.inter_packets = [packet]
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["target_node", "other_node"]
        )
        
        result = get_outgoing_targets(state, context)
        assert result == {"target_node"}

    def test_multiple_outgoing_packets_returns_all_targets(self):
        """Test multiple outgoing packets return all unique targets."""
        state = Mock()
        packets = [
            PacketFactory.create_task_packet(
                src_uid="my_node",
                dst_uid="target_a",
                task_content="Task A"
            ),
            PacketFactory.create_task_packet(
                src_uid="my_node",
                dst_uid="target_b", 
                task_content="Task B"
            ),
            PacketFactory.create_system_packet(
                src_uid="my_node",
                dst_uid="target_c",
                system_event="event_c"
            )
        ]
        state.inter_packets = packets
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["target_a", "target_b", "target_c", "unused_node"]
        )
        
        result = get_outgoing_targets(state, context)
        assert result == {"target_a", "target_b", "target_c"}

    def test_duplicate_targets_are_deduplicated(self):
        """Test that duplicate targets are deduplicated."""
        state = Mock()
        packets = [
            PacketFactory.create_task_packet(
                src_uid="my_node",
                dst_uid="target_node",
                task_content="Task 1"
            ),
            PacketFactory.create_task_packet(
                src_uid="my_node",
                dst_uid="target_node",
                task_content="Task 2"
            ),
            PacketFactory.create_system_packet(
                src_uid="my_node",
                dst_uid="target_node",
                system_event="system_event"
            )
        ]
        state.inter_packets = packets
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["target_node"]
        )
        
        result = get_outgoing_targets(state, context)
        assert result == {"target_node"}


class TestGetOutgoingTargetsFiltering:
    """Test filtering logic of get_outgoing_targets."""

    def test_filters_non_adjacent_nodes(self):
        """Test that non-adjacent nodes are filtered out."""
        state = Mock()
        packets = [
            PacketFactory.create_task_packet(
                src_uid="my_node",
                dst_uid="adjacent_node",
                task_content="To adjacent"
            ),
            PacketFactory.create_task_packet(
                src_uid="my_node",
                dst_uid="remote_node",  # Not in adjacent_nodes
                task_content="To remote"
            )
        ]
        state.inter_packets = packets
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["adjacent_node"]  # remote_node not included
        )
        
        result = get_outgoing_targets(state, context)
        assert result == {"adjacent_node"}

    def test_filters_packets_from_other_nodes(self):
        """Test that packets from other nodes are filtered out."""
        state = Mock()
        packets = [
            PacketFactory.create_task_packet(
                src_uid="my_node",  # From our node
                dst_uid="target_node",
                task_content="My task"
            ),
            PacketFactory.create_task_packet(
                src_uid="other_node",  # From different node
                dst_uid="target_node",
                task_content="Other task"
            )
        ]
        state.inter_packets = packets
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["target_node"]
        )
        
        result = get_outgoing_targets(state, context)
        assert result == {"target_node"}

    def test_filters_expired_packets(self):
        """Test that expired packets are filtered out."""
        state = Mock()
        
        # Create expired packet
        expired_packet = PacketFactory.create_expired_packet(
            src_uid="my_node",
            dst_uid="target_node",
            expired_seconds_ago=120
        )
        
        # Create fresh packet
        fresh_packet = PacketFactory.create_task_packet(
            src_uid="my_node",
            dst_uid="other_target",
            task_content="Fresh task"
        )
        
        state.inter_packets = [expired_packet, fresh_packet]
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["target_node", "other_target"]
        )
        
        result = get_outgoing_targets(state, context)
        # Should only include target of fresh packet
        assert result == {"other_target"}

    def test_empty_adjacent_nodes_returns_empty_set(self):
        """Test that empty adjacent nodes list returns empty set."""
        state = Mock()
        packet = PacketFactory.create_task_packet(
            src_uid="isolated_node",
            dst_uid="some_node",
            task_content="Isolated task"
        )
        state.inter_packets = [packet]
        
        context = create_test_step_context(
            uid="isolated_node",
            adjacent_nodes=[]  # No adjacent nodes
        )
        
        result = get_outgoing_targets(state, context)
        assert result == set()

    def test_none_adjacent_nodes_returns_empty_set(self):
        """Test handling when adjacent_nodes is None."""
        state = Mock()
        packet = PacketFactory.create_task_packet(
            src_uid="test_node",
            dst_uid="some_node"
        )
        state.inter_packets = [packet]
        
        context = Mock()
        context.uid = "test_node"
        context.adjacent_nodes = None
        
        result = get_outgoing_targets(state, context)
        assert result == set()


class TestGetOutgoingTargetsEdgeCases:
    """Test edge cases and error scenarios."""

    def test_malformed_packets_handled_gracefully(self):
        """Test that malformed packets don't crash the function."""
        state = Mock()
        
        # Create malformed packet without required attributes
        malformed_packet = Mock()
        malformed_packet.src = None  # Missing src
        malformed_packet.dst = ElementAddress(uid="target")
        malformed_packet.is_expired = False
        
        # Create normal packet
        normal_packet = PacketFactory.create_task_packet(
            src_uid="my_node",
            dst_uid="target",
            task_content="Normal task"
        )
        
        state.inter_packets = [malformed_packet, normal_packet]
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["target"]
        )
        
        # Should handle gracefully and return target from normal packet
        result = get_outgoing_targets(state, context)
        assert result == {"target"}

    def test_packets_without_src_attribute(self):
        """Test handling packets without src attribute."""
        state = Mock()
        
        packet = Mock()
        packet.dst = ElementAddress(uid="target")
        packet.is_expired = False
        # No src attribute
        
        state.inter_packets = [packet]
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["target"]
        )
        
        result = get_outgoing_targets(state, context)
        assert result == set()

    def test_packets_without_dst_attribute(self):
        """Test handling packets without dst attribute."""
        state = Mock()
        
        packet = Mock()
        packet.src = ElementAddress(uid="my_node")
        packet.is_expired = False
        # No dst attribute
        
        state.inter_packets = [packet]
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["target"]
        )
        
        result = get_outgoing_targets(state, context)
        assert result == set()

    def test_packets_without_is_expired_attribute(self):
        """Test handling packets without is_expired attribute."""
        state = Mock()
        
        packet = Mock()
        packet.src = ElementAddress(uid="my_node")
        packet.dst = ElementAddress(uid="target")
        # No is_expired attribute
        
        state.inter_packets = [packet]
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["target"]
        )
        
        # Should handle gracefully (assume not expired)
        result = get_outgoing_targets(state, context)
        assert result == set()  # Will fail hasattr check

    def test_packets_with_invalid_address_objects(self):
        """Test handling packets with invalid address objects."""
        state = Mock()
        
        packet = Mock()
        packet.src = "invalid_address_string"  # Should be ElementAddress
        packet.dst = ElementAddress(uid="target")
        packet.is_expired = False
        
        state.inter_packets = [packet]
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["target"]
        )
        
        result = get_outgoing_targets(state, context)
        assert result == set()


class TestGetOutgoingTargetsPerformance:
    """Test performance characteristics."""

    def test_performance_with_many_packets(self):
        """Test performance with large number of packets."""
        state = Mock()
        
        # Create many packets from our node
        our_packets = []
        for i in range(100):
            packet = PacketFactory.create_task_packet(
                src_uid="hub_node",
                dst_uid=f"target_{i % 10}",  # 10 unique targets
                task_content=f"Task {i}"
            )
            our_packets.append(packet)
        
        # Add many irrelevant packets
        other_packets = []
        for i in range(500):
            packet = PacketFactory.create_task_packet(
                src_uid=f"other_node_{i}",
                dst_uid=f"target_{i % 10}",
                task_content=f"Other task {i}"
            )
            other_packets.append(packet)
        
        state.inter_packets = our_packets + other_packets
        
        context = create_test_step_context(
            uid="hub_node",
            adjacent_nodes=[f"target_{i}" for i in range(10)]
        )
        
        # Should efficiently filter and return unique targets
        result = get_outgoing_targets(state, context)
        expected_targets = {f"target_{i}" for i in range(10)}
        assert result == expected_targets

    def test_performance_with_many_adjacent_nodes(self):
        """Test performance with large adjacency list."""
        state = Mock()
        
        # Create packets to subset of adjacent nodes
        packets = [
            PacketFactory.create_task_packet(
                src_uid="central_node",
                dst_uid="target_5",
                task_content="Task 1"
            ),
            PacketFactory.create_task_packet(
                src_uid="central_node",
                dst_uid="target_50",
                task_content="Task 2"
            )
        ]
        state.inter_packets = packets
        
        # Large adjacency list
        adjacent_nodes = [f"target_{i}" for i in range(1000)]
        context = create_test_step_context(
            uid="central_node",
            adjacent_nodes=adjacent_nodes
        )
        
        # Should efficiently find targets in large adjacency set
        result = get_outgoing_targets(state, context)
        assert result == {"target_5", "target_50"}


class TestGetOutgoingTargetsPacketTypes:
    """Test with different packet types."""

    def test_handles_task_packets(self):
        """Test handling TaskPacket objects."""
        state = Mock()
        packet = PacketFactory.create_task_packet(
            src_uid="my_node",
            dst_uid="target",
            task_content="Task packet test"
        )
        state.inter_packets = [packet]
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["target"]
        )
        
        result = get_outgoing_targets(state, context)
        assert result == {"target"}

    def test_handles_system_packets(self):
        """Test handling SystemPacket objects."""
        state = Mock()
        packet = PacketFactory.create_system_packet(
            src_uid="my_node",
            dst_uid="target",
            system_event="test_event"
        )
        state.inter_packets = [packet]
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["target"]
        )
        
        result = get_outgoing_targets(state, context)
        assert result == {"target"}

    def test_handles_debug_packets(self):
        """Test handling DebugPacket objects."""
        state = Mock()
        packet = PacketFactory.create_debug_packet(
            src_uid="my_node",
            dst_uid="target",
            debug_info={"test": True}
        )
        state.inter_packets = [packet]
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["target"]
        )
        
        result = get_outgoing_targets(state, context)
        assert result == {"target"}

    def test_handles_mixed_packet_types(self):
        """Test handling mixed packet types."""
        state = Mock()
        packets = [
            PacketFactory.create_task_packet(
                src_uid="my_node",
                dst_uid="target_a",
                task_content="Task"
            ),
            PacketFactory.create_system_packet(
                src_uid="my_node",
                dst_uid="target_b",
                system_event="event"
            ),
            PacketFactory.create_debug_packet(
                src_uid="my_node",
                dst_uid="target_c",
                debug_info={"debug": True}
            )
        ]
        state.inter_packets = packets
        
        context = create_test_step_context(
            uid="my_node",
            adjacent_nodes=["target_a", "target_b", "target_c"]
        )
        
        result = get_outgoing_targets(state, context)
        assert result == {"target_a", "target_b", "target_c"}


class TestGetOutgoingTargetsIntegrationWithCondition:
    """Test integration with RouterDirectCondition."""

    def test_integration_single_target_scenario(self):
        """Test integration scenario returning single target."""
        from mas.elements.conditions.router_direct.router import RouterDirectCondition
        
        # Set up condition
        condition = RouterDirectCondition()
        context = create_test_step_context(
            uid="orchestrator",
            adjacent_nodes=["worker_a", "worker_b"]
        )
        condition.set_context(context)
        
        # Set up state with single outgoing packet
        state = Mock()
        packet = PacketFactory.create_task_packet(
            src_uid="orchestrator",
            dst_uid="worker_a",
            task_content="Single task"
        )
        state.inter_packets = [packet]
        
        # Test that utility function and condition agree
        util_result = get_outgoing_targets(state, context)
        condition_result = condition.run(state)
        
        assert util_result == {"worker_a"}
        assert condition_result == "worker_a"

    def test_integration_multiple_targets_scenario(self):
        """Test integration scenario returning multiple targets."""
        from mas.elements.conditions.router_direct.router import RouterDirectCondition
        
        # Set up condition
        condition = RouterDirectCondition()
        context = create_test_step_context(
            uid="orchestrator",
            adjacent_nodes=["worker_a", "worker_b", "worker_c"]
        )
        condition.set_context(context)
        
        # Set up state with multiple outgoing packets
        state = Mock()
        packets = [
            PacketFactory.create_task_packet(
                src_uid="orchestrator",
                dst_uid="worker_a",
                task_content="Task A"
            ),
            PacketFactory.create_task_packet(
                src_uid="orchestrator",
                dst_uid="worker_c",
                task_content="Task C"
            )
        ]
        state.inter_packets = packets
        
        # Test that utility function and condition agree
        util_result = get_outgoing_targets(state, context)
        condition_result = condition.run(state)
        
        assert util_result == {"worker_a", "worker_c"}
        assert condition_result == ("worker_a", "worker_c")

    def test_integration_no_targets_scenario(self):
        """Test integration scenario with no targets."""
        from mas.elements.conditions.router_direct.router import RouterDirectCondition
        
        # Set up condition
        condition = RouterDirectCondition()
        context = create_test_step_context(
            uid="orchestrator",
            adjacent_nodes=["worker_a", "worker_b"]
        )
        condition.set_context(context)
        
        # Set up state with no relevant packets
        state = Mock()
        state.inter_packets = []
        
        # Test that utility function and condition agree
        util_result = get_outgoing_targets(state, context)
        condition_result = condition.run(state)
        
        assert util_result == set()
        assert condition_result == "END"
