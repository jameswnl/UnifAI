"""
IEM-Specific Testing Tools and Fixtures

Professional testing tools specifically designed for testing the IEM (Inter-Element Messaging) system.
Includes mock nodes, packet factories, chaos injection, and performance monitoring tools.
"""

import uuid
import time
import random
import threading
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Callable, Union
from unittest.mock import Mock, MagicMock
from dataclasses import dataclass, field
from contextlib import contextmanager

import pytest
from pydantic import BaseModel, Field

# IEM system imports
from mas.core.iem.packets import BaseIEMPacket, TaskPacket, SystemPacket, DebugPacket
from mas.core.iem.models import ElementAddress, PacketType, ErrorCode, IEMError
from mas.core.iem.interfaces import InterMessenger, MessengerMiddleware
from mas.core.iem.messenger import DefaultInterMessenger
from mas.core.iem.factory import create_messenger, messenger_from_ctx
from mas.elements.nodes.common.workload import Task, AgentResult
from mas.graph.state.state_view import StateView
from mas.graph.state.graph_state import GraphState, Channel
from mas.graph.models import StepContext


# =============================================================================
# MOCK IEM NODES FOR TESTING
# =============================================================================

class MockIEMNode:
    """
    Mock node that implements IEM protocol for comprehensive testing.
    
    Features:
    - Configurable behavior patterns
    - Packet tracking and metrics
    - Failure simulation capabilities
    - Performance monitoring
    """
    
    def __init__(self, uid: str, name: str = None, behavior: str = "normal"):
        self.uid = uid
        self.name = name or f"mock_node_{uid}"
        self.behavior = behavior
        
        # Tracking
        self.sent_packets: List[BaseIEMPacket] = []
        self.received_packets: List[BaseIEMPacket] = []
        self.acknowledged_packets: List[str] = []
        
        # Metrics
        self.packet_count = 0
        self.error_count = 0
        self.processing_times: List[float] = []
        
        # Behavior flags
        self.should_fail = False
        self.failure_rate = 0.0
        self.delay_ms = 0
        self.drop_packets = False
        
        # State
        self._state = {}
        self._messenger: Optional[InterMessenger] = None
        
    def set_messenger(self, messenger: InterMessenger):
        """Set the messenger for this mock node."""
        self._messenger = messenger
        
    def send_packet(self, packet: BaseIEMPacket) -> str:
        """Send a packet with behavior simulation."""
        start_time = time.time()
        
        # Simulate delay
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000)
            
        # Simulate failures
        if self.should_fail or (self.failure_rate > 0 and random.random() < self.failure_rate):
            self.error_count += 1
            raise Exception(f"Simulated failure in {self.name}")
            
        # Drop packets if configured
        if self.drop_packets:
            return packet.id
            
        # Track sent packet
        self.sent_packets.append(packet)
        self.packet_count += 1
        
        # Record processing time
        processing_time = time.time() - start_time
        self.processing_times.append(processing_time)
        
        if self._messenger:
            return self._messenger.send_packet(packet)
        return packet.id
        
    def receive_packet(self, packet: BaseIEMPacket) -> None:
        """Receive and process a packet."""
        start_time = time.time()
        
        # Track received packet
        self.received_packets.append(packet)
        
        # Simulate processing based on behavior
        if self.behavior == "slow":
            time.sleep(0.1)
        elif self.behavior == "unreliable":
            if random.random() < 0.3:
                raise Exception("Unreliable processing failure")
        elif self.behavior == "malicious":
            # Malicious nodes might corrupt or ignore packets
            packet.payload = {"corrupted": True}
            
        # Record processing time
        processing_time = time.time() - start_time
        self.processing_times.append(processing_time)
        
    def acknowledge_packet(self, packet_id: str) -> bool:
        """Acknowledge a packet."""
        self.acknowledged_packets.append(packet_id)
        if self._messenger:
            return self._messenger.acknowledge(packet_id)
        return True
        
    def get_metrics(self) -> Dict[str, Any]:
        """Get node performance metrics."""
        return {
            "packet_count": self.packet_count,
            "error_count": self.error_count,
            "sent_count": len(self.sent_packets),
            "received_count": len(self.received_packets),
            "acknowledged_count": len(self.acknowledged_packets),
            "avg_processing_time": sum(self.processing_times) / len(self.processing_times) if self.processing_times else 0,
            "max_processing_time": max(self.processing_times) if self.processing_times else 0,
            "error_rate": self.error_count / max(self.packet_count, 1)
        }
        
    def reset_metrics(self):
        """Reset all metrics and tracking data."""
        self.sent_packets.clear()
        self.received_packets.clear()
        self.acknowledged_packets.clear()
        self.packet_count = 0
        self.error_count = 0
        self.processing_times.clear()


