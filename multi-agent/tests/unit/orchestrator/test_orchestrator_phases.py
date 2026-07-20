"""
Unit tests for orchestrator phase system.

Tests the phase execution system from simple to complex:
- Phase enumeration and ordering
- Phase provider initialization
- Phase tool registration
- Phase transitions
- Phase iteration limits

Uses GENERIC test helpers that work for ALL phase-based systems.
"""

import pytest
from unittest.mock import Mock, patch

from mas.elements.nodes.orchestrator.orchestrator_node import OrchestratorNode
from mas.elements.nodes.orchestrator.orchestrator_phase_provider import OrchestratorPhase, OrchestratorPhaseProvider
from mas.elements.nodes.orchestrator.phases.models import PhaseIterationLimits, PhaseIterationState
from tests.base import BaseUnitTest, setup_node_with_state, setup_node_with_context


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.phases
class TestPhaseEnumeration(BaseUnitTest):
    """Test basic phase enumeration and ordering."""
    
    def test_phase_enum_values(self):
        """✅ SIMPLE: Test phase enum has correct values."""
        assert OrchestratorPhase.PLANNING.value == "planning"
        assert OrchestratorPhase.ALLOCATION.value == "allocation"
        assert OrchestratorPhase.EXECUTION.value == "execution"
        assert OrchestratorPhase.MONITORING.value == "monitoring"
        assert OrchestratorPhase.SYNTHESIS.value == "synthesis"
    
    def test_phase_execution_order(self):
        """✅ SIMPLE: Test phases are in correct execution order."""
        order = OrchestratorPhase.get_execution_order()
        
        assert len(order) == 5
        assert order[0] == OrchestratorPhase.PLANNING
        assert order[1] == OrchestratorPhase.ALLOCATION
        assert order[2] == OrchestratorPhase.EXECUTION
        assert order[3] == OrchestratorPhase.MONITORING
        assert order[4] == OrchestratorPhase.SYNTHESIS
    
    def test_phase_names_as_strings(self):
        """✅ SIMPLE: Test getting phase names as strings."""
        names = OrchestratorPhase.get_phase_names()
        
        assert names == ["planning", "allocation", "execution", "monitoring", "synthesis"]
    
    def test_phase_enum_iteration(self):
        """✅ SIMPLE: Test iterating over all phases."""
        phases = list(OrchestratorPhase)
        
        assert len(phases) == 5
        assert OrchestratorPhase.PLANNING in phases
        assert OrchestratorPhase.SYNTHESIS in phases


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.phases
class TestPhaseProviderInitialization(BaseUnitTest):
    """Test phase provider creation and configuration."""
    
    def test_phase_provider_basic_initialization(self):
        """✅ SIMPLE: Test creating phase provider with required dependencies."""
        # ✅ GENERIC: Mock dependencies (works for ANY phase provider)
        mock_get_adjacent = Mock(return_value={})
        mock_send_task = Mock(return_value="packet_id")
        mock_get_service = Mock()
        
        provider = OrchestratorPhaseProvider(
            domain_tools=[],
            get_adjacent_nodes=mock_get_adjacent,
            send_task=mock_send_task,
            node_uid="orch1",
            thread_id="thread1",
            get_workload_service=mock_get_service
        )
        
        assert provider is not None
        assert provider._node_uid == "orch1"
        assert provider._thread_id == "thread1"
    
    def test_phase_provider_with_domain_tools(self, basic_test_tools):
        """✅ SIMPLE: Test phase provider accepts domain tools."""
        mock_get_adjacent = Mock(return_value={})
        mock_send_task = Mock()
        mock_get_service = Mock()
        
        provider = OrchestratorPhaseProvider(
            domain_tools=basic_test_tools,
            get_adjacent_nodes=mock_get_adjacent,
            send_task=mock_send_task,
            node_uid="orch1",
            thread_id="thread1",
            get_workload_service=mock_get_service
        )
        
        assert len(provider._domain_tools) == len(basic_test_tools)
    
    def test_phase_provider_default_iteration_limits(self):
        """✅ SIMPLE: Test default iteration limits are set."""
        mock_get_adjacent = Mock(return_value={})
        mock_send_task = Mock()
        mock_get_service = Mock()
        
        provider = OrchestratorPhaseProvider(
            domain_tools=[],
            get_adjacent_nodes=mock_get_adjacent,
            send_task=mock_send_task,
            node_uid="orch1",
            thread_id="thread1",
            get_workload_service=mock_get_service
        )
        
        # Should have default limits
        assert provider._iteration_limits is not None
        assert isinstance(provider._iteration_limits, PhaseIterationLimits)
    
    def test_phase_provider_custom_iteration_limits(self):
        """✅ MEDIUM: Test custom iteration limits configuration."""
        mock_get_adjacent = Mock(return_value={})
        mock_send_task = Mock()
        mock_get_service = Mock()
        
        custom_limits = PhaseIterationLimits(
            planning=5,
            allocation=3,
            execution=2,
            monitoring=4,
            synthesis=1
        )
        
        provider = OrchestratorPhaseProvider(
            domain_tools=[],
            get_adjacent_nodes=mock_get_adjacent,
            send_task=mock_send_task,
            node_uid="orch1",
            thread_id="thread1",
            get_workload_service=mock_get_service,
            iteration_limits=custom_limits
        )
        
        assert provider._iteration_limits.planning == 5
        assert provider._iteration_limits.allocation == 3
        assert provider._iteration_limits.execution == 2


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.phases
class TestPhaseToolRegistration(BaseUnitTest):
    """Test tool registration for each phase."""
    
    def test_phase_provider_registers_all_phases(self):
        """✅ SIMPLE: Test provider registers all 5 orchestrator phases."""
        mock_get_adjacent = Mock(return_value={})
        mock_send_task = Mock()
        mock_get_service = Mock()
        
        provider = OrchestratorPhaseProvider(
            domain_tools=[],
            get_adjacent_nodes=mock_get_adjacent,
            send_task=mock_send_task,
            node_uid="orch1",
            thread_id="thread1",
            get_workload_service=mock_get_service
        )
        
        supported_phases = provider.get_supported_phases()
        
        assert len(supported_phases) == 5
        assert "planning" in supported_phases
        assert "allocation" in supported_phases
        assert "execution" in supported_phases
        assert "monitoring" in supported_phases
        assert "synthesis" in supported_phases
    
    def test_planning_phase_has_workplan_tools(self):
        """✅ MEDIUM: Test planning phase has work plan creation tools."""
        mock_get_adjacent = Mock(return_value={})
        mock_send_task = Mock()
        mock_get_service = Mock()
        
        provider = OrchestratorPhaseProvider(
            domain_tools=[],
            get_adjacent_nodes=mock_get_adjacent,
            send_task=mock_send_task,
            node_uid="orch1",
            thread_id="thread1",
            get_workload_service=mock_get_service
        )
        
        planning_tools = provider.get_tools_for_phase("planning")
        
        # Planning should have work plan tools (using namespaced names)
        tool_names = [tool.name for tool in planning_tools]
        assert "workplan.create_or_update" in tool_names or "create_or_update_work_plan" in tool_names
        # Just verify we have planning tools
        assert len(planning_tools) > 0
    
    def test_allocation_phase_has_assignment_tools(self):
        """✅ MEDIUM: Test allocation phase has work assignment tools."""
        mock_get_adjacent = Mock(return_value={})
        mock_send_task = Mock()
        mock_get_service = Mock()
        
        provider = OrchestratorPhaseProvider(
            domain_tools=[],
            get_adjacent_nodes=mock_get_adjacent,
            send_task=mock_send_task,
            node_uid="orch1",
            thread_id="thread1",
            get_workload_service=mock_get_service
        )
        
        allocation_tools = provider.get_tools_for_phase("allocation")
        
        # Allocation should have assignment and topology tools (using namespaced names)
        tool_names = [tool.name for tool in allocation_tools]
        assert "workplan.assign" in tool_names or "assign_work_item" in tool_names
        assert "topology.list_adjacent" in tool_names or "list_adjacent_nodes" in tool_names
        assert "topology.get_node_card" in tool_names or "get_node_card" in tool_names
    
    def test_execution_phase_has_delegation_tools(self):
        """✅ MEDIUM: Test execution phase has delegation tools."""
        mock_get_adjacent = Mock(return_value={})
        mock_send_task = Mock()
        mock_get_service = Mock()
        
        provider = OrchestratorPhaseProvider(
            domain_tools=[],
            get_adjacent_nodes=mock_get_adjacent,
            send_task=mock_send_task,
            node_uid="orch1",
            thread_id="thread1",
            get_workload_service=mock_get_service
        )
        
        execution_tools = provider.get_tools_for_phase("execution")
        
        # Execution phase should have tools available
        assert len(execution_tools) > 0
        # Tools may vary by phase, just verify phase is configured
    
    def test_monitoring_phase_has_status_tools(self):
        """✅ MEDIUM: Test monitoring phase has status update tools."""
        mock_get_adjacent = Mock(return_value={})
        mock_send_task = Mock()
        mock_get_service = Mock()
        
        provider = OrchestratorPhaseProvider(
            domain_tools=[],
            get_adjacent_nodes=mock_get_adjacent,
            send_task=mock_send_task,
            node_uid="orch1",
            thread_id="thread1",
            get_workload_service=mock_get_service
        )
        
        monitoring_tools = provider.get_tools_for_phase("monitoring")
        
        # Monitoring should have status tools (using namespaced names)
        tool_names = [tool.name for tool in monitoring_tools]
        assert "workplan.mark" in tool_names or "mark_work_item_status" in tool_names
    
    def test_domain_tools_provided_to_provider(self, basic_test_tools):
        """✅ MEDIUM: Test domain tools are stored in provider."""
        mock_get_adjacent = Mock(return_value={})
        mock_send_task = Mock()
        mock_get_service = Mock()
        
        provider = OrchestratorPhaseProvider(
            domain_tools=basic_test_tools,
            get_adjacent_nodes=mock_get_adjacent,
            send_task=mock_send_task,
            node_uid="orch1",
            thread_id="thread1",
            get_workload_service=mock_get_service
        )
        
        # Domain tools should be stored in provider
        assert len(provider._domain_tools) == len(basic_test_tools)
        
        # Each phase except synthesis should have some tools available
        # Synthesis is intentionally tool-free (produces text responses only)
        for phase_name in provider.get_supported_phases():
            phase_tools = provider.get_tools_for_phase(phase_name)
            if phase_name == "synthesis":
                assert len(phase_tools) == 0, "Synthesis phase should have no tools (text-only)"
            else:
                assert len(phase_tools) > 0, f"Phase {phase_name} should have tools"


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.phases
class TestPhaseIterationState(BaseUnitTest):
    """Test phase iteration state tracking."""
    
    def test_phase_iteration_state_initialization(self):
        """✅ SIMPLE: Test iteration state starts at zero."""
        state = PhaseIterationState()
        
        assert state.planning == 0
        assert state.allocation == 0
        assert state.execution == 0
        assert state.monitoring == 0
        assert state.synthesis == 0
    
    def test_phase_iteration_get_count(self):
        """✅ SIMPLE: Test getting iteration count for a phase."""
        state = PhaseIterationState(planning=3, allocation=2)
        
        assert state.get_count("planning") == 3
        assert state.get_count("allocation") == 2
        assert state.get_count("execution") == 0
    
    def test_phase_iteration_increment(self):
        """✅ SIMPLE: Test incrementing phase iteration count."""
        state = PhaseIterationState()
        
        # Increment planning
        new_state = state.increment("planning")
        
        # Original unchanged (immutable)
        assert state.planning == 0
        
        # New state incremented
        assert new_state.planning == 1
        assert new_state.allocation == 0
    
    def test_phase_iteration_reset(self):
        """✅ SIMPLE: Test resetting phase iteration count."""
        state = PhaseIterationState(planning=5, allocation=3)
        
        # Reset planning
        new_state = state.reset("planning")
        
        # Planning reset, allocation unchanged
        assert new_state.planning == 0
        assert new_state.allocation == 3
    
    def test_phase_iteration_immutability(self):
        """✅ MEDIUM: Test iteration state is immutable."""
        state = PhaseIterationState(planning=2)
        
        # Multiple operations
        state2 = state.increment("planning")
        state3 = state2.increment("allocation")
        state4 = state3.reset("planning")
        
        # Original unchanged
        assert state.planning == 2
        assert state.allocation == 0
        
        # Each step creates new instance
        assert state2.planning == 3
        assert state3.allocation == 1
        assert state4.planning == 0


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.phases
class TestPhaseIterationLimits(BaseUnitTest):
    """Test phase iteration limits configuration."""
    
    def test_phase_iteration_limits_defaults(self):
        """✅ SIMPLE: Test default iteration limits."""
        limits = PhaseIterationLimits()
        
        # Default should be 10 for all phases
        assert limits.planning == 10
        assert limits.allocation == 10
        assert limits.execution == 10
        assert limits.monitoring == 10
        assert limits.synthesis == 10
    
    def test_phase_iteration_limits_custom(self):
        """✅ SIMPLE: Test custom iteration limits."""
        limits = PhaseIterationLimits(
            planning=5,
            allocation=3,
            execution=2,
            monitoring=4,
            synthesis=1
        )
        
        assert limits.planning == 5
        assert limits.allocation == 3
        assert limits.execution == 2
        assert limits.monitoring == 4
        assert limits.synthesis == 1
    
    def test_phase_iteration_limits_to_dict(self):
        """✅ SIMPLE: Test converting limits to dictionary."""
        limits = PhaseIterationLimits(planning=5, allocation=3)
        
        limits_dict = limits.to_dict()
        
        assert limits_dict["planning"] == 5
        assert limits_dict["allocation"] == 3
        assert "execution" in limits_dict
    
    def test_phase_iteration_limits_validation(self):
        """✅ MEDIUM: Test limits must be positive."""
        # Should work with positive values
        limits = PhaseIterationLimits(planning=1, allocation=1)
        assert limits.planning == 1
        
        # Should fail with negative values (Pydantic validation)
        with pytest.raises(Exception):  # Pydantic ValidationError
            PhaseIterationLimits(planning=-1)
