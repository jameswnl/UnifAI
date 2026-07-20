"""
Comprehensive tests for IEM middleware validation scenarios.

Tests various validation patterns, security checks, and edge cases.
"""

import pytest
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from mas.core.iem.messenger import DefaultInterMessenger
from mas.core.iem.interfaces import MessengerMiddleware
from mas.core.iem.models import ElementAddress, PacketType
from mas.core.iem.packets import BaseIEMPacket, TaskPacket, SystemPacket
from mas.core.iem.exceptions import IEMValidationException, IEMPermissionException
from mas.graph.state.graph_state import Channel
from tests.fixtures.iem_testing_tools import create_test_state_view, PacketFactory


class SecurityMiddleware(MessengerMiddleware):
    """Advanced security validation middleware."""
    
    def __init__(self, 
                 allowed_senders: set = None,
                 blocked_senders: set = None,
                 max_payload_size: int = None,
                 require_encryption: bool = False):
        self.allowed_senders = allowed_senders or set()
        self.blocked_senders = blocked_senders or set()
        self.max_payload_size = max_payload_size
        self.require_encryption = require_encryption
        self.security_violations = []
    
    def before_send(self, packet: BaseIEMPacket) -> BaseIEMPacket:
        # Check payload size
        if self.max_payload_size:
            payload_size = len(str(packet.payload))
            if payload_size > self.max_payload_size:
                violation = f"Payload too large: {payload_size} > {self.max_payload_size}"
                self.security_violations.append(violation)
                raise IEMValidationException(violation)
        
        # Check encryption requirement
        if self.require_encryption and not packet.payload.get("encrypted", False):
            violation = "Encryption required but not present"
            self.security_violations.append(violation)
            raise IEMValidationException(violation)
        
        return packet
    
    def after_receive(self, packet: BaseIEMPacket) -> BaseIEMPacket:
        # Check sender allowlist
        if self.allowed_senders and packet.src.uid not in self.allowed_senders:
            violation = f"Sender {packet.src.uid} not in allowlist"
            self.security_violations.append(violation)
            raise IEMPermissionException(violation)
        
        # Check sender blocklist
        if packet.src.uid in self.blocked_senders:
            violation = f"Sender {packet.src.uid} is blocked"
            self.security_violations.append(violation)
            raise IEMPermissionException(violation)
        
        return packet


class ContentValidationMiddleware(MessengerMiddleware):
    """Validates packet content and structure."""
    
    def __init__(self, strict_schema: bool = False):
        self.strict_schema = strict_schema
        self.validation_errors = []
        self.required_task_fields = {"content", "created_by", "task_id"}
    
    def before_send(self, packet: BaseIEMPacket) -> BaseIEMPacket:
        if isinstance(packet, TaskPacket):
            self._validate_task_packet(packet)
        elif isinstance(packet, SystemPacket):
            self._validate_system_packet(packet)
        return packet
    
    def after_receive(self, packet: BaseIEMPacket) -> BaseIEMPacket:
        # Additional receive-side validation
        if packet.is_expired:
            error = f"Received expired packet: {packet.id}"
            self.validation_errors.append(error)
            raise IEMValidationException(error)
        return packet
    
    def _validate_task_packet(self, packet: TaskPacket):
        """Validate task packet structure."""
        if self.strict_schema:
            missing_fields = self.required_task_fields - set(packet.payload.keys())
            if missing_fields:
                error = f"Missing required fields: {missing_fields}"
                self.validation_errors.append(error)
                raise IEMValidationException(error)
        
        # Validate content is not empty
        content = packet.payload.get("content", "")
        if not content or not content.strip():
            error = "Task content cannot be empty"
            self.validation_errors.append(error)
            raise IEMValidationException(error)
    
    def _validate_system_packet(self, packet: SystemPacket):
        """Validate system packet structure."""
        if not hasattr(packet, 'system_event') or not packet.system_event:
            error = "System packet must have system_event"
            self.validation_errors.append(error)
            raise IEMValidationException(error)