class FlakyCommunicationNode(MockIEMNode):
    """Node that simulates various communication failures."""
    
    def __init__(self, uid: str, failure_patterns: Dict[str, float] = None):
        super().__init__(uid, behavior="flaky")
        self.failure_patterns = failure_patterns or {
            "send_failure": 0.1,
            "receive_failure": 0.1,
            "acknowledgment_failure": 0.05,
            "processing_delay": 0.2
        }
        
    def send_packet(self, packet: BaseIEMPacket) -> str:
        if random.random() < self.failure_patterns.get("send_failure", 0):
            self.error_count += 1
            raise Exception("Flaky send failure")
        return super().send_packet(packet)
        
    def receive_packet(self, packet: BaseIEMPacket) -> None:
        if random.random() < self.failure_patterns.get("receive_failure", 0):
            raise Exception("Flaky receive failure")
            
        if random.random() < self.failure_patterns.get("processing_delay", 0):
            time.sleep(random.uniform(0.1, 0.5))
            
        super().receive_packet(packet)
        
    def acknowledge_packet(self, packet_id: str) -> bool:
        if random.random() < self.failure_patterns.get("acknowledgment_failure", 0):
            return False
        return super().acknowledge_packet(packet_id)


class SlowProcessingNode(MockIEMNode):
    """Node that simulates slow packet processing."""
    
    def __init__(self, uid: str, base_delay_ms: int = 100, variability_ms: int = 50):
        super().__init__(uid, behavior="slow")
        self.base_delay_ms = base_delay_ms
        self.variability_ms = variability_ms
        
    def receive_packet(self, packet: BaseIEMPacket) -> None:
        # Variable processing delay
        delay = self.base_delay_ms + random.randint(0, self.variability_ms)
        time.sleep(delay / 1000)
        super().receive_packet(packet)


class MaliciousNode(MockIEMNode):
    """Node that sends malformed or malicious packets."""
    
    def __init__(self, uid: str, malicious_behaviors: List[str] = None):
        super().__init__(uid, behavior="malicious")
        self.malicious_behaviors = malicious_behaviors or [
            "corrupt_payload", "invalid_address", "oversized_packet", "spam_packets"
        ]
        
    def send_packet(self, packet: BaseIEMPacket) -> str:
        # Apply malicious behavior
        if "corrupt_payload" in self.malicious_behaviors:
            if hasattr(packet, 'payload'):
                packet.payload = {"__corrupted__": True, "original": packet.payload}
                
        if "invalid_address" in self.malicious_behaviors:
            packet.dst = ElementAddress(uid="__invalid__address__")
            
        if "oversized_packet" in self.malicious_behaviors:
            packet.payload = {"large_data": "x" * 10000}
            
        return super().send_packet(packet)


# =============================================================================
# PACKET FACTORIES FOR TESTING
# =============================================================================

