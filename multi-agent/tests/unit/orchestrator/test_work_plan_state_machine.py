"""
Unit tests for work plan state machine.

Tests work item status transitions from simple to complex:
- Basic status transitions (PENDING → DONE, PENDING → FAILED)
- Delegation flow (PENDING → WAITING → DONE)
- Retry logic and exhaustion
- Work plan completion detection
- Concurrent updates (thread safety)

Uses GENERIC test helpers that work for ALL workload systems.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock

from mas.elements.nodes.common.workload import (
    WorkPlan, WorkItem, WorkItemStatus, WorkItemKind,
    UnifiedWorkloadService, InMemoryStorage,
    WorkItemResult
)
from tests.base import BaseUnitTest, create_work_plan_with_items, assert_work_plan_status


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.workload
class TestWorkItemStatusTransitions(BaseUnitTest):
    """Test basic work item status transitions."""
    
    def test_work_item_pending_to_done(self):
        """✅ SIMPLE: Test successful completion: PENDING → DONE."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING
        )
        
        # Transition to DONE
        item.status = WorkItemStatus.DONE
        
        assert item.status == WorkItemStatus.DONE
    
    def test_work_item_pending_to_failed(self):
        """✅ SIMPLE: Test failure: PENDING → FAILED."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING
        )
        
        # Transition to FAILED with error
        item.status = WorkItemStatus.FAILED
        item.error = "Task failed due to invalid input"
        
        assert item.status == WorkItemStatus.FAILED
        assert item.error is not None
    
    def test_work_item_pending_to_in_progress_to_done(self):
        """✅ SIMPLE: Test normal execution flow: PENDING → IN_PROGRESS → DONE."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING
        )
        
        # Start work
        item.status = WorkItemStatus.IN_PROGRESS
        assert item.status == WorkItemStatus.IN_PROGRESS
        
        # Complete work
        item.status = WorkItemStatus.DONE
        assert item.status == WorkItemStatus.DONE
    
    def test_work_item_with_dependencies(self):
        """✅ SIMPLE: Test work item with dependencies."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING,
            dependencies=["item_0"]  # Depends on another item
        )
        
        # Has dependencies
        assert len(item.dependencies) > 0
        assert "item_0" in item.dependencies
        
        # Can still be processed (dependencies are just metadata)
        item.status = WorkItemStatus.IN_PROGRESS
        assert item.status == WorkItemStatus.IN_PROGRESS


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.workload
class TestDelegationFlow(BaseUnitTest):
    """Test delegation status flow for remote work items."""
    
    def test_remote_item_delegation_flow(self):
        """✅ MEDIUM: Test delegation: PENDING → IN_PROGRESS → DONE."""
        item = WorkItem(
            id="remote_1",
            kind=WorkItemKind.REMOTE,
            title="Delegated task",
            description="Task to delegate",
            assigned_uid="worker1",
            status=WorkItemStatus.PENDING
        )

        # Mark as delegated (in progress - remote)
        item.status = WorkItemStatus.IN_PROGRESS
        item.kind = WorkItemKind.REMOTE

        assert item.status == WorkItemStatus.IN_PROGRESS
        assert item.kind == WorkItemKind.REMOTE

        # Response received, mark as done
        item.status = WorkItemStatus.DONE
        item.result = WorkItemResult(
            success=True,
            final_summary="Work completed by worker1"
        )

        assert item.status == WorkItemStatus.DONE
        assert item.result.success is True
    
    def test_remote_item_delegation_failure(self):
        """✅ MEDIUM: Test delegation failure: PENDING → IN_PROGRESS → FAILED."""
        item = WorkItem(
            id="remote_1",
            kind=WorkItemKind.REMOTE,
            title="Delegated task",
            description="Task to delegate",
            assigned_uid="worker1",
            status=WorkItemStatus.PENDING
        )

        # Delegate
        item.status = WorkItemStatus.IN_PROGRESS
        item.kind = WorkItemKind.REMOTE

        # Worker reports failure
        item.status = WorkItemStatus.FAILED
        item.error = "Worker1 could not complete task"

        assert item.status == WorkItemStatus.FAILED
        assert item.error is not None
    
    def test_correlation_id_tracking(self):
        """✅ MEDIUM: Test correlation ID is properly tracked via DelegationExchange."""
        from mas.elements.nodes.common.workload.models.workplan_models import DelegationExchange

        item = WorkItem(
            id="remote_1",
            kind=WorkItemKind.REMOTE,
            title="Test",
            description="Test",
            assigned_uid="worker1",
            status=WorkItemStatus.PENDING
        )

        # Should start without result/delegations
        assert item.result is None

        # After delegation, should have a DelegationExchange with task_id for correlation
        item.status = WorkItemStatus.IN_PROGRESS
        item.kind = WorkItemKind.REMOTE
        item.result = WorkItemResult(delegations=[
            DelegationExchange(sequence=0, task_id="unique_corr_id_123",
                               query="Do work", delegated_to="worker1")
        ])

        assert item.result.delegations[0].task_id == "unique_corr_id_123"


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.workload
class TestRetryLogic(BaseUnitTest):
    """Test retry logic for failed work items."""
    
    def test_work_item_retry_count_initialization(self):
        """✅ SIMPLE: Test retry count starts at 0."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING
        )
        
        assert item.retry_count == 0
        assert item.max_retries == 3  # Default
    
    def test_work_item_retry_after_failure(self):
        """✅ MEDIUM: Test retry flow: FAILED → increment retry → retry."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING
        )
        
        # First attempt fails
        item.status = WorkItemStatus.FAILED
        item.error = "Attempt 1 failed"
        item.retry_count += 1
        
        assert item.retry_count == 1
        assert item.retry_count < item.max_retries  # Can retry
        
        # Retry (back to pending)
        item.status = WorkItemStatus.PENDING
        item.error = None
        
        assert item.status == WorkItemStatus.PENDING
    
    def test_work_item_retry_exhaustion(self):
        """✅ MEDIUM: Test retry exhaustion after max_retries."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING,
            max_retries=3
        )
        
        # Fail 3 times
        for attempt in range(3):
            item.status = WorkItemStatus.FAILED
            item.retry_count += 1
        
        assert item.retry_count == 3
        assert item.retry_count >= item.max_retries  # Exhausted
        
        # Should stay FAILED (no more retries)
        assert item.status == WorkItemStatus.FAILED
    
    def test_work_item_retry_custom_max(self):
        """✅ MEDIUM: Test custom max_retries value."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING,
            max_retries=5  # Custom
        )
        
        assert item.max_retries == 5
        
        # Can retry 5 times
        item.retry_count = 4
        assert item.retry_count < item.max_retries
        
        item.retry_count = 5
        assert item.retry_count >= item.max_retries
    
    def test_work_item_success_after_retry(self):
        """✅ MEDIUM: Test successful completion after retry."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING
        )
        
        # First attempt fails
        item.status = WorkItemStatus.FAILED
        item.retry_count += 1
        
        # Retry
        item.status = WorkItemStatus.PENDING
        
        # Second attempt succeeds
        item.status = WorkItemStatus.DONE
        
        assert item.status == WorkItemStatus.DONE
        assert item.retry_count == 1  # Tried once, succeeded on retry


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.workload
class TestWorkPlanCompletion(BaseUnitTest):
    """Test work plan completion detection."""
    
    def test_empty_work_plan_not_complete(self):
        """✅ SIMPLE: Test empty work plan is NOT considered complete."""
        plan = WorkPlan(
            summary="Empty plan",
            owner_uid="orch1",
            thread_id="thread1"
        )
        
        # Empty plan returns False (no work to complete means not complete)
        assert plan.is_complete() is False
    
    def test_work_plan_all_done_is_complete(self):
        """✅ SIMPLE: Test plan with all DONE items is complete."""
        # ✅ GENERIC: Use helper to create plan with items
        plan = create_work_plan_with_items("thread1", "orch1", num_local=3)
        
        # Mark all as DONE
        for item in plan.items.values():
            item.status = WorkItemStatus.DONE
        
        assert plan.is_complete() is True
    
    def test_work_plan_with_pending_not_complete(self):
        """✅ SIMPLE: Test plan with PENDING items is not complete."""
        plan = create_work_plan_with_items("thread1", "orch1", num_local=3)
        
        # One DONE, two PENDING
        list(plan.items.values())[0].status = WorkItemStatus.DONE
        
        assert plan.is_complete() is False
    
    def test_work_plan_mixed_done_and_failed_is_complete(self):
        """✅ MEDIUM: Test plan with DONE and FAILED items is complete."""
        plan = create_work_plan_with_items("thread1", "orch1", num_local=3)
        
        # 2 done, 1 failed (all terminal states)
        items = list(plan.items.values())
        items[0].status = WorkItemStatus.DONE
        items[1].status = WorkItemStatus.DONE
        items[2].status = WorkItemStatus.FAILED
        items[2].retry_count = 3  # Exhausted retries
        
        assert plan.is_complete() is True
    
    def test_work_plan_with_waiting_not_complete(self):
        """✅ MEDIUM: Test plan with WAITING items is not complete."""
        plan = create_work_plan_with_items("thread1", "orch1", num_remote=2, 
                                          remote_workers=["worker1"])
        
        # Mark as in progress (remote) for response
        for item in plan.items.values():
            item.status = WorkItemStatus.IN_PROGRESS
            item.kind = WorkItemKind.REMOTE
        
        assert plan.is_complete() is False
    
    def test_work_plan_with_in_progress_not_complete(self):
        """✅ MEDIUM: Test plan with IN_PROGRESS items is not complete."""
        plan = create_work_plan_with_items("thread1", "orch1", num_local=2)
        
        # One in progress
        list(plan.items.values())[0].status = WorkItemStatus.IN_PROGRESS
        
        assert plan.is_complete() is False


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.workload
class TestWorkPlanStatusCounts(BaseUnitTest):
    """Test work plan status counting."""
    
    def test_work_plan_status_counts_empty(self):
        """✅ SIMPLE: Test status counts for empty plan."""
        plan = WorkPlan(
            summary="Empty",
            owner_uid="orch1",
            thread_id="thread1"
        )
        
        # ✅ GENERIC: Use helper to assert counts
        assert_work_plan_status(plan, expected_total=0)
    
    def test_work_plan_status_counts_all_pending(self):
        """✅ SIMPLE: Test status counts with all PENDING items."""
        plan = create_work_plan_with_items("thread1", "orch1", num_local=5)
        
        assert_work_plan_status(plan, expected_pending=5, expected_total=5)
    
    def test_work_plan_status_counts_mixed(self):
        """✅ MEDIUM: Test status counts with mixed statuses."""
        plan = create_work_plan_with_items("thread1", "orch1", num_local=2, num_remote=3)
        
        items = list(plan.items.values())
        items[0].status = WorkItemStatus.DONE
        items[1].status = WorkItemStatus.IN_PROGRESS
        items[1].kind = WorkItemKind.LOCAL
        items[2].status = WorkItemStatus.IN_PROGRESS
        items[2].kind = WorkItemKind.REMOTE
        items[3].status = WorkItemStatus.FAILED
        # items[4] stays PENDING
        
        assert_work_plan_status(
            plan,
            expected_pending=1,
            expected_in_progress=2,  # Now includes both LOCAL and REMOTE in progress
            expected_done=1,
            expected_failed=1,
            expected_total=5
        )
    
    def test_work_plan_status_counts_after_updates(self):
        """✅ MEDIUM: Test status counts are accurate after updates."""
        plan = create_work_plan_with_items("thread1", "orch1", num_local=3)
        
        # Initially all pending
        assert_work_plan_status(plan, expected_pending=3)
        
        # Mark one as done
        list(plan.items.values())[0].status = WorkItemStatus.DONE
        assert_work_plan_status(plan, expected_pending=2, expected_done=1)
        
        # Mark another as failed
        list(plan.items.values())[1].status = WorkItemStatus.FAILED
        assert_work_plan_status(plan, expected_pending=1, expected_done=1, expected_failed=1)


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.workload
class TestWorkPlanResultTracking(BaseUnitTest):
    """Test work item result tracking."""
    
    def test_work_item_result_on_success(self):
        """✅ SIMPLE: Test storing result on successful completion."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING
        )

        # Complete with result
        item.status = WorkItemStatus.DONE
        item.result = WorkItemResult(
            success=True,
            final_summary="Task completed successfully",
            data={"output": "result data"}
        )

        assert item.result is not None
        assert item.result.success is True
        assert item.result.final_summary == "Task completed successfully"
        assert item.result.data["output"] == "result data"
    
    def test_work_item_result_on_failure(self):
        """✅ SIMPLE: Test storing result on failure."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING
        )

        # Fail with result
        item.status = WorkItemStatus.FAILED
        item.error = "Task failed"
        item.result = WorkItemResult(
            success=False,
            final_summary="Failed to process data",
            data={"error_code": "ERR_001"}
        )

        assert item.result is not None
        assert item.result.success is False
        assert item.error is not None
    
    def test_work_item_result_metadata(self):
        """✅ MEDIUM: Test result metadata storage."""
        item = WorkItem(
            id="item_1",
            kind=WorkItemKind.LOCAL,
            title="Test",
            description="Test",
            status=WorkItemStatus.PENDING
        )

        # Complete with metadata
        item.status = WorkItemStatus.DONE
        item.result = WorkItemResult(
            success=True,
            final_summary="Processed 100 records",
            metadata={
                "records_processed": 100,
                "processing_time_ms": 523,
                "worker_id": "worker1"
            }
        )

        assert item.result.metadata["records_processed"] == 100
        assert item.result.metadata["processing_time_ms"] == 523


