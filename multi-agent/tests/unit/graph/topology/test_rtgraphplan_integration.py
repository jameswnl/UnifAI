"""
Comprehensive integration tests for RTGraphPlan with the new topology system.

Tests that RTGraphPlan correctly creates StepContext with StepTopology containing
FinalizerPathInfo, and that this information is properly injected into nodes.
"""

import pytest
from unittest.mock import Mock, MagicMock, call
from mas.graph.rt_graph_plan import RTGraphPlan
from mas.graph.graph_plan import GraphPlan
from mas.graph.models import Step, StepContext
from mas.graph.topology.models import StepTopology, FinalizerPathInfo
from mas.core.enums import ResourceCategory
from mas.session.domain.session_registry import SessionRegistry
from mas.catalog.element_registry import ElementRegistry
from mas.blueprints.models.blueprint import StepMeta
from mas.elements.common.card import ElementCard


# ------------------------------------------------------------------ #
#  Module-level fixtures
# ------------------------------------------------------------------ #

@pytest.fixture
def mock_element_registry():
    """Mock element registry for card building."""
    registry = Mock(spec=ElementRegistry)
    mock_spec = Mock()
    mock_spec.category = ResourceCategory.NODE
    mock_spec.type_key = "test_type"
    mock_spec.name = "Test"
    mock_spec.description = "Test description"
    mock_spec.capability_names = []
    from mas.elements.common.card.default import DefaultCardBuilder
    mock_spec.card_builder_cls = DefaultCardBuilder
    registry.get_spec.return_value = mock_spec
    return registry


@pytest.fixture(autouse=True)
def _patch_card_building(monkeypatch):
    """Patch _build_all_cards to build cards from logical plan steps directly.

    The real _build_all_cards relies on SessionConfigCollector and
    ElementCardService, which require a fully populated
    SessionRegistry._store.  For integration tests that focus on topology
    we short-circuit card building so that every step in the logical plan
    gets a minimal ElementCard keyed by its rid.
    """

    def _build_all_cards(self):
        for step in self._logical_plan.steps:
            self._cards[step.rid] = ElementCard(
                uid=step.uid,
                category=step.category,
                type_key=step.type_key,
                name=f"Test {step.uid}",
                description=f"Test card for {step.uid}",
            )

    monkeypatch.setattr(RTGraphPlan, '_build_all_cards', _build_all_cards)


