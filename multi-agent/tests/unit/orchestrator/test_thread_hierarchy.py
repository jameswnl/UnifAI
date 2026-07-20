"""
Unit tests for thread hierarchy and parent/child relationships.

Tests thread management:
- Thread creation (root vs child)
- Parent-child relationships
- Hierarchy traversal
- Response routing through hierarchy
- Multi-level hierarchies
- Edge cases (max depth, cycles, orphans)

✅ GENERIC: Uses shared helpers and fixtures
✅ SOLID: Single responsibility per test
"""

import pytest
from unittest.mock import Mock
from mas.elements.nodes.orchestrator.orchestrator_node import OrchestratorNode
from mas.elements.nodes.common.workload import Thread, WorkItemStatus, Task, WorkItemResult
from mas.elements.nodes.common.workload.models.workplan_models import DelegationExchange
from tests.base import (
    BaseUnitTest,
    setup_node_with_state,
    setup_node_with_context,
    create_thread_hierarchy,
    create_multi_level_hierarchy,
    assert_thread_hierarchy,
    assert_response_routes_to_root,
    get_hierarchy_depth,
    create_work_plan_with_items,
    simulate_worker_response
)


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.threads
class TestThreadCreation(BaseUnitTest):
    """Test thread creation basics."""
    
    def test_create_root_thread(self, mock_llm_provider):
        """✅ SIMPLE: Test creating root thread."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        thread_service = orch.get_workload_service().get_thread_service()
        
        # Create root thread
        root = thread_service.create_root_thread(
            title="Root Thread",
            objective="Test objective",
            initiator="orch1"
        )
        
        # Should have no parent
        assert root.parent_thread_id is None
        assert len(root.child_thread_ids) == 0
        assert root.thread_id is not None
    
    def test_create_child_thread(self, mock_llm_provider):
        """✅ SIMPLE: Test creating child thread."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        thread_service = orch.get_workload_service().get_thread_service()
        
        # Create parent
        parent = thread_service.create_root_thread(
            title="Parent",
            objective="Parent objective",
            initiator="orch1"
        )
        
        # Create child
        child = thread_service.create_child_thread(
            parent=parent,
            title="Child",
            objective="Child objective",
            initiator="orch1"
        )
        
        # ✅ GENERIC: Use assertion helper
        assert_thread_hierarchy(parent, child)
    
    def test_create_multiple_children(self, mock_llm_provider):
        """✅ MEDIUM: Test parent with multiple children."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        # ✅ GENERIC: Use hierarchy helper
        hierarchy = create_thread_hierarchy(orch, "parent_1", num_children=3)
        
        parent = hierarchy["parent"]
        children = hierarchy["children"]
        
        # Parent should have 3 children
        assert len(parent.child_thread_ids) == 3
        assert len(children) == 3
        
        # Each child should reference parent
        for child in children:
            assert child.parent_thread_id == parent.thread_id


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.threads
class TestThreadHierarchyTraversal(BaseUnitTest):
    """Test thread hierarchy navigation."""
    
    def test_find_root_from_child(self, mock_llm_provider):
        """✅ SIMPLE: Test finding root from child thread."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        thread_service = orch.get_workload_service().get_thread_service()
        
        # Create hierarchy
        hierarchy = create_thread_hierarchy(orch, "parent_1", num_children=1)
        parent = hierarchy["parent"]
        child = hierarchy["children"][0]
        
        # Find root from child
        root_id = thread_service.find_root_thread(child.thread_id)
        
        assert root_id == parent.thread_id
    
    def test_find_root_from_grandchild(self, mock_llm_provider):
        """✅ MEDIUM: Test finding root from grandchild thread."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        # ✅ GENERIC: Use multi-level helper
        threads = create_multi_level_hierarchy(orch, levels=3)
        root = threads[0]
        grandchild = threads[2]
        
        thread_service = orch.get_workload_service().get_thread_service()
        
        # Find root from grandchild
        root_id = thread_service.find_root_thread(grandchild.thread_id)
        
        assert root_id == root.thread_id
    
    def test_find_root_when_already_root(self, mock_llm_provider):
        """✅ SIMPLE: Test finding root when already at root."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        thread_service = orch.get_workload_service().get_thread_service()
        
        # Create root
        root = thread_service.create_root_thread(
            title="Root",
            objective="Root objective",
            initiator="orch1"
        )
        
        # Should return self
        root_id = thread_service.find_root_thread(root.thread_id)
        
        assert root_id == root.thread_id
    
    def test_get_hierarchy_path(self, mock_llm_provider):
        """✅ MEDIUM: Test getting hierarchy path from root to leaf."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        thread_service = orch.get_workload_service().get_thread_service()
        
        # Create 4-level hierarchy
        threads = create_multi_level_hierarchy(orch, levels=4)
        leaf = threads[-1]
        
        # Get path
        path = thread_service.get_hierarchy_path(leaf.thread_id)
        
        # Should have 4 levels
        assert len(path) == 4
        
        # Should match created threads
        for i, thread in enumerate(threads):
            assert path[i] == thread.thread_id
    
    def test_get_child_threads(self, mock_llm_provider):
        """✅ MEDIUM: Test getting direct children of thread."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        thread_service = orch.get_workload_service().get_thread_service()
        
        # Create hierarchy with 3 children
        hierarchy = create_thread_hierarchy(orch, "parent_1", num_children=3)
        parent = hierarchy["parent"]
        
        # Get children
        children = thread_service.get_child_threads(parent.thread_id)
        
        # Should have 3 children
        assert len(children) == 3
        
        # All should be Thread objects with correct parent
        for child in children:
            assert isinstance(child, Thread)
            assert child.parent_thread_id == parent.thread_id


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.threads
class TestResponseRouting(BaseUnitTest):
    """Test response routing through thread hierarchy."""
    
    def test_response_from_child_routes_to_parent(self, mock_llm_provider):
        """✅ MEDIUM: Test response from child routes to parent thread."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", ["worker1"])
        
        # Create hierarchy
        hierarchy = create_thread_hierarchy(orch, "parent_1", num_children=1)
        parent = hierarchy["parent"]
        child = hierarchy["children"][0]
        
        # Create work plan in parent thread (this is where orch1's work plan would be)
        workspace_service = orch.get_workload_service().get_workspace_service()
        plan = workspace_service.create_work_plan(parent.thread_id, "orch1", "Parent plan")
        workspace_service.save_work_plan(plan)
        
        # ✅ GENERIC: Use assertion helper
        assert_response_routes_to_root(orch, child.thread_id, parent.thread_id)
    
    def test_response_from_grandchild_routes_to_root(self, mock_llm_provider):
        """✅ MEDIUM: Test response from grandchild routes to root."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", ["worker1"])
        
        # Create 3-level hierarchy
        threads = create_multi_level_hierarchy(orch, levels=3)
        root = threads[0]
        grandchild = threads[2]
        
        # Create work plan in root thread (this is where orch1's work plan would be)
        workspace_service = orch.get_workload_service().get_workspace_service()
        plan = workspace_service.create_work_plan(root.thread_id, "orch1", "Root plan")
        workspace_service.save_work_plan(plan)
        
        # ✅ GENERIC: Use assertion helper
        assert_response_routes_to_root(orch, grandchild.thread_id, root.thread_id)
    
    def test_work_plan_owner_walks_hierarchy(self, mock_llm_provider):
        """✅ MEDIUM: Test work plan owner search walks up hierarchy to find owner's plan."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        thread_service = orch.get_workload_service().get_thread_service()
        workspace_service = orch.get_workload_service().get_workspace_service()
        
        # Create 3-level hierarchy
        threads = create_multi_level_hierarchy(orch, levels=3)
        root, child, grandchild = threads
        
        # Create work plan in root thread for orch1
        plan = workspace_service.create_work_plan(root.thread_id, "orch1", "Root plan")
        workspace_service.save_work_plan(plan)
        
        # Check work plan owner search from different levels
        # All should route to root (where orch1's work plan is)
        for thread in threads:
            owner = thread_service.find_work_plan_owner(thread.thread_id, "orch1")
            assert owner == root.thread_id, \
                f"Work plan owner for {thread.thread_id} should be root {root.thread_id}, got {owner}"
        
        # Test with non-existent owner - should return None
        no_owner = thread_service.find_work_plan_owner(grandchild.thread_id, "nonexistent")
        assert no_owner is None, f"Should return None for non-existent owner, got {no_owner}"
    
    def test_response_updates_parent_work_plan(self, mock_llm_provider):
        """✅ COMPLEX: Test response from child updates parent's work plan."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", ["worker1"])

        # Create hierarchy
        hierarchy = create_thread_hierarchy(orch, "parent_1", num_children=1)
        parent = hierarchy["parent"]
        child = hierarchy["children"][0]

        # Create work plan in PARENT thread
        plan = create_work_plan_with_items(
            parent.thread_id, "orch1",
            num_remote=1,
            remote_workers=["worker1"]
        )

        service = orch.get_workload_service()
        workspace_service = service.get_workspace_service()

        # Set up delegation exchange (correlation now lives in DelegationExchange.task_id)
        item = list(plan.items.values())[0]
        item.status = WorkItemStatus.IN_PROGRESS
        item.result = WorkItemResult(delegations=[
            DelegationExchange(sequence=0, task_id="corr_123",
                               query="Do work", delegated_to="worker1")
        ])
        workspace_service.save_work_plan(plan)

        # Response comes from CHILD thread (simulating nested orchestration)
        response = Task(
            content="Work failed",
            created_by="worker1",
            correlation_task_id="corr_123",
            thread_id=child.thread_id,  # Response from child thread!
            error="Work failed"  # Error is now a string
        )

        # Handle response (should route to parent)
        result_thread = orch._handle_task_response(response)

        # Should route to parent thread
        assert result_thread == parent.thread_id

        # Verify parent work plan's delegation exchange was filled
        updated_plan = workspace_service.load_work_plan(parent.thread_id, "orch1")
        updated_item = list(updated_plan.items.values())[0]
        # Response is stored in the exchange -- status stays IN_PROGRESS (LLM interprets)
        assert updated_item.result.delegations[0].response_content is not None


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.threads
class TestThreadHierarchyEdgeCases(BaseUnitTest):
    """Test thread hierarchy edge cases."""
    
    def test_deep_hierarchy_max_depth_protection(self, mock_llm_provider):
        """✅ COMPLEX: Test max depth protection in hierarchy traversal."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        thread_service = orch.get_workload_service().get_thread_service()
        
        # Create deep hierarchy (10 levels - well within max)
        threads = create_multi_level_hierarchy(orch, levels=10)
        root = threads[0]
        deep_child = threads[-1]
        
        # Should still find root
        found_root = thread_service.find_root_thread(deep_child.thread_id)
        assert found_root == root.thread_id
        
        # Path should have all 10 levels
        path = thread_service.get_hierarchy_path(deep_child.thread_id)
        assert len(path) == 10
    
    def test_hierarchy_depth_calculation(self, mock_llm_provider):
        """✅ MEDIUM: Test calculating thread depth in hierarchy."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        thread_service = orch.get_workload_service().get_thread_service()
        
        # Create 4-level hierarchy
        threads = create_multi_level_hierarchy(orch, levels=4)
        
        # ✅ GENERIC: Use depth helper
        assert get_hierarchy_depth(thread_service, threads[0].thread_id) == 0  # Root
        assert get_hierarchy_depth(thread_service, threads[1].thread_id) == 1  # Child
        assert get_hierarchy_depth(thread_service, threads[2].thread_id) == 2  # Grandchild
        assert get_hierarchy_depth(thread_service, threads[3].thread_id) == 3  # Great-grandchild
    
    def test_orphaned_thread_without_parent(self, mock_llm_provider):
        """✅ MEDIUM: Test thread with non-existent parent."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        thread_service = orch.get_workload_service().get_thread_service()
        
        # Create thread
        orphan = thread_service.create_root_thread(
            title="Orphan",
            objective="Orphan objective",
            initiator="orch1"
        )
        
        # Manually set non-existent parent (simulate orphan)
        orphan.parent_thread_id = "nonexistent_parent"
        thread_service.save_thread(orphan)
        
        # Try to find root - should handle gracefully
        root_id = thread_service.find_root_thread(orphan.thread_id)
        
        # Should return something (behavior depends on implementation)
        assert root_id is not None
    
    def test_thread_hierarchy_persistence(self, mock_llm_provider):
        """✅ MEDIUM: Test thread hierarchy persists across saves."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        thread_service = orch.get_workload_service().get_thread_service()
        
        # Create hierarchy
        hierarchy = create_thread_hierarchy(orch, "parent_1", num_children=2)
        parent = hierarchy["parent"]
        children = hierarchy["children"]
        
        # Reload parent
        reloaded_parent = thread_service.get_thread(parent.thread_id)
        
        # Should still have children
        assert len(reloaded_parent.child_thread_ids) == 2
        
        # Children should still have parent
        for child_id in reloaded_parent.child_thread_ids:
            reloaded_child = thread_service.get_thread(child_id)
            assert reloaded_child.parent_thread_id == reloaded_parent.thread_id
    
    def test_multiple_root_threads_independent(self, mock_llm_provider):
        """✅ MEDIUM: Test multiple independent root threads."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        thread_service = orch.get_workload_service().get_thread_service()
        
        # Create two independent hierarchies
        hierarchy1 = create_thread_hierarchy(orch, "root_1", num_children=2)
        hierarchy2 = create_thread_hierarchy(orch, "root_2", num_children=2)
        
        root1 = hierarchy1["parent"]
        root2 = hierarchy2["parent"]
        
        # Roots should be different
        assert root1.thread_id != root2.thread_id
        
        # Each root should only have its own children
        assert len(root1.child_thread_ids) == 2
        assert len(root2.child_thread_ids) == 2
        
        # No cross-contamination
        for child_id in root1.child_thread_ids:
            assert child_id not in root2.child_thread_ids