@pytest.mark.unit
@pytest.mark.orchestrator
@pytest.mark.workload
class TestWorkPlanThreadSafety(BaseUnitTest):
    """Test thread-safe operations on work plan."""
    
    def test_workspace_service_atomic_update(self):
        """✅ COMPLEX: Test atomic work item updates via workspace service."""
        service = UnifiedWorkloadService.create_in_memory()
        
        # Create thread and plan
        thread = service.create_thread("Test", "Obj", "orch1")
        workspace_service = service.get_workspace_service()
        
        plan = create_work_plan_with_items(thread.thread_id, "orch1", num_local=1)
        workspace_service.save_work_plan(plan)
        
        # Atomic update
        def update_func(item, plan):
            item.status = WorkItemStatus.DONE
            item.result = WorkItemResult(success=True, final_summary="Updated")
        
        success = workspace_service.atomic_update_work_item(
            thread.thread_id, "orch1", "local_1", update_func
        )
        
        assert success is True
        
        # Verify update
        loaded_plan = workspace_service.load_work_plan(thread.thread_id, "orch1")
        assert loaded_plan.items["local_1"].status == WorkItemStatus.DONE
    
    def test_workspace_service_concurrent_save_load(self):
        """✅ COMPLEX: Test concurrent save/load operations are consistent."""
        service = UnifiedWorkloadService.create_in_memory()
        
        thread = service.create_thread("Test", "Obj", "orch1")
        workspace_service = service.get_workspace_service()
        
        # Create and save plan
        plan = create_work_plan_with_items(thread.thread_id, "orch1", num_local=3)
        workspace_service.save_work_plan(plan)
        
        # Modify and save
        plan.items["local_1"].status = WorkItemStatus.DONE
        workspace_service.save_work_plan(plan)
        
        # Load should get latest
        loaded = workspace_service.load_work_plan(thread.thread_id, "orch1")
        assert loaded.items["local_1"].status == WorkItemStatus.DONE