class TestRTGraphPlanTopologyIntegration:
    """Test integration of topology analysis into RTGraphPlan."""

    @pytest.fixture
    def mock_session_registry(self):
        """Mock session registry for testing."""
        registry = Mock(spec=SessionRegistry)
        
        # Provide _store for SessionConfigCollector
        registry._store = {cat: {} for cat in ResourceCategory}
        
        # Create mock node instances
        mock_nodes = {}
        for node_id in ["orchestrator", "agent", "processor", "finalizer"]:
            mock_node = Mock()
            mock_node.set_context = Mock()
            mock_node.__dict__['set_context'] = mock_node.set_context
            mock_nodes[f"{node_id}_rid"] = mock_node
        
        def get_instance_side_effect(category, rid):
            if rid in mock_nodes:
                return mock_nodes[rid]
            new_mock = Mock()
            new_mock.set_context = Mock()
            new_mock.__dict__['set_context'] = new_mock.set_context
            mock_nodes[rid] = new_mock
            return new_mock
        
        def get_runtime_element_side_effect(category, rid):
            runtime_element = Mock()
            runtime_element.instance = mock_nodes.get(rid, Mock())
            runtime_element.config = Mock()
            
            spec = Mock()
            spec.type_key = "test_type"
            spec.name = f"Test {rid}"
            spec.description = f"Test description for {rid}"
            spec.capability_surface = set()
            spec.reads = []
            spec.writes = []
            
            runtime_element.spec = spec
            return runtime_element
        
        registry.get_instance.side_effect = get_instance_side_effect
        registry.get_runtime_element.side_effect = get_runtime_element_side_effect
        return registry, mock_nodes
    
    def test_rtgraphplan_creates_topology_for_simple_chain(self, mock_session_registry, mock_element_registry):
        """Test RTGraphPlan creates topology for simple chain to finalizer."""
        registry, mock_nodes = mock_session_registry
        
        # Create simple chain: orchestrator -> agent -> finalizer
        orchestrator = Step(
            uid="orchestrator",
            category=ResourceCategory.NODE,
            rid="orchestrator_rid",
            type_key="orchestrator",
            writes={"messages"}
        )
        
        agent = Step(
            uid="agent",
            category=ResourceCategory.NODE,
            rid="agent_rid",
            type_key="agent",
            reads={"messages"},
            writes={"nodes_output"},
            after=["orchestrator"]
        )
        
        finalizer = Step(
            uid="finalizer",
            category=ResourceCategory.NODE,
            rid="finalizer_rid",
            type_key="finalizer",
            reads={"nodes_output"},
            writes={"output"},  # Finalizer
            after=["agent"]
        )
        
        # Create logical plan
        logical_plan = GraphPlan()
        logical_plan.add_step(orchestrator)
        logical_plan.add_step(agent)
        logical_plan.add_step(finalizer)
        
        # Create runtime plan
        rt_plan = RTGraphPlan(logical_plan, registry, mock_element_registry)
        
        # Verify orchestrator got topology information
        orchestrator_node = mock_nodes["orchestrator_rid"]
        orchestrator_node.set_context.assert_called_once()
        
        context = orchestrator_node.set_context.call_args[0][0]
        assert isinstance(context, StepContext)
        assert context.uid == "orchestrator"
        assert isinstance(context.topology, StepTopology)
        
        # Orchestrator should see agent as adjacent with path to finalizer
        assert context.topology.has_finalizer_path()
        assert context.topology.get_distance_to_finalizer("agent") == 2  # agent -> finalizer + 1
        assert context.topology.get_nearest_finalizer_node() == "agent"
    
    def test_rtgraphplan_creates_topology_for_multiple_paths(self, mock_session_registry, mock_element_registry):
        """Test RTGraphPlan creates topology for multiple paths to finalizers."""
        registry, mock_nodes = mock_session_registry
        
        # Create graph: orchestrator -> [agent1, agent2] -> finalizer
        # agent1 has shorter path, agent2 has longer path
        orchestrator = Step(
            uid="orchestrator",
            category=ResourceCategory.NODE,
            rid="orchestrator_rid",
            type_key="orchestrator",
            writes={"messages"}
        )
        
        agent1 = Step(
            uid="agent1",
            category=ResourceCategory.NODE,
            rid="agent1_rid",
            type_key="agent",
            reads={"messages"},
            writes={"output"},  # Direct finalizer
            after=["orchestrator"]
        )
        
        agent2 = Step(
            uid="agent2",
            category=ResourceCategory.NODE,
            rid="agent2_rid",
            type_key="agent",
            reads={"messages"},
            writes={"intermediate"},
            after=["orchestrator"]
        )
        
        processor = Step(
            uid="processor",
            category=ResourceCategory.NODE,
            rid="processor_rid",
            type_key="processor",
            reads={"intermediate"},
            writes={"output"},  # Also a finalizer
            after=["agent2"]
        )
        
        # Add mock for processor
        mock_nodes["processor_rid"] = Mock()
        mock_nodes["processor_rid"].set_context = Mock()
        
        logical_plan = GraphPlan()
        for step in [orchestrator, agent1, agent2, processor]:
            logical_plan.add_step(step)
        
        rt_plan = RTGraphPlan(logical_plan, registry, mock_element_registry)
        
        # Check orchestrator's topology
        context = mock_nodes["orchestrator_rid"].set_context.call_args[0][0]
        assert context.topology.has_finalizer_path()
        
        # agent1 should have distance 1 (direct finalizer)
        assert context.topology.get_distance_to_finalizer("agent1") == 1
        # agent2 should have distance 2 (agent2 -> processor + 1)
        assert context.topology.get_distance_to_finalizer("agent2") == 2
        
        # Shortest path should be through agent1
        assert context.topology.get_shortest_finalizer_distance() == 1
        assert context.topology.get_nearest_finalizer_node() == "agent1"
    
    def test_rtgraphplan_handles_no_finalizer_paths(self, mock_session_registry, mock_element_registry):
        """Test RTGraphPlan handles nodes with no paths to finalizers."""
        registry, mock_nodes = mock_session_registry
        
        # Create graph with no finalizers
        node1 = Step(
            uid="node1",
            category=ResourceCategory.NODE,
            rid="node1_rid",
            type_key="node1",
            writes={"data1"}
        )
        
        node2 = Step(
            uid="node2",
            category=ResourceCategory.NODE,
            rid="node2_rid",
            type_key="node2",
            reads={"data1"},
            writes={"data2"},  # Not a finalizer
            after=["node1"]
        )
        
        # Add mock for node2
        mock_nodes["node1_rid"] = Mock()
        mock_nodes["node1_rid"].set_context = Mock()
        mock_nodes["node2_rid"] = Mock()
        mock_nodes["node2_rid"].set_context = Mock()
        
        logical_plan = GraphPlan()
        logical_plan.add_step(node1)
        logical_plan.add_step(node2)
        
        rt_plan = RTGraphPlan(logical_plan, registry, mock_element_registry)
        
        # Check node1's topology
        context = mock_nodes["node1_rid"].set_context.call_args[0][0]
        assert isinstance(context.topology, StepTopology)
        assert not context.topology.has_finalizer_path()
        assert context.topology.finalizer_paths is None
    
    def test_rtgraphplan_handles_cycles(self, mock_session_registry, mock_element_registry):
        """Test RTGraphPlan handles cyclic graphs correctly."""
        registry, mock_nodes = mock_session_registry
        
        # Create cycle: A -> B -> A, plus A -> C -> finalizer
        node_a = Step(
            uid="A",
            category=ResourceCategory.NODE,
            rid="A_rid",
            type_key="A",
            writes={"data_a"}
        )
        
        node_b = Step(
            uid="B",
            category=ResourceCategory.NODE,
            rid="B_rid",
            type_key="B",
            reads={"data_a"},
            writes={"data_a"},  # Cycles back
            after=["A"]
        )
        
        node_c = Step(
            uid="C",
            category=ResourceCategory.NODE,
            rid="C_rid",
            type_key="C",
            reads={"data_a"},
            writes={"data_c"},
            after=["A"]
        )
        
        finalizer = Step(
            uid="finalizer",
            category=ResourceCategory.NODE,
            rid="finalizer_rid",
            type_key="finalizer",
            reads={"data_c"},
            writes={"output"},
            after=["C"]
        )
        
        # Add mocks
        for node_id in ["A", "B", "C"]:
            mock_nodes[f"{node_id}_rid"] = Mock()
            mock_nodes[f"{node_id}_rid"].set_context = Mock()
        
        logical_plan = GraphPlan()
        for step in [node_a, node_b, node_c, finalizer]:
            logical_plan.add_step(step)
        
        rt_plan = RTGraphPlan(logical_plan, registry, mock_element_registry)
        
        # Check A's topology - should find path through C but handle B cycle
        context = mock_nodes["A_rid"].set_context.call_args[0][0]
        assert context.topology.has_finalizer_path()
        
        # Should have path through C
        assert context.topology.get_distance_to_finalizer("C") == 2  # C -> finalizer + 1
        
        # B might or might not be included depending on cycle detection
        # The key is that we have at least one valid path
        assert context.topology.get_shortest_finalizer_distance() >= 2
    
    def test_rtgraphplan_handles_branching_conditions(self, mock_session_registry, mock_element_registry):
        """Test RTGraphPlan handles conditional branching in topology."""
        registry, mock_nodes = mock_session_registry
        
        # Create conditional branch: orchestrator -> {success: agent1, failure: agent2}
        orchestrator = Step(
            uid="orchestrator",
            category=ResourceCategory.NODE,
            rid="orchestrator_rid",
            type_key="orchestrator",
            writes={"messages"},
            branches={"success": "agent1", "failure": "agent2"}  # Conditional branches
        )
        
        agent1 = Step(
            uid="agent1",
            category=ResourceCategory.NODE,
            rid="agent1_rid",
            type_key="agent",
            reads={"messages"},
            writes={"output"}  # Finalizer
        )
        
        agent2 = Step(
            uid="agent2",
            category=ResourceCategory.NODE,
            rid="agent2_rid",
            type_key="agent",
            reads={"messages"},
            writes={"output"}  # Also finalizer
        )
        
        logical_plan = GraphPlan()
        for step in [orchestrator, agent1, agent2]:
            logical_plan.add_step(step)
        
        rt_plan = RTGraphPlan(logical_plan, registry, mock_element_registry)
        
        # Check orchestrator's topology
        context = mock_nodes["orchestrator_rid"].set_context.call_args[0][0]
        assert context.topology.has_finalizer_path()
        
        # Both agents should be reachable with distance 1 (direct finalizers)
        assert context.topology.get_distance_to_finalizer("agent1") == 1
        assert context.topology.get_distance_to_finalizer("agent2") == 1
        assert context.topology.get_shortest_finalizer_distance() == 1
        
        # Should include both in reachable nodes
        reachable = set(context.topology.get_finalizer_reachable_nodes())
        assert reachable == {"agent1", "agent2"}
        
        # Should be able to access composed FinalizerPathInfo directly
        assert context.topology.finalizer_paths is not None
        assert isinstance(context.topology.finalizer_paths, FinalizerPathInfo)
        assert context.topology.finalizer_paths.distances == {"agent1": 1, "agent2": 1}