class PacketFactory:
    """Factory for creating various packet types for testing."""
    
    @staticmethod
    def create_task_packet(
        src_uid: str = "test_src",
        dst_uid: str = "test_dst", 
        task_content: str = "Test task",
        thread_id: str = None,
        **kwargs
    ) -> TaskPacket:
        """Create a task packet for testing."""
        task = Task.create(
            content=task_content,
            thread_id=thread_id or str(uuid.uuid4()),
            created_by=src_uid
        )
        
        return TaskPacket.create(
            src=ElementAddress(uid=src_uid),
            dst=ElementAddress(uid=dst_uid),
            task=task,
            **kwargs
        )
        
    @staticmethod
    def create_system_packet(
        src_uid: str = "test_src",
        dst_uid: str = "test_dst",
        system_event: str = "test_event",
        data: Dict[str, Any] = None,
        **kwargs
    ) -> SystemPacket:
        """Create a system packet for testing."""
        return SystemPacket(
            src=ElementAddress(uid=src_uid),
            dst=ElementAddress(uid=dst_uid),
            system_event=system_event,
            data=data or {},
            **kwargs
        )
        
    @staticmethod
    def create_debug_packet(
        src_uid: str = "test_src",
        dst_uid: str = "test_dst",
        debug_info: Dict[str, Any] = None,
        **kwargs
    ) -> DebugPacket:
        """Create a debug packet for testing."""
        return DebugPacket(
            src=ElementAddress(uid=src_uid),
            dst=ElementAddress(uid=dst_uid),
            debug_info=debug_info or {"test": True},
            **kwargs
        )
        
    @staticmethod
    def create_expired_packet(
        src_uid: str = "test_src",
        dst_uid: str = "test_dst",
        expired_seconds_ago: int = 60
    ) -> TaskPacket:
        """Create an expired packet for testing."""
        packet = PacketFactory.create_task_packet(src_uid, dst_uid)
        # Backdate the timestamp
        packet.ts = datetime.now(timezone.utc) - timedelta(seconds=expired_seconds_ago)
        packet.ttl = timedelta(seconds=30)  # Short TTL to ensure expiration
        return packet
        
    @staticmethod
    def create_large_packet(
        src_uid: str = "test_src",
        dst_uid: str = "test_dst",
        payload_size_kb: int = 100
    ) -> TaskPacket:
        """Create a large packet for testing."""
        large_data = "x" * (payload_size_kb * 1024)
        task = Task.create(
            content="Large task",
            data={"large_field": large_data}
        )
        
        return TaskPacket.create(
            src=ElementAddress(uid=src_uid),
            dst=ElementAddress(uid=dst_uid),
            task=task
        )
        
    @staticmethod
    def create_packet_batch(
        count: int,
        src_uid: str = "test_src",
        dst_uid: str = "test_dst",
        packet_type: str = "task"
    ) -> List[BaseIEMPacket]:
        """Create a batch of packets for testing."""
        packets = []
        
        for i in range(count):
            if packet_type == "task":
                packet = PacketFactory.create_task_packet(
                    src_uid, dst_uid, f"Task {i+1}"
                )
            elif packet_type == "system":
                packet = PacketFactory.create_system_packet(
                    src_uid, dst_uid, f"event_{i+1}"
                )
            elif packet_type == "debug":
                packet = PacketFactory.create_debug_packet(
                    src_uid, dst_uid, {"batch_index": i}
                )
            else:
                raise ValueError(f"Unknown packet type: {packet_type}")
                
            packets.append(packet)
            
        return packets


# =============================================================================
# CHAOS INJECTION TOOLS
# =============================================================================

@dataclass
class ChaosScenario:
    """Configuration for a chaos engineering scenario."""
    name: str
    description: str
    failure_rate: float = 0.1
    duration_seconds: int = 10
    affected_operations: List[str] = field(default_factory=list)
    recovery_time_seconds: int = 5


