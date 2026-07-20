"""
Unit tests for packet lifecycle management.

Tests the complete lifecycle of IEM packets from creation to delivery,
acknowledgment, expiration, and cleanup. Covers packet state transitions
and lifecycle edge cases.
"""

import pytest
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, Mock
from typing import List

from mas.core.iem.packets import BaseIEMPacket, TaskPacket
from mas.core.iem.models import ElementAddress, PacketType
from mas.core.iem.messenger import DefaultInterMessenger
from mas.graph.state.graph_state import Channel
from tests.fixtures.iem_testing_tools import (
    PacketFactory, create_test_state_view, MockIEMNode,
    IEMPerformanceMonitor
)


class TestPacketLifecycle:
    """Test suite for complete packet lifecycle scenarios."""
    
    def test_packet_creation_to_delivery_basic(self):
        """Test basic packet lifecycle from creation to delivery."""
        # Setup
        state = create_test_state_view()
        sender = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="sender")
        )
        receiver = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="receiver")
        )
        
        # 1. Create packet
        packet = PacketFactory.create_task_packet(
            src_uid="sender",
            dst_uid="receiver",
            task_content="Lifecycle test task"
        )
        
        # Verify initial state
        assert packet.ack_by == set()
        assert not packet.is_expired
        
        # 2. Send packet
        packet_id = sender.send_packet(packet)
        assert packet_id == packet.id
        
        # 3. Receiver checks inbox
        inbox = receiver.inbox_packets()
        assert len(inbox) == 1
        assert inbox[0].id == packet.id
        
        # 4. Receiver acknowledges packet
        ack_result = receiver.acknowledge(packet.id)
        assert ack_result is True
        
        # 5. Verify acknowledgment
        final_inbox = receiver.inbox_packets()
        assert len(final_inbox) == 0  # Packet no longer in inbox
        
        # 6. Check packet state
        packets = state.get(Channel.INTER_PACKETS, [])
        assert len(packets) == 1
        assert packets[0].is_acknowledged_by("receiver")
        
    def test_packet_creation_to_delivery_with_ttl(self):
        """Test packet lifecycle with TTL expiration."""
        state = create_test_state_view()
        sender = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="sender")
        )
        receiver = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="receiver")
        )
        
        # Create packet with short TTL
        packet = PacketFactory.create_task_packet(
            src_uid="sender",
            dst_uid="receiver"
        )
        packet.ttl = timedelta(milliseconds=100)  # Very short TTL
        
        # Send packet
        sender.send_packet(packet)
        
        # Wait for expiration
        time.sleep(0.2)  # 200ms > 100ms TTL
        
        # Packet should be expired and not in inbox
        inbox = receiver.inbox_packets()
        assert len(inbox) == 0
        
    def test_packet_acknowledgment_lifecycle(self):
        """Test packet acknowledgment lifecycle with multiple receivers."""
        state = create_test_state_view()
        sender = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="sender")
        )
        
        receivers = [
            DefaultInterMessenger(state=state, identity=ElementAddress(uid=f"receiver_{i}"))
            for i in range(3)
        ]
        
        # Create and send packet to multiple receivers via multicast
        packet = PacketFactory.create_task_packet(src_uid="sender", dst_uid="placeholder")
        target_uids = [f"receiver_{i}" for i in range(3)]
        
        packet_ids = sender.multicast_packet(packet, target_uids)
        assert len(packet_ids) == 3
        
        # Each receiver should see their packet
        for i, receiver in enumerate(receivers):
            inbox = receiver.inbox_packets()
            assert len(inbox) == 1
            assert inbox[0].dst.uid == f"receiver_{i}"
            
        # Acknowledge from each receiver
        for i, receiver in enumerate(receivers):
            inbox = receiver.inbox_packets()
            packet_to_ack = inbox[0]
            result = receiver.acknowledge(packet_to_ack.id)
            assert result is True
            
        # Verify all packets are acknowledged
        all_packets = state.get(Channel.INTER_PACKETS, [])
        for packet in all_packets:
            # Each packet should be acknowledged by its specific receiver
            receiver_uid = packet.dst.uid
            assert packet.is_acknowledged_by(receiver_uid)
            
    def test_packet_expiration_handling(self):
        """Test various packet expiration scenarios."""
        state = create_test_state_view()
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="test_node")
        )
        
        now = datetime.now(timezone.utc)

        # Create packets with different expiration states
        packets = [
            # Already expired
            PacketFactory.create_expired_packet(
                src_uid="sender",
                dst_uid="test_node",
                expired_seconds_ago=60
            ),
            # Expiring soon
            PacketFactory.create_task_packet(src_uid="sender", dst_uid="test_node"),
            # No TTL (never expires)
            PacketFactory.create_task_packet(src_uid="sender", dst_uid="test_node")
        ]
        
        # Set specific TTLs
        packets[1].ttl = timedelta(seconds=1)
        packets[1].ts = now
        packets[2].ttl = None  # Never expires
        
        # Add to state
        state[Channel.INTER_PACKETS] = packets
        
        # Initially, only non-expired packets in inbox
        inbox = messenger.inbox_packets()
        assert len(inbox) == 2  # Expired packet excluded
        
        # Wait for second packet to expire
        time.sleep(1.5)
        
        # Now only the never-expiring packet should be in inbox
        inbox = messenger.inbox_packets()
        assert len(inbox) == 1
        assert inbox[0].ttl is None
        
    def test_packet_purging_strategies(self):
        """Test different packet purging strategies."""
        state = create_test_state_view()
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="purger"),
            max_packet_age=timedelta(hours=1)
        )
        
        now = datetime.now(timezone.utc)

        # Create packets with different states
        packets = []
        
        # Old acknowledged packet
        old_acked = PacketFactory.create_task_packet(src_uid="sender", dst_uid="purger")
        old_acked.ts = now - timedelta(hours=2)
        old_acked.acknowledge("purger")
        packets.append(old_acked)
        
        # Recent acknowledged packet
        recent_acked = PacketFactory.create_task_packet(src_uid="sender", dst_uid="purger")
        recent_acked.acknowledge("purger")
        packets.append(recent_acked)
        
        # Old unacknowledged packet
        old_unacked = PacketFactory.create_task_packet(src_uid="sender", dst_uid="purger")
        old_unacked.ts = now - timedelta(hours=2)
        packets.append(old_unacked)
        
        # Recent unacknowledged packet
        recent_unacked = PacketFactory.create_task_packet(src_uid="sender", dst_uid="purger")
        packets.append(recent_unacked)
        
        state[Channel.INTER_PACKETS] = packets
        
        # Test purging acknowledged only
        purged_count = messenger.purge(acked_only=True)
        assert purged_count == 2  # Both acknowledged packets
        
        remaining = state.get(Channel.INTER_PACKETS, [])
        assert len(remaining) == 2  # Both unacknowledged packets remain
        
        # Reset state
        state[Channel.INTER_PACKETS] = packets
        
        # Test purging by age (regardless of acknowledgment)
        purged_count = messenger.purge(
            max_age=timedelta(hours=1),
            acked_only=False
        )
        assert purged_count == 2  # Both old packets
        
        remaining = state.get(Channel.INTER_PACKETS, [])
        assert len(remaining) == 2  # Both recent packets remain
        
    def test_duplicate_packet_handling(self):
        """Test handling of duplicate packets."""
        state = create_test_state_view()
        sender = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="sender")
        )
        receiver = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="receiver")
        )
        
        # Create identical packets (same content, different IDs)
        packet1 = PacketFactory.create_task_packet(
            src_uid="sender",
            dst_uid="receiver",
            task_content="Duplicate test"
        )
        packet2 = PacketFactory.create_task_packet(
            src_uid="sender", 
            dst_uid="receiver",
            task_content="Duplicate test"
        )
        
        # Ensure different IDs
        assert packet1.id != packet2.id
        
        # Send both packets
        sender.send_packet(packet1)
        sender.send_packet(packet2)
        
        # Receiver should see both packets (IEM doesn't deduplicate by content)
        inbox = receiver.inbox_packets()
        assert len(inbox) == 2
        
        # Acknowledge both separately
        for packet in inbox:
            receiver.acknowledge(packet.id)
            
        # Both should be acknowledged
        final_inbox = receiver.inbox_packets()
        assert len(final_inbox) == 0
        
    def test_packet_ordering_preservation(self):
        """Test that packet ordering is preserved through lifecycle."""
        state = create_test_state_view()
        sender = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="sender")
        )
        receiver = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="receiver")
        )
        
        # Send packets in specific order
        packet_contents = ["First", "Second", "Third", "Fourth"]
        sent_packets = []
        
        for content in packet_contents:
            packet = PacketFactory.create_task_packet(
                src_uid="sender",
                dst_uid="receiver",
                task_content=content
            )
            sender.send_packet(packet)
            sent_packets.append(packet)
            
        # Receiver gets packets in order
        inbox = receiver.inbox_packets()
        assert len(inbox) == 4
        
        # Verify order is preserved
        for i, packet in enumerate(inbox):
            expected_content = packet_contents[i]
            actual_content = packet.extract_task().content
            assert actual_content == expected_content
            
    def test_lifecycle_with_performance_monitoring(self):
        """Test packet lifecycle with performance monitoring."""
        state = create_test_state_view()
        monitor = IEMPerformanceMonitor()
        
        sender = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="sender")
        )
        receiver = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="receiver")
        )
        
        # Monitor send operation
        with monitor.monitor_operation("packet_send") as op_id:
            packet = PacketFactory.create_task_packet(
                src_uid="sender",
                dst_uid="receiver"
            )
            packet_id = sender.send_packet(packet)
            
        # Monitor receive operation
        with monitor.monitor_operation("packet_receive") as op_id:
            inbox = receiver.inbox_packets()
            
        # Monitor acknowledgment operation
        with monitor.monitor_operation("packet_acknowledge") as op_id:
            receiver.acknowledge(packet_id)
            
        # Verify performance metrics
        send_stats = monitor.get_operation_stats("packet_send")
        receive_stats = monitor.get_operation_stats("packet_receive")
        ack_stats = monitor.get_operation_stats("packet_acknowledge")
        
        # Check that operations were recorded (using correct field names from first implementation)
        assert send_stats["success_count"] == 1
        assert receive_stats["success_count"] == 1
        assert ack_stats["success_count"] == 1
        
        # Verify duration tracking
        assert send_stats["avg_duration_ms"] >= 0
        assert receive_stats["avg_duration_ms"] >= 0
        assert ack_stats["avg_duration_ms"] >= 0
        
        overall_stats = monitor.get_overall_stats()
        assert overall_stats["total_operations"] == 3
        assert overall_stats["overall_success_rate"] == 1.0
        
    def test_lifecycle_error_recovery(self):
        """Test packet lifecycle with error scenarios and recovery."""
        state = create_test_state_view()
        
        # Create messenger with mocked state that fails occasionally
        mock_state = Mock()
        mock_state.get.side_effect = [
            [],  # First call succeeds
            Exception("State read failed"),  # Second call fails
            [PacketFactory.create_task_packet("sender", "test_node")]  # Third call succeeds - correct destination
        ]
        mock_state.__setitem__ = Mock()
        
        messenger = DefaultInterMessenger(
            state=mock_state,
            identity=ElementAddress(uid="test_node")
        )
        
        # First operation should succeed
        packets = messenger.inbox_packets()
        assert packets == []
        
        # Second operation should raise the mocked exception
        with pytest.raises(Exception, match="State read failed"):
            messenger.inbox_packets()
            
        # System should recover for subsequent operations
        inbox = messenger.inbox_packets()
        assert isinstance(inbox, list)
        assert len(inbox) == 1  # Should get the mocked packet addressed to test_node
        
    def test_complex_lifecycle_scenario(self):
        """Test complex lifecycle scenario with multiple nodes and operations."""
        state = create_test_state_view()
        
        # Create multiple nodes
        nodes = {
            "orchestrator": DefaultInterMessenger(
                state=state,
                identity=ElementAddress(uid="orchestrator")
            ),
            "worker_1": DefaultInterMessenger(
                state=state,
                identity=ElementAddress(uid="worker_1")
            ),
            "worker_2": DefaultInterMessenger(
                state=state,
                identity=ElementAddress(uid="worker_2")
            ),
            "collector": DefaultInterMessenger(
                state=state,
                identity=ElementAddress(uid="collector")
            )
        }
        
        # Scenario: Orchestrator distributes work, workers process and send to collector
        
        # 1. Orchestrator sends tasks to workers
        work_packets = []
        for i, worker_uid in enumerate(["worker_1", "worker_2"]):
            packet = PacketFactory.create_task_packet(
                src_uid="orchestrator",
                dst_uid=worker_uid,
                task_content=f"Process chunk {i+1}"
            )
            nodes["orchestrator"].send_packet(packet)
            work_packets.append(packet)
            
        # 2. Workers receive and acknowledge work
        for worker_uid in ["worker_1", "worker_2"]:
            worker = nodes[worker_uid]
            inbox = worker.inbox_packets()
            assert len(inbox) == 1
            
            work_packet = inbox[0]
            worker.acknowledge(work_packet.id)
            
            # Worker sends results to collector
            result_packet = PacketFactory.create_task_packet(
                src_uid=worker_uid,
                dst_uid="collector",
                task_content=f"Result from {worker_uid}"
            )
            worker.send_packet(result_packet)
            
        # 3. Collector receives results
        collector = nodes["collector"]
        inbox = collector.inbox_packets()
        assert len(inbox) == 2
        
        # Verify results from both workers
        results = [packet.extract_task().content for packet in inbox]
        assert "Result from worker_1" in results
        assert "Result from worker_2" in results
        
        # 4. Collector acknowledges all results
        for packet in inbox:
            collector.acknowledge(packet.id)
            
        # 5. Final state verification
        final_inbox = collector.inbox_packets()
        assert len(final_inbox) == 0
        
        # All packets should be acknowledged by their respective receivers
        all_packets = state.get(Channel.INTER_PACKETS, [])
        for packet in all_packets:
            assert packet.is_acknowledged_by(packet.dst.uid)
            
        # 6. Cleanup old acknowledged packets
        total_purged = 0
        for node in nodes.values():
            purged = node.purge(acked_only=True)
            total_purged += purged
            
        assert total_purged == 4  # 2 work packets + 2 result packets