class TestRTGraphPlanStepContextInjection:
    """Test that StepContext with topology is properly injected into nodes."""
    
    @pytest.fixture
    def mock_session_registry(self):
        """Mock session registry that tracks set_context calls."""
        registry = Mock(spec=SessionRegistry)
        
        # Create mock nodes that track set_context calls
        context_calls = {}
        
        def create_mock_node(rid):
            mock_node = Mock()
            mock_node.set_context = Mock()
            # Ensure hasattr works
            mock_node.__dict__['set_context'] = mock_node.set_context
            
            def track_context(context):
                context_calls[rid] = context
            
            mock_node.set_context.side_effect = track_context
            return mock_node
        
        mock_nodes = {
            "node1_rid": create_mock_node("node1_rid"),
            "node2_rid": create_mock_node("node2_rid"),
            "finalizer_rid": create_mock_node("finalizer_rid")
        }
        
        def get_instance_side_effect(category, rid):
            if rid in mock_nodes:
                return mock_nodes[rid]
            # Create new mock for unknown rids
            new_mock = create_mock_node(rid)
            mock_nodes[rid] = new_mock
            return new_mock
        
        def get_runtime_element_side_effect(category, rid):
            # Create a mock runtime element
            runtime_element = Mock()
            runtime_element.instance = mock_nodes.get(rid, Mock())
            runtime_element.config = Mock()
            
            # Create mock spec with required attributes
            spec = Mock()
            spec.type_key = "test_type"
            spec.name = f"Test {rid}"
            spec.description = f"Test description for {rid}"
            spec.capability_surface = set()
            spec.reads = []  # Empty list instead of Mock
            spec.writes = []  # Empty list instead of Mock
            
            runtime_element.spec = spec
            return runtime_element
        
        registry.get_instance.side_effect = get_instance_side_effect
        registry.get_runtime_element.side_effect = get_runtime_element_side_effect
        return registry, mock_nodes
    
    def test_all_nodes_receive_step_context(self, mock_session_registry, mock_element_registry):
        """Test that all nodes receive StepContext with topology."""
        registry, mock_nodes = mock_session_registry
        
        node1 = Step(uid="node1", category=ResourceCategory.NODE, rid="node1_rid", type_key="node1", writes={"data"})
        node2 = Step(uid="node2", category=ResourceCategory.NODE, rid="node2_rid", type_key="node2", reads={"data"}, writes={"processed"}, after=["node1"])
        finalizer = Step(uid="finalizer", category=ResourceCategory.NODE, rid="finalizer_rid", type_key="finalizer", reads={"processed"}, writes={"output"}, after=["node2"])
        
        logical_plan = GraphPlan()
        for step in [node1, node2, finalizer]:
            logical_plan.add_step(step)
        
        rt_plan = RTGraphPlan(logical_plan, registry, mock_element_registry)
        
        # All nodes should have received set_context calls
        for rid, mock_node in mock_nodes.items():
            mock_node.set_context.assert_called_once()
            
            context = mock_node.set_context.call_args[0][0]
            assert isinstance(context, StepContext)
            assert isinstance(context.topology, StepTopology)
    
    def test_step_context_contains_correct_topology(self, mock_session_registry, mock_element_registry):
        """Test that each node's StepContext contains correct topology for that node."""
        registry, mock_nodes = mock_session_registry
        
        # Create chain where each node has different topology
        node1 = Step(uid="node1", category=ResourceCategory.NODE, rid="node1_rid", type_key="node1", writes={"data1"})
        node2 = Step(uid="node2", category=ResourceCategory.NODE, rid="node2_rid", type_key="node2", reads={"data1"}, writes={"data2"}, after=["node1"])
        finalizer = Step(uid="finalizer", category=ResourceCategory.NODE, rid="finalizer_rid", type_key="finalizer", reads={"data2"}, writes={"output"}, after=["node2"])
        
        logical_plan = GraphPlan()
        for step in [node1, node2, finalizer]:
            logical_plan.add_step(step)
        
        rt_plan = RTGraphPlan(logical_plan, registry, mock_element_registry)
        
        # Check node1's context
        node1_context = mock_nodes["node1_rid"].set_context.call_args[0][0]
        assert node1_context.uid == "node1"
        assert node1_context.topology.has_finalizer_path()
        assert node1_context.topology.get_distance_to_finalizer("node2") == 2  # node2 -> finalizer + 1
        
        # Check node2's context
        node2_context = mock_nodes["node2_rid"].set_context.call_args[0][0]
        assert node2_context.uid == "node2"
        assert node2_context.topology.has_finalizer_path()
        assert node2_context.topology.get_distance_to_finalizer("finalizer") == 1  # Direct to finalizer
        
        # Check finalizer's context
        finalizer_context = mock_nodes["finalizer_rid"].set_context.call_args[0][0]
        assert finalizer_context.uid == "finalizer"
        assert not finalizer_context.topology.has_finalizer_path()  # No adjacent nodes
    
    def test_step_context_includes_adjacent_nodes(self, mock_session_registry, mock_element_registry):
        """Test that StepContext includes both adjacent nodes and topology."""
        registry, mock_nodes = mock_session_registry
        
        orchestrator = Step(uid="orchestrator", category=ResourceCategory.NODE, rid="orchestrator_rid", type_key="orchestrator", writes={"messages"})
        agent1 = Step(uid="agent1", category=ResourceCategory.NODE, rid="agent1_rid", type_key="agent", reads={"messages"}, writes={"output"}, after=["orchestrator"])
        agent2 = Step(uid="agent2", category=ResourceCategory.NODE, rid="agent2_rid", type_key="agent", reads={"messages"}, writes={"output"}, after=["orchestrator"])
        
        # Add mocks for agents
        mock_nodes["agent1_rid"] = Mock()
        mock_nodes["agent1_rid"].set_context = Mock()
        mock_nodes["agent2_rid"] = Mock()
        mock_nodes["agent2_rid"].set_context = Mock()
        
        logical_plan = GraphPlan()
        for step in [orchestrator, agent1, agent2]:
            logical_plan.add_step(step)
        
        rt_plan = RTGraphPlan(logical_plan, registry, mock_element_registry)
        
        # Check orchestrator's context
        context = mock_nodes["orchestrator_rid"].set_context.call_args[0][0]
        
        # Should have adjacent nodes
        assert len(context.adjacent_nodes) == 2
        assert "agent1" in context.adjacent_nodes
        assert "agent2" in context.adjacent_nodes
        
        # Should have topology for those adjacent nodes
        assert context.topology.has_finalizer_path()
        assert context.topology.get_distance_to_finalizer("agent1") == 1
        assert context.topology.get_distance_to_finalizer("agent2") == 1
        assert set(context.topology.get_finalizer_reachable_nodes()) == {"agent1", "agent2"}
    
    def test_nodes_without_set_context_method(self, mock_session_registry, mock_element_registry):
        """Test that nodes without set_context method don't cause errors."""
        registry, mock_nodes = mock_session_registry
        
        # Create a mock node without set_context method
        node_without_context = Mock()
        del node_without_context.set_context  # Remove the method
        mock_nodes["node1_rid"] = node_without_context
        
        node1 = Step(uid="node1", category=ResourceCategory.NODE, rid="node1_rid", type_key="node1", writes={"output"})
        
        logical_plan = GraphPlan()
        logical_plan.add_step(node1)
        
        # Should not raise an error
        rt_plan = RTGraphPlan(logical_plan, registry, mock_element_registry)
        
        # Verify the node was still retrieved
        registry.get_instance.assert_called_with(ResourceCategory.NODE, "node1_rid")