class IEMChaosInjector:
    """Chaos engineering tool for IEM testing."""
    
    def __init__(self):
        self.active_scenarios: Dict[str, ChaosScenario] = {}
        self.failure_history: List[Dict[str, Any]] = []
        self._chaos_thread: Optional[threading.Thread] = None
        self._stop_chaos = threading.Event()
        
    def inject_packet_drops(self, messenger: InterMessenger, drop_rate: float = 0.1):
        """Inject random packet drops."""
        original_send = messenger.send_packet
        
        def chaotic_send(packet: BaseIEMPacket) -> str:
            if random.random() < drop_rate:
                self.failure_history.append({
                    "type": "packet_drop",
                    "packet_id": packet.id,
                    "timestamp": datetime.utcnow()
                })
                # Simulate drop by returning fake ID
                return str(uuid.uuid4())
            return original_send(packet)
            
        messenger.send_packet = chaotic_send
        
    def inject_acknowledgment_failures(self, messenger: InterMessenger, failure_rate: float = 0.1):
        """Inject random acknowledgment failures."""
        original_ack = messenger.acknowledge
        
        def chaotic_acknowledge(packet_id: str) -> bool:
            if random.random() < failure_rate:
                self.failure_history.append({
                    "type": "acknowledgment_failure", 
                    "packet_id": packet_id,
                    "timestamp": datetime.utcnow()
                })
                return False
            return original_ack(packet_id)
            
        messenger.acknowledge = chaotic_acknowledge
        
    def inject_processing_delays(self, node: MockIEMNode, delay_range_ms: tuple = (50, 500)):
        """Inject random processing delays."""
        original_receive = node.receive_packet
        
        def delayed_receive(packet: BaseIEMPacket) -> None:
            delay_ms = random.randint(*delay_range_ms)
            time.sleep(delay_ms / 1000)
            self.failure_history.append({
                "type": "processing_delay",
                "delay_ms": delay_ms,
                "node_uid": node.uid,
                "timestamp": datetime.utcnow()
            })
            return original_receive(packet)
            
        node.receive_packet = delayed_receive
        
    def inject_network_partitions(self, nodes: List[MockIEMNode], partition_groups: List[List[str]]):
        """Simulate network partitions between node groups."""
        for node in nodes:
            if hasattr(node, '_messenger') and node._messenger:
                original_send = node._messenger.send_packet
                
                def partitioned_send(packet: BaseIEMPacket) -> str:
                    # Check if packet crosses partition boundary
                    src_group = self._find_node_group(node.uid, partition_groups)
                    dst_group = self._find_node_group(packet.dst.uid, partition_groups)
                    
                    if src_group != dst_group and src_group is not None and dst_group is not None:
                        self.failure_history.append({
                            "type": "network_partition",
                            "src_uid": node.uid,
                            "dst_uid": packet.dst.uid,
                            "timestamp": datetime.utcnow()
                        })
                        raise Exception("Network partition: packet blocked")
                        
                    return original_send(packet)
                    
                node._messenger.send_packet = partitioned_send
                
    def _find_node_group(self, uid: str, partition_groups: List[List[str]]) -> Optional[int]:
        """Find which partition group a node belongs to."""
        for i, group in enumerate(partition_groups):
            if uid in group:
                return i
        return None
        
    @contextmanager
    def chaos_scenario(self, scenario: ChaosScenario, target_components: List[Any]):
        """Execute a chaos scenario for a specific duration."""
        print(f"Starting chaos scenario: {scenario.name}")
        
        try:
            # Apply chaos based on scenario configuration
            if "packet_drops" in scenario.affected_operations:
                for component in target_components:
                    if hasattr(component, 'send_packet'):
                        self.inject_packet_drops(component, scenario.failure_rate)
                        
            if "acknowledgment_failures" in scenario.affected_operations:
                for component in target_components:
                    if hasattr(component, 'acknowledge'):
                        self.inject_acknowledgment_failures(component, scenario.failure_rate)
                        
            if "processing_delays" in scenario.affected_operations:
                for component in target_components:
                    if isinstance(component, MockIEMNode):
                        self.inject_processing_delays(component)
                        
            # Let chaos run for specified duration
            time.sleep(scenario.duration_seconds)
            
        finally:
            print(f"Chaos scenario {scenario.name} completed")
            # Recovery time
            time.sleep(scenario.recovery_time_seconds)
            
        yield self.failure_history
        
    def get_failure_summary(self) -> Dict[str, Any]:
        """Get summary of all injected failures."""
        failure_types = {}
        for failure in self.failure_history:
            failure_type = failure["type"]
            failure_types[failure_type] = failure_types.get(failure_type, 0) + 1
            
        return {
            "total_failures": len(self.failure_history),
            "failure_types": failure_types,
            "timeline": sorted(self.failure_history, key=lambda x: x["timestamp"])
        }


