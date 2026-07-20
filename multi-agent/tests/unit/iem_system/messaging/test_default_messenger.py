"""
Unit tests for DefaultInterMessenger - Core IEM messenger implementation.

Tests packet sending, receiving, acknowledgment, adjacency enforcement,
middleware integration, and error handling.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

from mas.core.iem.messenger import DefaultInterMessenger
from mas.core.iem.interfaces import MessengerMiddleware
from mas.core.iem.models import ElementAddress, PacketType
from mas.core.iem.packets import BaseIEMPacket, TaskPacket
from mas.core.iem.exceptions import IEMAdjacencyException, IEMValidationException
from mas.graph.state.graph_state import Channel
from tests.fixtures.iem_testing_tools import (
    PacketFactory, create_test_state_view, create_test_step_context,
    MockIEMNode
)


class MockMiddleware(MessengerMiddleware):
    """Mock middleware for testing."""
    
    def __init__(self, modify_before_send: bool = False, reject_packets: bool = False):
        self.modify_before_send = modify_before_send
        self.reject_packets = reject_packets
        self.before_send_calls = []
        self.after_receive_calls = []
        
    def before_send(self, packet: BaseIEMPacket) -> BaseIEMPacket:
        self.before_send_calls.append(packet)
        
        if self.reject_packets:
            raise IEMValidationException("Middleware rejected packet")
            
        if self.modify_before_send:
            # Modify packet metadata
            packet.payload = {**packet.payload, "middleware_modified": True}
            
        return packet
        
    def after_receive(self, packet: BaseIEMPacket) -> BaseIEMPacket:
        self.after_receive_calls.append(packet)
        
        if self.reject_packets:
            raise IEMValidationException("Middleware rejected packet")
            
        return packet


class TestDefaultInterMessenger:
    """Test suite for DefaultInterMessenger functionality."""
    
    def test_messenger_initialization(self):
        """Test basic messenger initialization."""
        state = create_test_state_view()
        identity = ElementAddress(uid="test_messenger")
        
        messenger = DefaultInterMessenger(state=state, identity=identity)
        
        assert messenger._state == state
        assert messenger._me == identity
        assert messenger._is_adjacent is None  # No adjacency enforcement by default
        assert messenger._middleware == []
        
    def test_messenger_initialization_with_adjacency(self):
        """Test messenger initialization with adjacency enforcement."""
        state = create_test_state_view()
        identity = ElementAddress(uid="test_messenger")
        
        def is_adjacent(uid: str) -> bool:
            return uid in ["node_1", "node_2"]
            
        messenger = DefaultInterMessenger(
            state=state,
            identity=identity,
            is_adjacent=is_adjacent
        )
        
        assert messenger._is_adjacent == is_adjacent
        assert messenger._is_adjacent("node_1") is True
        assert messenger._is_adjacent("node_3") is False
        
    def test_messenger_initialization_with_middleware(self):
        """Test messenger initialization with middleware."""
        state = create_test_state_view()
        identity = ElementAddress(uid="test_messenger")
        middleware = [MockMiddleware(), MockMiddleware()]
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=identity,
            middleware=middleware
        )
        
        assert messenger._middleware == middleware
        assert len(messenger._middleware) == 2
        
    def test_packet_sending_basic(self):
        """Test basic packet sending functionality."""
        state = create_test_state_view()
        identity = ElementAddress(uid="sender")
        messenger = DefaultInterMessenger(state=state, identity=identity)
        
        packet = PacketFactory.create_task_packet(
            src_uid="sender",
            dst_uid="receiver"
        )
        
        packet_id = messenger.send_packet(packet)
        
        assert packet_id == packet.id
        
        # Verify packet was added to state
        packets = state.get(Channel.INTER_PACKETS, [])
        assert len(packets) == 1
        assert packets[0].id == packet.id
        
    def test_packet_sending_with_adjacency_allowed(self):
        """Test packet sending with adjacency enforcement - allowed destination."""
        state = create_test_state_view()
        identity = ElementAddress(uid="sender")
        
        def is_adjacent(uid: str) -> bool:
            return uid == "allowed_receiver"
            
        messenger = DefaultInterMessenger(
            state=state,
            identity=identity,
            is_adjacent=is_adjacent
        )
        
        packet = PacketFactory.create_task_packet(
            src_uid="sender",
            dst_uid="allowed_receiver"
        )
        
        packet_id = messenger.send_packet(packet)
        assert packet_id == packet.id
        
    def test_packet_sending_with_adjacency_blocked(self):
        """Test packet sending with adjacency enforcement - blocked destination."""
        state = create_test_state_view()
        identity = ElementAddress(uid="sender")
        
        def is_adjacent(uid: str) -> bool:
            return uid == "allowed_receiver"
            
        messenger = DefaultInterMessenger(
            state=state,
            identity=identity,
            is_adjacent=is_adjacent
        )
        
        packet = PacketFactory.create_task_packet(
            src_uid="sender",
            dst_uid="blocked_receiver"
        )
        
        with pytest.raises(IEMAdjacencyException):
            messenger.send_packet(packet)
            
    def test_packet_inbox_filtering_basic(self):
        """Test basic packet inbox filtering."""
        state = create_test_state_view()
        identity = ElementAddress(uid="receiver")
        messenger = DefaultInterMessenger(state=state, identity=identity)
        
        # Add packets to state
        packets = [
            PacketFactory.create_task_packet(src_uid="sender_1", dst_uid="receiver"),
            PacketFactory.create_task_packet(src_uid="sender_2", dst_uid="other_receiver"),
            PacketFactory.create_system_packet(src_uid="system", dst_uid="receiver")
        ]
        
        state[Channel.INTER_PACKETS] = packets
        
        # Get inbox
        inbox = messenger.inbox_packets()
        
        # Should only get packets addressed to this messenger
        assert len(inbox) == 2
        received_dst_uids = [p.dst.uid for p in inbox]
        assert all(uid == "receiver" for uid in received_dst_uids)
        
    def test_packet_inbox_filtering_by_type(self):
        """Test packet inbox filtering by packet type."""
        state = create_test_state_view()
        identity = ElementAddress(uid="receiver")
        messenger = DefaultInterMessenger(state=state, identity=identity)
        
        # Add various packet types
        packets = [
            PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver"),
            PacketFactory.create_system_packet(src_uid="sender", dst_uid="receiver"),
            PacketFactory.create_debug_packet(src_uid="sender", dst_uid="receiver")
        ]
        
        state[Channel.INTER_PACKETS] = packets
        
        # Filter by task packets only
        task_inbox = messenger.inbox_packets(PacketType.TASK)
        assert len(task_inbox) == 1
        assert task_inbox[0].type == PacketType.TASK
        
        # Filter by system packets only
        system_inbox = messenger.inbox_packets(PacketType.SYSTEM)
        assert len(system_inbox) == 1
        assert system_inbox[0].type == PacketType.SYSTEM
        
    def test_packet_inbox_excludes_acknowledged(self):
        """Test that inbox excludes already acknowledged packets."""
        state = create_test_state_view()
        identity = ElementAddress(uid="receiver")
        messenger = DefaultInterMessenger(state=state, identity=identity)
        
        # Create packets
        packet1 = PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver")
        packet2 = PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver")
        
        # Acknowledge one packet
        packet1.acknowledge("receiver")
        
        state[Channel.INTER_PACKETS] = [packet1, packet2]
        
        # Inbox should only contain unacknowledged packet
        inbox = messenger.inbox_packets()
        assert len(inbox) == 1
        assert inbox[0].id == packet2.id
        
    def test_packet_inbox_excludes_expired(self):
        """Test that inbox excludes expired packets."""
        state = create_test_state_view()
        identity = ElementAddress(uid="receiver")
        messenger = DefaultInterMessenger(state=state, identity=identity)
        
        # Create packets with different expiration states
        fresh_packet = PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver")
        expired_packet = PacketFactory.create_expired_packet(src_uid="sender", dst_uid="receiver")
        
        state[Channel.INTER_PACKETS] = [fresh_packet, expired_packet]
        
        # Inbox should only contain non-expired packet
        inbox = messenger.inbox_packets()
        assert len(inbox) == 1
        assert inbox[0].id == fresh_packet.id
        
    def test_acknowledgment_handling_success(self):
        """Test successful packet acknowledgment."""
        state = create_test_state_view()
        identity = ElementAddress(uid="receiver")
        messenger = DefaultInterMessenger(state=state, identity=identity)
        
        # Add packet to state
        packet = PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver")
        state[Channel.INTER_PACKETS] = [packet]
        
        # Acknowledge packet
        result = messenger.acknowledge(packet.id)
        
        assert result is True
        
        # Verify packet is marked as acknowledged
        updated_packets = state.get(Channel.INTER_PACKETS, [])
        assert len(updated_packets) == 1
        assert updated_packets[0].is_acknowledged_by("receiver")
        
    def test_acknowledgment_handling_packet_not_found(self):
        """Test acknowledgment when packet is not found."""
        state = create_test_state_view()
        identity = ElementAddress(uid="receiver")
        messenger = DefaultInterMessenger(state=state, identity=identity)
        
        # Try to acknowledge non-existent packet
        result = messenger.acknowledge("non_existent_packet_id")
        
        assert result is False
        
    def test_adjacency_enforcement_enabled(self):
        """Test adjacency enforcement when enabled."""
        state = create_test_state_view()
        identity = ElementAddress(uid="sender")
        
        adjacent_nodes = ["node_1", "node_2"]
        
        def is_adjacent(uid: str) -> bool:
            return uid in adjacent_nodes
            
        messenger = DefaultInterMessenger(
            state=state,
            identity=identity,
            is_adjacent=is_adjacent
        )
        
        # Should allow sending to adjacent nodes
        allowed_packet = PacketFactory.create_task_packet(src_uid="sender", dst_uid="node_1")
        packet_id = messenger.send_packet(allowed_packet)
        assert packet_id == allowed_packet.id
        
        # Should block sending to non-adjacent nodes
        blocked_packet = PacketFactory.create_task_packet(src_uid="sender", dst_uid="node_3")
        with pytest.raises(IEMAdjacencyException):
            messenger.send_packet(blocked_packet)
            
    def test_adjacency_enforcement_disabled(self):
        """Test adjacency enforcement when disabled."""
        state = create_test_state_view()
        identity = ElementAddress(uid="sender")
        
        # No adjacency check function provided
        messenger = DefaultInterMessenger(state=state, identity=identity)
        
        # Should allow sending to any node
        packet = PacketFactory.create_task_packet(src_uid="sender", dst_uid="any_node")
        packet_id = messenger.send_packet(packet)
        assert packet_id == packet.id
        
    def test_packet_purging_acknowledged_only(self):
        """Test packet purging with acknowledged-only mode."""
        state = create_test_state_view()
        identity = ElementAddress(uid="receiver")
        messenger = DefaultInterMessenger(state=state, identity=identity)
        
        # Create packets
        packet1 = PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver")
        packet2 = PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver")
        packet3 = PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver")
        
        # Acknowledge some packets
        packet1.acknowledge("receiver")
        packet2.acknowledge("receiver")
        
        state[Channel.INTER_PACKETS] = [packet1, packet2, packet3]
        
        # Purge acknowledged packets only
        purged_count = messenger.purge(acked_only=True)
        
        assert purged_count == 2
        
        remaining_packets = state.get(Channel.INTER_PACKETS, [])
        assert len(remaining_packets) == 1
        assert remaining_packets[0].id == packet3.id
        
    def test_packet_purging_by_age(self):
        """Test packet purging by age."""
        state = create_test_state_view()
        identity = ElementAddress(uid="receiver")
        messenger = DefaultInterMessenger(state=state, identity=identity)
        
        # Create packets with different ages
        old_packet = PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver")
        old_packet.ts = datetime.now(timezone.utc) - timedelta(hours=2)
        
        recent_packet = PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver")
        
        state[Channel.INTER_PACKETS] = [old_packet, recent_packet]
        
        # Purge packets older than 1 hour
        purged_count = messenger.purge(
            max_age=timedelta(hours=1),
            acked_only=False
        )
        
        assert purged_count == 1
        
        remaining_packets = state.get(Channel.INTER_PACKETS, [])
        assert len(remaining_packets) == 1
        assert remaining_packets[0].id == recent_packet.id
        
    def test_broadcast_functionality(self):
        """Test broadcast packet functionality."""
        state = create_test_state_view()
        context = create_test_step_context(
            uid="broadcaster",
            adjacent_nodes=["node_1", "node_2", "node_3"]
        )
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="broadcaster"),
            context=context
        )
        
        packet = PacketFactory.create_task_packet(src_uid="broadcaster", dst_uid="placeholder")
        
        packet_ids = messenger.broadcast_packet(packet)
        
        # Should have sent to all adjacent nodes
        assert len(packet_ids) == 3
        
        # Verify packets were added to state
        sent_packets = state.get(Channel.INTER_PACKETS, [])
        assert len(sent_packets) == 3
        
        # Verify each packet has correct destination
        destinations = [p.dst.uid for p in sent_packets]
        assert set(destinations) == {"node_1", "node_2", "node_3"}
        
    def test_multicast_functionality(self):
        """Test multicast packet functionality."""
        state = create_test_state_view()
        identity = ElementAddress(uid="multicaster")
        messenger = DefaultInterMessenger(state=state, identity=identity)
        
        packet = PacketFactory.create_task_packet(src_uid="multicaster", dst_uid="placeholder")
        target_uids = ["target_1", "target_2", "target_4"]
        
        packet_ids = messenger.multicast_packet(packet, target_uids)
        
        # Should have sent to specified targets
        assert len(packet_ids) == 3
        
        # Verify packets were sent
        sent_packets = state.get(Channel.INTER_PACKETS, [])
        assert len(sent_packets) == 3
        
        destinations = [p.dst.uid for p in sent_packets]
        assert set(destinations) == set(target_uids)
        
    def test_middleware_application_before_send(self):
        """Test middleware application before sending packets."""
        state = create_test_state_view()
        identity = ElementAddress(uid="sender")
        middleware = MockMiddleware(modify_before_send=True)
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=identity,
            middleware=[middleware]
        )
        
        packet = PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver")
        original_payload = packet.payload.copy()
        
        messenger.send_packet(packet)
        
        # Verify middleware was called
        assert len(middleware.before_send_calls) == 1
        assert middleware.before_send_calls[0].id == packet.id
        
        # Verify packet was modified by middleware
        sent_packets = state.get(Channel.INTER_PACKETS, [])
        assert len(sent_packets) == 1
        assert sent_packets[0].payload["middleware_modified"] is True
        
    def test_middleware_application_after_receive(self):
        """Test middleware application when receiving packets."""
        state = create_test_state_view()
        identity = ElementAddress(uid="receiver")
        middleware = MockMiddleware()
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=identity,
            middleware=[middleware]
        )
        
        # Add packet to state
        packet = PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver")
        state[Channel.INTER_PACKETS] = [packet]
        
        # Get inbox (should trigger after_receive middleware)
        inbox = messenger.inbox_packets()
        
        # Verify middleware was called
        assert len(middleware.after_receive_calls) == 1
        assert middleware.after_receive_calls[0].id == packet.id
        
    def test_middleware_rejection_before_send(self):
        """Test middleware rejecting packets before send."""
        state = create_test_state_view()
        identity = ElementAddress(uid="sender")
        middleware = MockMiddleware(reject_packets=True)
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=identity,
            middleware=[middleware]
        )
        
        packet = PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver")
        
        with pytest.raises(IEMValidationException):
            messenger.send_packet(packet)
            
        # Verify packet was not added to state
        sent_packets = state.get(Channel.INTER_PACKETS, [])
        assert len(sent_packets) == 0
        
    def test_middleware_rejection_after_receive(self):
        """Test middleware rejecting packets after receive."""
        state = create_test_state_view()
        identity = ElementAddress(uid="receiver")
        middleware = MockMiddleware(reject_packets=True)
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=identity,
            middleware=[middleware]
        )
        
        # Add packet to state
        packet = PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver")
        state[Channel.INTER_PACKETS] = [packet]
        
        # Inbox should be empty due to middleware rejection
        inbox = messenger.inbox_packets()
        assert len(inbox) == 0
        
    def test_error_handling_send_failures(self):
        """Test error handling during packet sending."""
        state = create_test_state_view()
        identity = ElementAddress(uid="sender")
        
        # Mock state to raise exception on write
        mock_state = Mock()
        mock_state.get.return_value = []
        mock_state.__setitem__ = Mock(side_effect=Exception("State write failed"))
        
        messenger = DefaultInterMessenger(state=mock_state, identity=identity)
        
        packet = PacketFactory.create_task_packet(src_uid="sender", dst_uid="receiver")
        
        with pytest.raises(IEMValidationException):
            messenger.send_packet(packet)
            
    def test_get_adjacent_nodes_with_context(self):
        """Test getting adjacent nodes from context."""
        context = create_test_step_context(
            uid="test_node",
            adjacent_nodes=["node_1", "node_2", "node_3"]
        )
        
        messenger = DefaultInterMessenger(
            state=create_test_state_view(),
            identity=ElementAddress(uid="test_node"),
            context=context
        )
        
        adjacent_nodes = messenger.get_adjacent_nodes()
        assert set(adjacent_nodes) == {"node_1", "node_2", "node_3"}
        
    def test_get_adjacent_nodes_without_context(self):
        """Test getting adjacent nodes without context."""
        messenger = DefaultInterMessenger(
            state=create_test_state_view(),
            identity=ElementAddress(uid="test_node")
        )
        
        adjacent_nodes = messenger.get_adjacent_nodes()
        assert adjacent_nodes == []
        
    def test_complex_messaging_scenario(self):
        """Test complex messaging scenario with multiple operations."""
        state = create_test_state_view()
        identity = ElementAddress(uid="complex_node")
        context = create_test_step_context(
            uid="complex_node",
            adjacent_nodes=["node_1", "node_2"]
        )
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=identity,
            context=context
        )
        
        # Send multiple packets
        packet1 = PacketFactory.create_task_packet(src_uid="complex_node", dst_uid="node_1")
        packet2 = PacketFactory.create_system_packet(src_uid="complex_node", dst_uid="node_2")
        
        id1 = messenger.send_packet(packet1)
        id2 = messenger.send_packet(packet2)
        
        # Add incoming packets
        incoming1 = PacketFactory.create_task_packet(src_uid="node_1", dst_uid="complex_node")
        incoming2 = PacketFactory.create_task_packet(src_uid="node_2", dst_uid="complex_node")
        
        current_packets = state.get(Channel.INTER_PACKETS, [])
        current_packets.extend([incoming1, incoming2])
        state[Channel.INTER_PACKETS] = current_packets
        
        # Process inbox
        inbox = messenger.inbox_packets()
        assert len(inbox) == 2
        
        # Acknowledge packets
        for packet in inbox:
            result = messenger.acknowledge(packet.id)
            assert result is True
            
        # Verify acknowledgments
        final_inbox = messenger.inbox_packets()
        assert len(final_inbox) == 0  # All packets acknowledged
        
        # Purge acknowledged packets
        purged_count = messenger.purge(acked_only=True)
        assert purged_count == 2