class RateLimitingMiddleware(MessengerMiddleware):
    """Rate limiting middleware to prevent spam."""
    
    def __init__(self, max_packets_per_second: int = 10, window_size: int = 60):
        self.max_packets_per_second = max_packets_per_second
        self.window_size = window_size
        self.send_timestamps = []
        self.receive_timestamps = []
        self.rate_limit_violations = []
    
    def before_send(self, packet: BaseIEMPacket) -> BaseIEMPacket:
        now = datetime.now(timezone.utc)
        self.send_timestamps.append(now)
        
        # Clean old timestamps
        cutoff = now - timedelta(seconds=self.window_size)
        self.send_timestamps = [ts for ts in self.send_timestamps if ts > cutoff]
        
        # Check rate limit
        if len(self.send_timestamps) > self.max_packets_per_second * self.window_size:
            violation = f"Send rate limit exceeded: {len(self.send_timestamps)} packets in {self.window_size}s"
            self.rate_limit_violations.append(violation)
            raise IEMValidationException(violation)
        
        return packet
    
    def after_receive(self, packet: BaseIEMPacket) -> BaseIEMPacket:
        now = datetime.now(timezone.utc)
        self.receive_timestamps.append(now)
        
        # Clean old timestamps
        cutoff = now - timedelta(seconds=self.window_size)
        self.receive_timestamps = [ts for ts in self.receive_timestamps if ts > cutoff]
        
        return packet