# =============================================================================
# PERFORMANCE MONITORING TOOLS
# =============================================================================

@dataclass
class PerformanceMetrics:
    """Performance metrics for IEM operations."""
    operation_name: str
    start_time: float
    end_time: float
    success: bool
    error_message: str = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def duration_ms(self) -> float:
        """Get operation duration in milliseconds."""
        return (self.end_time - self.start_time) * 1000


class IEMPerformanceMonitor:
    """Performance monitoring tool for IEM operations."""
    
    def __init__(self):
        self.metrics: List[PerformanceMetrics] = []
        self._active_operations: Dict[str, float] = {}
        
    @contextmanager
    def monitor_operation(self, operation_name: str, metadata: Dict[str, Any] = None):
        """Monitor the performance of an IEM operation."""
        operation_id = f"{operation_name}_{uuid.uuid4().hex[:8]}"
        start_time = time.time()
        
        try:
            yield operation_id
            # Success case
            end_time = time.time()
            self.metrics.append(PerformanceMetrics(
                operation_name=operation_name,
                start_time=start_time,
                end_time=end_time,
                success=True,
                metadata=metadata or {}
            ))
            
        except Exception as e:
            # Failure case
            end_time = time.time()
            self.metrics.append(PerformanceMetrics(
                operation_name=operation_name,
                start_time=start_time,
                end_time=end_time,
                success=False,
                error_message=str(e),
                metadata=metadata or {}
            ))
            raise
            
    def get_operation_stats(self, operation_name: str) -> Dict[str, Any]:
        """Get statistics for a specific operation."""
        operation_metrics = [m for m in self.metrics if m.operation_name == operation_name]
        
        if not operation_metrics:
            return {"error": f"No metrics found for operation: {operation_name}"}
            
        durations = [m.duration_ms for m in operation_metrics]
        success_count = sum(1 for m in operation_metrics if m.success)
        
        return {
            "operation_name": operation_name,
            "total_calls": len(operation_metrics),
            "success_count": success_count,
            "failure_count": len(operation_metrics) - success_count,
            "success_rate": success_count / len(operation_metrics),
            "avg_duration_ms": sum(durations) / len(durations),
            "min_duration_ms": min(durations),
            "max_duration_ms": max(durations),
            "total_duration_ms": sum(durations)
        }
        
    def get_overall_stats(self) -> Dict[str, Any]:
        """Get overall performance statistics."""
        if not self.metrics:
            return {"error": "No metrics collected"}
            
        operations = set(m.operation_name for m in self.metrics)
        operation_stats = {op: self.get_operation_stats(op) for op in operations}
        
        total_success = sum(1 for m in self.metrics if m.success)
        total_duration = sum(m.duration_ms for m in self.metrics)
        
        return {
            "total_operations": len(self.metrics),
            "unique_operation_types": len(operations),
            "overall_success_rate": total_success / len(self.metrics),
            "total_duration_ms": total_duration,
            "avg_duration_ms": total_duration / len(self.metrics),
            "operation_breakdown": operation_stats
        }
        
    def reset_metrics(self):
        """Reset all collected metrics."""
        self.metrics.clear()
        self._active_operations.clear()


# =============================================================================
# TEST GRAPH STATE SETUP
# =============================================================================

def create_test_graph_state() -> GraphState:
    """
    Create a test graph state with IEM channels.
    
    Note: For most testing, prefer using the shared 'graph_state' fixture from conftest.py
    This function is kept for IEM-specific testing scenarios that need custom state setup.
    """
    state = GraphState()
    state.inter_packets = []
    state.threads = {}
    state.workspaces = {}
    state.task_threads = {}
    return state