class TestRTGraphPlanCoreFeatures:
    """Test that RTGraphPlan core features work with new topology system."""

    def test_existing_functionality_with_topology(self, mock_element_registry):
        """Test that existing RTGraphPlan functionality works with new topology."""
        registry = Mock(spec=SessionRegistry)
        registry._store = {cat: {} for cat in ResourceCategory}
        mock_node = Mock()
        registry.get_instance.return_value = mock_node
        
        step = Step(
            uid="test_step",
            category=ResourceCategory.NODE,
            rid="test_rid",
            type_key="test",
            writes={"output"}
        )
        
        logical_plan = GraphPlan()
        logical_plan.add_step(step)
        
        rt_plan = RTGraphPlan(logical_plan, registry, mock_element_registry)
        
        # Existing methods should still work
        assert len(rt_plan.steps) == 1
        assert rt_plan.get_step("test_step") is not None
        assert len(rt_plan.get_roots()) == 1
        assert len(rt_plan.get_leaves()) == 1
        
        # Should be iterable
        steps = list(rt_plan)
        assert len(steps) == 1
        
        # Should have length
        assert len(rt_plan) == 1
    
    def test_step_context_with_new_topology(self, mock_element_registry):
        """Test that StepContext works correctly with new topology composition."""
        registry = Mock(spec=SessionRegistry)
        registry._store = {cat: {} for cat in ResourceCategory}
        mock_node = Mock()
        mock_node.set_context = Mock()
        registry.get_instance.return_value = mock_node
        
        step = Step(
            uid="test_step",
            category=ResourceCategory.NODE,
            rid="test_rid",
            type_key="test",
            writes={"output"}
        )
        
        logical_plan = GraphPlan()
        logical_plan.add_step(step)
        
        rt_plan = RTGraphPlan(logical_plan, registry, mock_element_registry)
        
        # Get the context that was passed to the node
        context = mock_node.set_context.call_args[0][0]
        
        # All StepContext fields should be present
        assert hasattr(context, 'uid')
        assert hasattr(context, 'metadata')
        assert hasattr(context, 'adjacent_nodes')
        assert hasattr(context, 'branches')
        
        # Topology field with composition should be present
        assert hasattr(context, 'topology')
        assert isinstance(context.topology, StepTopology)
        
        # Should be able to access composed FinalizerPathInfo if present
        if context.topology.finalizer_paths:
            assert isinstance(context.topology.finalizer_paths, FinalizerPathInfo)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