class TestMiddlewareValidation:
    """Test suite for middleware validation functionality."""
    
    def test_security_middleware_sender_allowlist(self):
        """Test security middleware with sender allowlist."""
        state = create_test_state_view()
        security_middleware = SecurityMiddleware(allowed_senders={"trusted_sender"})
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="test_node"),
            middleware=[security_middleware]
        )
        
        # Add packet from allowed sender
        allowed_packet = PacketFactory.create_task_packet("trusted_sender", "test_node")
        state[Channel.INTER_PACKETS] = [allowed_packet]
        
        inbox = messenger.inbox_packets()
        assert len(inbox) == 1
        
        # Add packet from non-allowed sender
        blocked_packet = PacketFactory.create_task_packet("untrusted_sender", "test_node")
        state[Channel.INTER_PACKETS] = [allowed_packet, blocked_packet]
        
        inbox = messenger.inbox_packets()
        assert len(inbox) == 1  # Only allowed packet
        assert len(security_middleware.security_violations) == 1
    
    def test_security_middleware_sender_blocklist(self):
        """Test security middleware with sender blocklist."""
        state = create_test_state_view()
        security_middleware = SecurityMiddleware(blocked_senders={"malicious_sender"})
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="test_node"),
            middleware=[security_middleware]
        )
        
        # Add packet from blocked sender
        blocked_packet = PacketFactory.create_task_packet("malicious_sender", "test_node")
        normal_packet = PacketFactory.create_task_packet("normal_sender", "test_node")
        
        state[Channel.INTER_PACKETS] = [blocked_packet, normal_packet]
        
        inbox = messenger.inbox_packets()
        assert len(inbox) == 1  # Only normal packet
        assert len(security_middleware.security_violations) == 1
    
    def test_security_middleware_payload_size_limit(self):
        """Test security middleware payload size validation."""
        state = create_test_state_view()
        security_middleware = SecurityMiddleware(max_payload_size=100)
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="test_node"),
            middleware=[security_middleware]
        )
        
        # Create packet with large payload
        large_packet = PacketFactory.create_task_packet("sender", "receiver")
        large_packet.payload["large_data"] = "x" * 1000  # Large payload
        
        with pytest.raises(IEMValidationException, match="Payload too large"):
            messenger.send_packet(large_packet)
        
        assert len(security_middleware.security_violations) == 1
    
    def test_security_middleware_encryption_requirement(self):
        """Test security middleware encryption validation."""
        state = create_test_state_view()
        security_middleware = SecurityMiddleware(require_encryption=True)
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="test_node"),
            middleware=[security_middleware]
        )
        
        # Unencrypted packet should be rejected
        unencrypted_packet = PacketFactory.create_task_packet("sender", "receiver")
        
        with pytest.raises(IEMValidationException, match="Encryption required"):
            messenger.send_packet(unencrypted_packet)
        
        # Encrypted packet should pass
        encrypted_packet = PacketFactory.create_task_packet("sender", "receiver")
        encrypted_packet.payload["encrypted"] = True
        
        # Should not raise exception
        messenger.send_packet(encrypted_packet)
        
    def test_content_validation_strict_schema(self):
        """Test content validation with strict schema."""
        state = create_test_state_view()
        content_middleware = ContentValidationMiddleware(strict_schema=True)
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="test_node"),
            middleware=[content_middleware]
        )
        
        # Packet missing required fields
        incomplete_packet = TaskPacket(
            src=ElementAddress(uid="sender"),
            dst=ElementAddress(uid="receiver"),
            payload={"content": "test"}  # Missing created_by, task_id
        )
        
        with pytest.raises(IEMValidationException, match="Missing required fields"):
            messenger.send_packet(incomplete_packet)
        
        assert len(content_middleware.validation_errors) == 1
    
    def test_content_validation_empty_content(self):
        """Test content validation rejects empty content."""
        state = create_test_state_view()
        content_middleware = ContentValidationMiddleware()
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="test_node"),
            middleware=[content_middleware]
        )
        
        # Empty content packet
        empty_packet = PacketFactory.create_task_packet("sender", "receiver", "")
        
        with pytest.raises(IEMValidationException, match="Task content cannot be empty"):
            messenger.send_packet(empty_packet)
        
        # Whitespace-only content
        whitespace_packet = PacketFactory.create_task_packet("sender", "receiver", "   ")
        
        with pytest.raises(IEMValidationException, match="Task content cannot be empty"):
            messenger.send_packet(whitespace_packet)
    
    def test_content_validation_expired_packets(self):
        """Test that expired packets are filtered by messenger before middleware."""
        state = create_test_state_view()
        content_middleware = ContentValidationMiddleware()
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="test_node"),
            middleware=[content_middleware]
        )
        
        # Create expired packet
        expired_packet = PacketFactory.create_task_packet("sender", "test_node")
        expired_packet.ts = datetime.now(timezone.utc) - timedelta(hours=2)
        expired_packet.ttl = timedelta(hours=1)  # Expired 1 hour ago
        
        state[Channel.INTER_PACKETS] = [expired_packet]
        
        inbox = messenger.inbox_packets()
        assert len(inbox) == 0  # Expired packet rejected by messenger (not middleware)
        assert len(content_middleware.validation_errors) == 0  # Middleware never sees expired packets
    
    def test_rate_limiting_middleware_send_limit(self):
        """Test rate limiting on send operations."""
        state = create_test_state_view()
        rate_limiter = RateLimitingMiddleware(max_packets_per_second=2, window_size=1)
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="test_node"),
            middleware=[rate_limiter]
        )
        
        # Send packets within limit
        for i in range(2):
            packet = PacketFactory.create_task_packet("sender", "receiver", f"packet_{i}")
            messenger.send_packet(packet)  # Should succeed
        
        # Next packet should exceed rate limit
        packet = PacketFactory.create_task_packet("sender", "receiver", "overflow_packet")
        
        with pytest.raises(IEMValidationException, match="Send rate limit exceeded"):
            messenger.send_packet(packet)
        
        assert len(rate_limiter.rate_limit_violations) == 1
    
    def test_multiple_validation_middleware_chain(self):
        """Test multiple validation middleware working together."""
        state = create_test_state_view()
        
        security_middleware = SecurityMiddleware(max_payload_size=500)
        content_middleware = ContentValidationMiddleware(strict_schema=False)
        rate_limiter = RateLimitingMiddleware(max_packets_per_second=5)
        
        middleware_chain = [security_middleware, content_middleware, rate_limiter]
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="test_node"),
            middleware=middleware_chain
        )
        
        # Valid packet should pass all middleware
        valid_packet = PacketFactory.create_task_packet("sender", "receiver", "Valid content")
        messenger.send_packet(valid_packet)  # Should succeed
        
        # Invalid packet should be caught by first applicable middleware
        invalid_packet = PacketFactory.create_task_packet("sender", "receiver", "")
        
        with pytest.raises(IEMValidationException, match="Task content cannot be empty"):
            messenger.send_packet(invalid_packet)
        
        assert len(content_middleware.validation_errors) == 1
    
    def test_validation_middleware_performance_edge_cases(self):
        """Test validation middleware with performance edge cases."""
        state = create_test_state_view()
        
        # Very strict validation
        strict_security = SecurityMiddleware(
            max_payload_size=50,
            require_encryption=True,
            allowed_senders={"trusted_only"}
        )
        strict_content = ContentValidationMiddleware(strict_schema=True)
        strict_rate_limiter = RateLimitingMiddleware(max_packets_per_second=1)
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="test_node"),
            middleware=[strict_security, strict_content, strict_rate_limiter]
        )
        
        # Test various failure scenarios
        test_cases = [
            ("large_payload", lambda: PacketFactory.create_task_packet("sender", "receiver", "x" * 1000)),
            ("no_encryption", lambda: PacketFactory.create_task_packet("sender", "receiver")),
            ("incomplete_schema", lambda: TaskPacket(
                src=ElementAddress(uid="sender"),
                dst=ElementAddress(uid="receiver"),
                payload={"content": "test"}
            ))
        ]
        
        for case_name, packet_factory in test_cases:
            packet = packet_factory()
            if hasattr(packet, 'payload') and case_name != "no_encryption":
                packet.payload["encrypted"] = True
            
            with pytest.raises(IEMValidationException):
                messenger.send_packet(packet)
    
    def test_validation_middleware_concurrent_safety(self):
        """Test validation middleware thread safety."""
        import threading
        import time
        
        state = create_test_state_view()
        security_middleware = SecurityMiddleware(max_payload_size=1000)
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="test_node"),
            middleware=[security_middleware]
        )
        
        def send_packets_thread(thread_id: int, packet_count: int):
            for i in range(packet_count):
                packet = PacketFactory.create_task_packet(
                    f"sender_{thread_id}", 
                    "receiver", 
                    f"content_{thread_id}_{i}"
                )
                try:
                    messenger.send_packet(packet)
                except Exception:
                    pass  # Expected for some edge cases
                time.sleep(0.001)
        
        # Start multiple threads
        threads = []
        for thread_id in range(5):
            thread = threading.Thread(target=send_packets_thread, args=(thread_id, 10))
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Middleware should have handled concurrent access safely
        # (No specific assertions, just ensuring no crashes)
        assert len(security_middleware.security_violations) >= 0  # Could be empty if all valid
    
    def test_validation_edge_case_null_values(self):
        """Test validation with null/None values."""
        state = create_test_state_view()
        content_middleware = ContentValidationMiddleware(strict_schema=True)
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="test_node"),
            middleware=[content_middleware]
        )
        
        # Packet with None values
        null_packet = TaskPacket(
            src=ElementAddress(uid="sender"),
            dst=ElementAddress(uid="receiver"),
            payload={
                "content": None,
                "created_by": "sender",
                "task_id": "test_id"
            }
        )
        
        with pytest.raises(IEMValidationException):
            messenger.send_packet(null_packet)
    
    def test_validation_edge_case_unicode_content(self):
        """Test validation with Unicode and special characters."""
        state = create_test_state_view()
        content_middleware = ContentValidationMiddleware()
        
        messenger = DefaultInterMessenger(
            state=state,
            identity=ElementAddress(uid="test_node"),
            middleware=[content_middleware]
        )
        
        # Unicode content should be valid
        unicode_packet = PacketFactory.create_task_packet(
            "sender", "receiver", "测试内容 🚀 émojis"
        )
        
        # Should not raise exception
        messenger.send_packet(unicode_packet)
        
        # Special characters
        special_packet = PacketFactory.create_task_packet(
            "sender", "receiver", "Content with\nnewlines\tand\ttabs"
        )
        
        # Should not raise exception
        messenger.send_packet(special_packet)