def create_test_state_view(graph_state: GraphState = None) -> StateView:
    """
    Create a test state view for IEM testing.
    
    Note: For most testing, prefer using the shared 'state_view' fixture from conftest.py
    This function is kept for IEM-specific testing scenarios that need custom state setup.
    """
    if graph_state is None:
        graph_state = create_test_graph_state()
    
    # For testing, we need to provide read/write access to all IEM-related channels
    # This simulates what a node with IEM and workload capabilities would have
    reads = {
        Channel.INTER_PACKETS,  # IEM packets
        Channel.THREADS,        # Thread metadata
        Channel.WORKSPACES,     # Workspace data
        Channel.TASK_THREADS,   # Task conversation threads
        Channel.MESSAGES,       # Public conversation
        Channel.USER_PROMPT     # User input
    }
    writes = {
        Channel.INTER_PACKETS,  # IEM packets
        Channel.THREADS,        # Thread metadata  
        Channel.WORKSPACES,     # Workspace data
        Channel.TASK_THREADS,   # Task conversation threads
        Channel.MESSAGES,       # Public conversation
        Channel.NODES_OUTPUT    # Node outputs
    }
    
    return StateView(graph_state, reads=reads, writes=writes)


def create_test_step_context(uid: str, adjacent_nodes: List[str] = None) -> StepContext:
    """
    Create a test step context for IEM testing.
    
    Note: For most testing, prefer using the shared fixtures from conftest.py:
    - 'step_context' for basic context
    - 'step_context_with_adjacency' for context with adjacent nodes
    - create_step_context() factory function for custom scenarios
    
    This function is kept for IEM-specific testing scenarios.
    """
    # Use the shared factory function from conftest.py for consistency
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from conftest import create_step_context as shared_create_step_context
    return shared_create_step_context(uid, adjacent_nodes)


# =============================================================================
# MOCK CLASSES FOR TESTING
# =============================================================================

class MockMiddleware(MessengerMiddleware):
    """Mock middleware for testing."""
    
    def __init__(self, modify_before_send: bool = False, reject_packets: bool = False):
        self.modify_before_send = modify_before_send
        self.reject_packets = reject_packets
        self.before_send_calls = []
        self.after_receive_calls = []
    
    def before_send(self, packet: BaseIEMPacket) -> BaseIEMPacket:
        """Mock before_send implementation."""
        self.before_send_calls.append(packet)
        
        if self.reject_packets:
            from mas.core.iem.exceptions import IEMValidationException
            raise IEMValidationException("Mock rejection")
        
        if self.modify_before_send:
            # Create a modified copy of the packet
            modified_packet = type(packet)(**packet.model_dump())
            modified_packet.payload = {"modified": True, **packet.payload}
            return modified_packet
        
        return packet
    
    def after_receive(self, packet: BaseIEMPacket) -> BaseIEMPacket:
        """Mock after_receive implementation."""
        self.after_receive_calls.append(packet)
        
        if self.reject_packets:
            from mas.core.iem.exceptions import IEMValidationException
            raise IEMValidationException("Mock rejection")
        
        return packet


class MockNode:
    """Mock node for IEM testing scenarios."""
    
    def __init__(self, uid: str, behavior: str = "normal"):
        self.uid = uid
        self.behavior = behavior
        self.packets_received = []
        self.packets_sent = []
        self.response_delay = 0.0
        self.failure_rate = 0.0
        
    def receive_packet(self, packet: BaseIEMPacket):
        """Simulate receiving a packet."""
        self.packets_received.append(packet)
        
        if self.behavior == "slow":
            import time
            time.sleep(self.response_delay)
        elif self.behavior == "unreliable":
            import random
            if random.random() < self.failure_rate:
                raise Exception("Simulated node failure")
        elif self.behavior == "malicious":
            # Malicious node could modify or drop packets
            return None
        
        return packet
    
    def send_packet(self, packet: BaseIEMPacket):
        """Simulate sending a packet."""
        self.packets_sent.append(packet)
        return packet


