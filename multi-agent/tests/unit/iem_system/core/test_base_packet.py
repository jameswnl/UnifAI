"""
Unit tests for BaseIEMPacket - Core IEM protocol packet testing.

Tests the fundamental packet structure, lifecycle, and validation.
Covers packet creation, expiration, acknowledgment tracking, and serialization.
"""

import pytest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from mas.core.iem.packets import BaseIEMPacket, TaskPacket
from mas.core.iem.models import ElementAddress, PacketType
from tests.fixtures.iem_testing_tools import PacketFactory


class TestBaseIEMPacket:
    """Test suite for BaseIEMPacket core functionality."""
    
    def test_packet_creation_with_defaults(self):
        """Test packet creation with default values."""
        src = ElementAddress(uid="test_src")
        dst = ElementAddress(uid="test_dst")
        
        # Create a concrete subclass since BaseIEMPacket is abstract
        packet = TaskPacket(
            src=src,
            dst=dst,
            payload={"test": "data"}
        )
        
        # Verify default values
        assert packet.protocol == "iem/2.0"
        assert packet.type == PacketType.TASK
        assert packet.src == src
        assert packet.dst == dst
        assert isinstance(packet.id, str)
        assert len(packet.id) > 0
        assert isinstance(packet.ts, datetime)
        assert packet.ttl is None
        assert packet.ack_by == set()
        
    def test_packet_id_uniqueness(self):
        """Test that packet IDs are unique across multiple packets."""
        src = ElementAddress(uid="test_src")
        dst = ElementAddress(uid="test_dst")
        
        packets = []
        for _ in range(100):
            packet = TaskPacket(
                src=src,
                dst=dst,
                payload={"test": "data"}
            )
            packets.append(packet)
            
        # Verify all IDs are unique
        packet_ids = [p.id for p in packets]
        assert len(packet_ids) == len(set(packet_ids))
        
    def test_packet_expiration_logic_not_expired(self):
        """Test packet expiration logic for non-expired packets."""
        packet = PacketFactory.create_task_packet()
        
        # Packet without TTL should never expire
        assert not packet.is_expired
        
        # Packet with future TTL should not be expired
        packet.ttl = timedelta(hours=1)
        assert not packet.is_expired
        
    def test_packet_expiration_logic_expired(self):
        """Test packet expiration logic for expired packets."""
        packet = PacketFactory.create_task_packet()
        
        # Set TTL that has already passed
        packet.ttl = timedelta(seconds=1)
        packet.ts = datetime.now(timezone.utc) - timedelta(seconds=2)
        
        assert packet.is_expired
        
    def test_packet_expiration_edge_cases(self):
        """Test packet expiration edge cases."""
        packet = PacketFactory.create_task_packet()
        
        # Zero TTL should be expired
        packet.ttl = timedelta(seconds=0)
        assert packet.is_expired
        
        # Negative TTL should be expired
        packet.ttl = timedelta(seconds=-1)
        assert packet.is_expired
        
    def test_packet_acknowledgment_tracking(self):
        """Test packet acknowledgment tracking functionality."""
        packet = PacketFactory.create_task_packet()
        
        # Initially no acknowledgments
        assert packet.ack_by == set()
        assert not packet.is_acknowledged_by("node1")
        assert not packet.is_acknowledged_by("node2")
        
        # Acknowledge by one node
        packet.acknowledge("node1")
        assert packet.is_acknowledged_by("node1")
        assert not packet.is_acknowledged_by("node2")
        assert "node1" in packet.ack_by
        
        # Acknowledge by another node
        packet.acknowledge("node2")
        assert packet.is_acknowledged_by("node1")
        assert packet.is_acknowledged_by("node2")
        assert "node1" in packet.ack_by
        assert "node2" in packet.ack_by
        
    def test_packet_double_acknowledgment(self):
        """Test that double acknowledgment from same node is handled correctly."""
        packet = PacketFactory.create_task_packet()
        
        # Acknowledge twice from same node
        packet.acknowledge("node1")
        packet.acknowledge("node1")
        
        # Should only be in set once
        assert len(packet.ack_by) == 1
        assert "node1" in packet.ack_by
        
    def test_packet_serialization_deserialization(self):
        """Test packet serialization and deserialization."""
        original_packet = PacketFactory.create_task_packet(
            src_uid="src_node",
            dst_uid="dst_node",
            task_content="Test task content"
        )
        
        # Serialize to dict
        packet_dict = original_packet.model_dump()
        
        # Verify essential fields are present
        assert packet_dict["id"] == original_packet.id
        assert packet_dict["protocol"] == "iem/2.0"
        assert packet_dict["type"] == PacketType.TASK
        assert packet_dict["src"]["uid"] == "src_node"
        assert packet_dict["dst"]["uid"] == "dst_node"
        
        # Deserialize back to packet
        reconstructed_packet = TaskPacket.model_validate(packet_dict)
        
        # Verify reconstruction
        assert reconstructed_packet.id == original_packet.id
        assert reconstructed_packet.protocol == original_packet.protocol
        assert reconstructed_packet.type == original_packet.type
        assert reconstructed_packet.src == original_packet.src
        assert reconstructed_packet.dst == original_packet.dst
        
    def test_packet_ttl_handling(self):
        """Test packet TTL (Time To Live) handling."""
        packet = PacketFactory.create_task_packet()
        
        # Test various TTL values
        ttl_values = [
            timedelta(seconds=1),
            timedelta(minutes=5),
            timedelta(hours=1),
            timedelta(days=1)
        ]
        
        for ttl in ttl_values:
            packet.ttl = ttl
            # Packet should not be expired immediately after setting TTL
            assert not packet.is_expired
            
    def test_packet_validation_with_invalid_data(self):
        """Test packet validation with invalid data."""
        with pytest.raises(Exception):
            # Invalid source address
            TaskPacket(
                src="invalid_address",  # Should be ElementAddress
                dst=ElementAddress(uid="test_dst"),
                payload={"test": "data"}
            )
            
        with pytest.raises(Exception):
            # Invalid destination address  
            TaskPacket(
                src=ElementAddress(uid="test_src"),
                dst="invalid_address",  # Should be ElementAddress
                payload={"test": "data"}
            )
            
    def test_packet_with_custom_timestamp(self):
        """Test packet creation with custom timestamp."""
        custom_time = datetime.now(timezone.utc) - timedelta(hours=1)
        
        packet = TaskPacket(
            src=ElementAddress(uid="test_src"),
            dst=ElementAddress(uid="test_dst"),
            payload={"test": "data"},
            ts=custom_time
        )
        
        assert packet.ts == custom_time
        
    def test_packet_acknowledgment_by_multiple_nodes(self):
        """Test packet acknowledgment by multiple nodes in various scenarios."""
        packet = PacketFactory.create_task_packet()
        
        # Test acknowledgment by multiple nodes
        nodes = ["node1", "node2", "node3", "node4", "node5"]
        
        for i, node in enumerate(nodes):
            packet.acknowledge(node)
            assert packet.is_acknowledged_by(node)
            assert len(packet.ack_by) == i + 1
            
        # Verify all nodes are in acknowledgment set
        for node in nodes:
            assert packet.is_acknowledged_by(node)
            
    def test_packet_with_very_long_uid(self):
        """Test packet with very long node UIDs."""
        long_uid = "very_long_node_uid_" + "x" * 1000
        
        packet = PacketFactory.create_task_packet(
            src_uid=long_uid,
            dst_uid=long_uid + "_dst"
        )
        
        assert packet.src.uid == long_uid
        assert packet.dst.uid == long_uid + "_dst"
        
    def test_packet_with_special_characters_in_uid(self):
        """Test packet with special characters in node UIDs."""
        special_chars_uid = "node-123_test.domain@example.com"
        
        packet = PacketFactory.create_task_packet(
            src_uid=special_chars_uid,
            dst_uid=special_chars_uid + "_dst"
        )
        
        assert packet.src.uid == special_chars_uid
        assert packet.dst.uid == special_chars_uid + "_dst"
        
    def test_packet_expiration_with_timezone_issues(self):
        """Test packet expiration handling with potential timezone issues."""
        packet = PacketFactory.create_task_packet()
        
        # Set packet timestamp to various times
        now = datetime.now(timezone.utc)
        packet.ts = now
        packet.ttl = timedelta(seconds=5)

        # Should not be expired immediately
        assert not packet.is_expired

        # Mock time progression
        with patch('mas.core.iem.packets.datetime') as mock_datetime:
            # Mock current time to be 10 seconds in the future
            mock_datetime.now.return_value = now + timedelta(seconds=10)

            # Now packet should be expired
            assert packet.is_expired
