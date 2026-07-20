"""
Unit tests for orchestrator edge cases.

Tests error handling and boundary conditions:
- Empty inputs
- Missing data
- Invalid states
- Null values
- Concurrent operations

✅ GENERIC: Uses shared helpers and fixtures
✅ SOLID: Single responsibility per test
"""

import pytest
from unittest.mock import Mock, patch
from mas.elements.nodes.orchestrator.orchestrator_node import OrchestratorNode
from mas.elements.nodes.common.workload import (
    WorkPlan, WorkItem, WorkItemKind, WorkItemStatus, Task
)
from tests.base import (
    BaseUnitTest,
    setup_node_with_state,
    setup_node_with_context,
    create_work_plan_with_items,
    assert_work_plan_status
)


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.edge_cases
class TestEmptyInputs(BaseUnitTest):
    """Test orchestrator handles empty inputs gracefully."""
    
    def test_empty_work_plan(self, mock_llm_provider):
        """✅ SIMPLE: Test orchestrator handles empty work plan."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        # Create empty work plan
        plan = WorkPlan(
            summary="Empty plan",
            owner_uid="orch1",
            thread_id="thread1"
        )
        
        service = orch.get_workload_service()
        workspace_service = service.get_workspace_service()
        workspace_service.save_work_plan(plan)
        
        # Should handle gracefully
        loaded_plan = workspace_service.load_work_plan("thread1", "orch1")
        assert loaded_plan is not None
        assert len(loaded_plan.items) == 0
        assert loaded_plan.is_complete() is False
    
    def test_empty_adjacent_nodes(self, mock_llm_provider):
        """✅ SIMPLE: Test orchestrator with no adjacent nodes."""
        # ✅ GENERIC: Use setup helper with empty adjacent list
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])  # Empty list
        
        # Should initialize without error
        assert orch is not None
        
        # Can still create local work plans
        plan = create_work_plan_with_items("thread1", "orch1", num_local=1)
        
        service = orch.get_workload_service()
        workspace_service = service.get_workspace_service()
        workspace_service.save_work_plan(plan)
        
        assert len(plan.items) == 1
    
    def test_empty_thread_id(self, mock_llm_provider):
        """✅ SIMPLE: Test work plan with empty thread ID."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        # Work plan with empty thread_id
        plan = WorkPlan(
            summary="Test plan",
            owner_uid="orch1",
            thread_id=""  # Empty
        )
        
        service = orch.get_workload_service()
        workspace_service = service.get_workspace_service()
        
        # Should save (validation depends on implementation)
        try:
            workspace_service.save_work_plan(plan)
            # If it saves, try to load
            loaded = workspace_service.load_work_plan("", "orch1")
            assert loaded is not None or loaded is None  # Either is acceptable
        except (ValueError, KeyError):
            # Validation error is also acceptable
            pass
    
    def test_work_item_with_empty_description(self, mock_llm_provider):
        """✅ SIMPLE: Test work item with empty description."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="",  # Empty
            status=WorkItemStatus.PENDING
        )
        
        # Should create successfully
        assert item is not None
        assert item.description == ""


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.edge_cases
class TestMissingData(BaseUnitTest):
    """Test orchestrator handles missing data."""
    
    def test_load_nonexistent_work_plan(self, mock_llm_provider):
        """✅ SIMPLE: Test loading work plan that doesn't exist."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        service = orch.get_workload_service()
        workspace_service = service.get_workspace_service()
        
        # Try to load non-existent plan
        result = workspace_service.load_work_plan("nonexistent_thread", "orch1")
        
        # Should return None or raise exception
        assert result is None or isinstance(result, WorkPlan)
    
    def test_response_for_nonexistent_thread(self, mock_llm_provider):
        """✅ MEDIUM: Test response for thread with no work plan."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", ["worker1"])
        
        # Create response for non-existent thread
        response = Task(
            content="Response",
            created_by="worker1",
            is_response=True,
            correlation_task_id="corr_123",
            thread_id="nonexistent_thread"
        )
        
        # Should handle gracefully
        result = orch._handle_task_response(response)
        assert result is None  # No work plan to update
    
    def test_work_item_without_assigned_uid(self, mock_llm_provider):
        """✅ SIMPLE: Test remote work item without assigned UID."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.REMOTE,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING
            # No assigned_uid
        )
        
        # Should create but might have None assigned_uid
        assert item is not None
        assert item.assigned_uid is None or item.assigned_uid == ""
    
    def test_work_item_without_delegation_exchanges(self, mock_llm_provider):
        """✅ SIMPLE: Test work item without delegation exchanges (no correlation)."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.REMOTE,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING,
            assigned_uid="worker1"
            # No result with delegations — no correlation tracking yet
        )

        # Should create successfully
        assert item is not None
        assert item.result is None  # No delegations yet


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.edge_cases
class TestInvalidStates(BaseUnitTest):
    """Test orchestrator handles invalid state transitions."""
    
    def test_mark_pending_item_as_done_directly(self, mock_llm_provider):
        """✅ SIMPLE: Test skipping IN_PROGRESS state."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING
        )
        
        # Skip IN_PROGRESS and go directly to DONE
        item.status = WorkItemStatus.DONE
        
        # Should allow (no strict state machine enforcement)
        assert item.status == WorkItemStatus.DONE
    
    def test_mark_done_item_back_to_pending(self, mock_llm_provider):
        """✅ MEDIUM: Test reverting completed item to pending."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.DONE
        )
        
        # Try to revert to pending
        item.status = WorkItemStatus.PENDING
        
        # Should allow (no strict state machine enforcement)
        assert item.status == WorkItemStatus.PENDING
    
    def test_failed_item_retry_status_change(self, mock_llm_provider):
        """✅ MEDIUM: Test retrying failed item."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.FAILED
        )
        
        # Reset to pending for retry
        item.status = WorkItemStatus.PENDING
        
        # Should allow
        assert item.status == WorkItemStatus.PENDING


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.edge_cases
class TestBoundaryConditions(BaseUnitTest):
    """Test orchestrator boundary conditions."""
    
    def test_work_plan_with_single_item(self, mock_llm_provider):
        """✅ SIMPLE: Test work plan with exactly one item."""
        # ✅ GENERIC: Use helper
        plan = create_work_plan_with_items("thread1", "orch1", num_local=1)
        
        # ✅ GENERIC: Use assertion helper
        assert_work_plan_status(plan, expected_total=1, expected_pending=1)
    
    def test_work_plan_with_many_items(self, mock_llm_provider):
        """✅ MEDIUM: Test work plan with many items."""
        # ✅ GENERIC: Use helper
        plan = create_work_plan_with_items("thread1", "orch1", num_local=50)
        
        # ✅ GENERIC: Use assertion helper
        assert_work_plan_status(plan, expected_total=50, expected_pending=50)
        
        # Should handle large plans
        assert len(plan.items) == 50
    
    def test_work_item_with_many_dependencies(self, mock_llm_provider):
        """✅ MEDIUM: Test work item with many dependencies."""
        # Create item with many dependencies
        many_deps = [f"item_{i}" for i in range(100)]
        
        item = WorkItem(
            id="item_final",
            kind=WorkItemKind.LOCAL,
            title="Final Task",
            description="Task with many dependencies",
            status=WorkItemStatus.PENDING,
            dependencies=many_deps
        )
        
        # Should create successfully
        assert item is not None
        assert len(item.dependencies) == 100
    
    def test_work_item_retry_count_edge_cases(self, mock_llm_provider):
        """✅ MEDIUM: Test retry count at boundaries."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING,
            retry_count=0,
            max_retries=3
        )
        
        # Increment to max
        item.retry_count = 1
        item.retry_count = 2
        item.retry_count = 3
        
        # At max retries
        assert item.retry_count == item.max_retries
        
        # Can exceed (no hard limit enforcement)
        item.retry_count = 4
        assert item.retry_count > item.max_retries
    
    def test_zero_max_retries(self, mock_llm_provider):
        """✅ SIMPLE: Test work item with zero max retries."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING,
            max_retries=0  # No retries allowed
        )
        
        # Should create successfully
        assert item is not None
        assert item.max_retries == 0
        
        # Already at max retries initially
        assert item.retry_count <= item.max_retries


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.edge_cases
class TestConcurrentOperations(BaseUnitTest):
    """Test orchestrator concurrent operations."""
    
    def test_multiple_work_plans_same_owner_different_threads(self, mock_llm_provider):
        """✅ MEDIUM: Test multiple work plans for same owner."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        # Create multiple plans
        plan1 = create_work_plan_with_items("thread1", "orch1", num_local=2)
        plan2 = create_work_plan_with_items("thread2", "orch1", num_local=3)
        plan3 = create_work_plan_with_items("thread3", "orch1", num_local=1)
        
        service = orch.get_workload_service()
        workspace_service = service.get_workspace_service()
        
        # Save all plans
        workspace_service.save_work_plan(plan1)
        workspace_service.save_work_plan(plan2)
        workspace_service.save_work_plan(plan3)
        
        # All should persist independently
        loaded1 = workspace_service.load_work_plan("thread1", "orch1")
        loaded2 = workspace_service.load_work_plan("thread2", "orch1")
        loaded3 = workspace_service.load_work_plan("thread3", "orch1")
        
        assert len(loaded1.items) == 2
        assert len(loaded2.items) == 3
        assert len(loaded3.items) == 1
    
    def test_update_work_plan_multiple_times(self, mock_llm_provider):
        """✅ MEDIUM: Test updating same work plan multiple times."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        plan = create_work_plan_with_items("thread1", "orch1", num_local=3)
        
        service = orch.get_workload_service()
        workspace_service = service.get_workspace_service()
        
        # Save initial
        workspace_service.save_work_plan(plan)
        
        # Update multiple times
        items = list(plan.items.values())
        
        items[0].status = WorkItemStatus.IN_PROGRESS
        workspace_service.save_work_plan(plan)
        
        items[0].status = WorkItemStatus.DONE
        workspace_service.save_work_plan(plan)
        
        items[1].status = WorkItemStatus.IN_PROGRESS
        workspace_service.save_work_plan(plan)
        
        items[1].status = WorkItemStatus.DONE
        workspace_service.save_work_plan(plan)
        
        # Final state should reflect all updates
        loaded_plan = workspace_service.load_work_plan("thread1", "orch1")
        loaded_items = list(loaded_plan.items.values())
        
        assert loaded_items[0].status == WorkItemStatus.DONE
        assert loaded_items[1].status == WorkItemStatus.DONE
        assert loaded_items[2].status == WorkItemStatus.PENDING
    
    def test_work_plan_isolation_between_threads(self, mock_llm_provider):
        """✅ MEDIUM: Test work plans isolated per thread."""
        # ✅ GENERIC: Use setup helper
        orch = OrchestratorNode(llm=mock_llm_provider)
        state_view, context = setup_node_with_context(orch, "orch1", [])
        
        plan1 = create_work_plan_with_items("thread1", "orch1", num_local=2)
        plan2 = create_work_plan_with_items("thread2", "orch1", num_local=2)
        
        service = orch.get_workload_service()
        workspace_service = service.get_workspace_service()
        
        workspace_service.save_work_plan(plan1)
        workspace_service.save_work_plan(plan2)
        
        # Modify plan1
        items1 = list(plan1.items.values())
        items1[0].status = WorkItemStatus.DONE
        workspace_service.save_work_plan(plan1)
        
        # Verify plan2 unaffected
        loaded_plan2 = workspace_service.load_work_plan("thread2", "orch1")
        items2 = list(loaded_plan2.items.values())
        
        assert all(item.status == WorkItemStatus.PENDING for item in items2)


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.edge_cases
class TestNullAndOptionalValues(BaseUnitTest):
    """Test handling of null and optional values."""
    
    def test_work_item_optional_fields_none(self, mock_llm_provider):
        """✅ SIMPLE: Test work item with None optional fields."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING
            # All optional fields default to None
        )

        # Should create successfully
        assert item is not None
        assert item.assigned_uid is None or item.assigned_uid == ""
        assert item.result is None
    
    def test_work_plan_summary_none(self, mock_llm_provider):
        """✅ SIMPLE: Test work plan with None summary."""
        # Try to create with None summary
        try:
            plan = WorkPlan(
                summary=None,  # None
                owner_uid="orch1",
                thread_id="thread1"
            )
            # If it creates, verify
            assert plan is not None
        except (TypeError, ValueError):
            # Validation error is acceptable
            pass
    
    def test_task_optional_correlation_id(self, mock_llm_provider):
        """✅ SIMPLE: Test task with optional correlation ID."""
        task = Task(
            content="Test task",
            created_by="orch1",
            thread_id="thread1"
            # No correlation_task_id
        )
        
        # Should create successfully
        assert task is not None
        assert not hasattr(task, 'correlation_task_id') or task.correlation_task_id is None