class ChaosInjector:
    """Chaos engineering utility for IEM testing."""
    
    def __init__(self):
        self.enabled = False
        self.packet_drop_rate = 0.0
        self.packet_delay_rate = 0.0
        self.packet_corruption_rate = 0.0
        self.node_failure_rate = 0.0
        
    def enable_chaos(self, drop_rate: float = 0.1, delay_rate: float = 0.1, 
                     corruption_rate: float = 0.05, failure_rate: float = 0.01):
        """Enable chaos injection with specified rates."""
        self.enabled = True
        self.packet_drop_rate = drop_rate
        self.packet_delay_rate = delay_rate
        self.packet_corruption_rate = corruption_rate
        self.node_failure_rate = failure_rate
    
    def disable_chaos(self):
        """Disable chaos injection."""
        self.enabled = False
    
    def inject_packet_chaos(self, packet: BaseIEMPacket) -> tuple[BaseIEMPacket, bool]:
        """
        Inject chaos into a packet.
        
        Returns:
            (modified_packet, should_drop)
        """
        if not self.enabled:
            return packet, False
        
        import random
        
        # Check if packet should be dropped
        if random.random() < self.packet_drop_rate:
            return packet, True
        
        # Check if packet should be delayed
        if random.random() < self.packet_delay_rate:
            import time
            time.sleep(random.uniform(0.1, 0.5))
        
        # Check if packet should be corrupted
        if random.random() < self.packet_corruption_rate:
            corrupted_packet = type(packet)(**packet.model_dump())
            corrupted_packet.payload = {"corrupted": True, **packet.payload}
            return corrupted_packet, False
        
        return packet, False
    
    def inject_node_chaos(self) -> bool:
        """
        Check if a node should fail.
        
        Returns:
            True if node should fail
        """
        if not self.enabled:
            return False
        
        import random
        return random.random() < self.node_failure_rate


# =============================================================================
# FACTORY FUNCTIONS FOR TEST SCENARIOS
# =============================================================================

def create_basic_iem_test_setup(node_count: int = 3) -> Dict[str, Any]:
    """Create basic IEM test setup with multiple nodes."""
    nodes = []
    for i in range(node_count):
        node = MockIEMNode(f"node_{i+1}")
        nodes.append(node)
        
    state = create_test_state_view()
    packet_factory = PacketFactory()
    
    return {
        "nodes": nodes,
        "state": state,
        "packet_factory": packet_factory,
        "context": create_test_step_context("test_node", [f"node_{i+1}" for i in range(node_count)])
    }


def create_flaky_network_test_setup() -> Dict[str, Any]:
    """Create test setup with flaky network conditions."""
    nodes = [
        FlakyCommunicationNode("flaky_1", {"send_failure": 0.2}),
        FlakyCommunicationNode("flaky_2", {"receive_failure": 0.15}),
        SlowProcessingNode("slow_1", base_delay_ms=200),
        MaliciousNode("malicious_1", ["corrupt_payload"])
    ]
    
    chaos_injector = IEMChaosInjector()
    performance_monitor = IEMPerformanceMonitor()
    
    return {
        "nodes": nodes,
        "state": create_test_state_view(),
        "packet_factory": PacketFactory(),
        "chaos_injector": chaos_injector,
        "performance_monitor": performance_monitor
    }


def create_stress_test_setup(node_count: int = 10, packet_count: int = 1000) -> Dict[str, Any]:
    """Create setup for stress testing scenarios."""
    nodes = [MockIEMNode(f"stress_node_{i+1}") for i in range(node_count)]
    packets = PacketFactory.create_packet_batch(packet_count, "stress_src", "stress_dst")
    
    return {
        "nodes": nodes,
        "packets": packets,
        "state": create_test_state_view(),
        "performance_monitor": IEMPerformanceMonitor()
    }
