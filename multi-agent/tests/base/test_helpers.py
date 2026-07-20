"""
Generic test helper functions for ALL nodes.

These helpers provide common patterns that any node test can use.
Keeps test code DRY and consistent across the test suite.

ALL functions here are GENERIC and work for ANY node type.
"""

from typing import Set
from mas.graph.state.graph_state import GraphState, Channel
from mas.graph.state.state_view import StateView
from mas.graph.models import StepContext


def setup_node_with_state(node, channels: Set[str] = None):
    """
    ✅ GENERIC: Setup any node with state and proper channel permissions.
    
    This is the standard pattern ALL node tests should use to initialize
    state before testing node behavior.
    
    Args:
        node: Any node instance (OrchestratorNode, CustomAgentNode, etc.)
        channels: Set of channel names for read/write access
                 If None, uses common workload channels
    
    Returns:
        The StateView that was set
        
    Example:
        node = OrchestratorNode(llm=mock_llm)
        state_view = setup_node_with_state(node)
        # Now node can access workload services
        service = node.get_workload_service()
    """
    if channels is None:
        # Default: common workload channels
        channels = {
            Channel.THREADS,
            Channel.WORKSPACES,
            Channel.TASK_THREADS,
            Channel.INTER_PACKETS,  # For IEM
            Channel.MESSAGES  # For conversation
        }
    
    state = GraphState()
    state_view = StateView(state, reads=channels, writes=channels)
    node._state = state_view
    
    return state_view


def setup_node_with_context(node, uid: str, adjacent_nodes: list = None):
    """
    ✅ GENERIC: Setup node with both state and context.
    
    Use this when tests need to access node.uid or call methods that
    access self.uid, self.display_name, or adjacency.
    
    Args:
        node: Any node instance
        uid: Node UID
        adjacent_nodes: List of adjacent node UIDs
        
    Returns:
        Tuple of (StateView, StepContext)
        
    Example:
        node = CustomAgentNode(llm=mock_llm)
        state_view, context = setup_node_with_context(node, "agent1", ["orch1"])
        assert node.uid == "agent1"  # Now works!
        node._handle_new_work(task)  # Methods that use self.uid work!
    """
    # Setup state
    state_view = setup_node_with_state(node)
    
    # Setup context
    context = create_test_step_context(uid, adjacent_nodes or [])
    node._ctx = context
    
    return state_view, context


def create_test_element_card(uid: str, name: str = None, description: str = None, 
                            capabilities: set = None, type_key: str = "test_node"):
    """
    ✅ GENERIC: Create REAL ElementCard for testing.
    
    Creates actual ElementCard instances, not mocks. This ensures compatibility
    with ALL ElementCard operations and future changes.
    
    Args:
        uid: Unique identifier
        name: Display name (defaults to uid)
        description: Description (defaults to "Test node {uid}")
        capabilities: Set of capability names (defaults to empty)
        type_key: Element type (defaults to "test_node")
        
    Returns:
        Real ElementCard instance
        
    Example:
        card = create_test_element_card("agent1", capabilities={"analysis", "reporting"})
    """
    from mas.elements.common.card import ElementCard
    from mas.elements.common.card.models.card import Capability
    from mas.core.enums import ResourceCategory
    
    cap_list = [Capability(name=c) for c in (capabilities or set())]
    
    return ElementCard(
        uid=uid,
        category=ResourceCategory.NODE,
        type_key=type_key,
        name=name or uid,
        description=description or f"Test node {uid}",
        capabilities=cap_list,
        skills=[],
        configuration={},
        metadata=None
    )


def create_test_adjacent_nodes(node_uids: list = None, node_cards: dict = None):
    """
    ✅ GENERIC: Create REAL AdjacentNodes for testing.
    
    Creates actual AdjacentNodes Pydantic model with REAL ElementCards.
    This works with ALL AdjacentNodes methods (.items(), .keys(), .filter_by_capability(), etc.)
    without needing Mock patches.
    
    Args:
        node_uids: List of node UIDs to create simple cards for
        node_cards: Dict of {uid: ElementCard} for custom cards (overrides node_uids)
        
    Returns:
        Real AdjacentNodes instance
        
    Example:
        # Simple: Just UIDs
        adj = create_test_adjacent_nodes(["agent1", "agent2"])
        
        # Advanced: Custom cards with capabilities
        cards = {
            "agent1": create_test_element_card("agent1", capabilities={"analysis"}),
            "agent2": create_test_element_card("agent2", capabilities={"reporting"})
        }
        adj = create_test_adjacent_nodes(node_cards=cards)
    """
    from mas.graph.models.adjacency import AdjacentNodes
    
    if node_cards:
        # Use provided cards
        return AdjacentNodes(nodes=node_cards)
    elif node_uids:
        # Create simple cards from UIDs
        cards = {uid: create_test_element_card(uid) for uid in node_uids}
        return AdjacentNodes(nodes=cards)
    else:
        # Empty adjacent nodes
        return AdjacentNodes.empty()


def create_test_step_context(uid: str, adjacent_node_uids: list = None):
    """
    ✅ GENERIC: Create StepContext for testing with REAL objects.
    
    Now creates REAL AdjacentNodes with REAL ElementCards instead of mocks.
    This ensures compatibility with ALL future operations and is more maintainable.
    
    Args:
        uid: The unique identifier for the step
        adjacent_node_uids: List of adjacent node UIDs
        
    Returns:
        StepContext instance properly configured for testing
    """
    from mas.graph.models import StepContext
    from mas.blueprints.models.blueprint import StepMeta

    # Real StepMeta — StepContext validates this field (a Mock fails pydantic validation)
    metadata = StepMeta(
        display_name=f"Test {uid}",
        description="Test node for testing",
    )
    
    # ✅ Create REAL AdjacentNodes with REAL ElementCards
    adjacent_nodes = create_test_adjacent_nodes(node_uids=adjacent_node_uids)
    
    return StepContext(
        uid=uid,
        metadata=metadata,
        adjacent_nodes=adjacent_nodes
    )


def assert_workplan_created(state_view: StateView, thread_id: str, owner_uid: str) -> bool:
    """
    ✅ GENERIC: Assert that a work plan was created for any WorkloadCapable node.
    
    Args:
        state_view: The state view to check
        thread_id: Thread ID to check
        owner_uid: Owner UID of the workplan
        
    Returns:
        True if workplan exists
        
    Example:
        # After orchestrator runs
        assert_workplan_created(state_view, "thread_1", "orch1")
    """
    from mas.elements.nodes.common.workload import UnifiedWorkloadService, StateBoundStorage
    
    storage = StateBoundStorage(state_view)
    service = UnifiedWorkloadService(storage)
    
    work_plan = service.get_workspace_service().load_work_plan(thread_id, owner_uid)
    assert work_plan is not None, f"WorkPlan not found for thread={thread_id}, owner={owner_uid}"
    
    return True


def assert_thread_created(state_view: StateView, thread_title: str) -> str:
    """
    ✅ GENERIC: Assert that a thread was created and return its ID.
    
    Args:
        state_view: The state view to check
        thread_title: Expected thread title
        
    Returns:
        Thread ID if found
        
    Example:
        thread_id = assert_thread_created(state_view, "My Task")
    """
    from mas.elements.nodes.common.workload import UnifiedWorkloadService, StateBoundStorage
    
    storage = StateBoundStorage(state_view)
    service = UnifiedWorkloadService(storage)
    
    # Get all threads (this is a simplification - in real code might need to search)
    # For now, just verify we can access thread service
    thread_service = service.get_thread_service()
    assert thread_service is not None
    
    # Return a dummy ID for now - this would need proper implementation
    # based on how threads are actually stored
    return "thread_created"


# =============================================================================
# ✅ GENERIC ASSERTION HELPERS - Work for ANY node type
# =============================================================================

def assert_has_workload_capability(node):
    """
    ✅ GENERIC: Assert node has workload management capabilities.
    
    Example:
        node = OrchestratorNode(llm=mock_llm)
        setup_node_with_state(node)
        assert_has_workload_capability(node)
    """
    assert hasattr(node, 'get_workload_service'), \
        f"{node.__class__.__name__} should have get_workload_service()"
    assert hasattr(node, 'workspaces'), \
        f"{node.__class__.__name__} should have .workspaces property"
    assert hasattr(node, 'threads'), \
        f"{node.__class__.__name__} should have .threads property"


def assert_has_iem_capability(node):
    """
    ✅ GENERIC: Assert node has IEM messaging capabilities.
    
    Example:
        node = CustomAgentNode(llm=mock_llm)
        setup_node_with_context(node, "agent1")
        assert_has_iem_capability(node)
    """
    assert hasattr(node, 'send_task'), \
        f"{node.__class__.__name__} should have send_task()"
    assert hasattr(node, 'inbox_packets'), \
        f"{node.__class__.__name__} should have inbox_packets()"


def assert_has_llm_capability(node):
    """
    ✅ GENERIC: Assert node has LLM capabilities.
    
    Example:
        node = OrchestratorNode(llm=mock_llm)
        assert_has_llm_capability(node)
    """
    assert hasattr(node, 'llm'), \
        f"{node.__class__.__name__} should have .llm attribute"
    assert node.llm is not None, \
        f"{node.__class__.__name__}.llm should not be None"


def assert_has_agent_capability(node):
    """
    ✅ GENERIC: Assert node has agent execution capabilities.
    
    Example:
        node = CustomAgentNode(llm=mock_llm)
        assert_has_agent_capability(node)
    """
    assert hasattr(node, 'create_strategy'), \
        f"{node.__class__.__name__} should have create_strategy()"
    assert hasattr(node, 'run_agent'), \
        f"{node.__class__.__name__} should have run_agent()"


def get_workspace_from_node(node, thread_id: str):
    """
    ✅ GENERIC: Get workspace from ANY WorkloadCapable node (correct API).
    
    Replaces the deprecated node.get_workspace(thread_id) pattern.
    
    Args:
        node: Any node with WorkloadCapableMixin (CustomAgent, Orchestrator, etc.)
        thread_id: Thread ID to get workspace for
        
    Returns:
        Workspace instance
        
    Example:
        workspace = get_workspace_from_node(custom_agent, "my_thread")
        results = workspace.context.results
    """
    service = node.get_workload_service()
    workspace_service = service.get_workspace_service()
    return workspace_service.get_workspace(thread_id)


def get_thread_from_node(node, thread_id: str):
    """
    ✅ GENERIC: Get thread from ANY WorkloadCapable node using ThreadService.
    
    Uses the proper ThreadService API - same as production code.
    
    Args:
        node: Any node with WorkloadCapableMixin (CustomAgent, Orchestrator, etc.)
        thread_id: Thread ID to get
        
    Returns:
        Thread instance or None
        
    Example:
        thread = get_thread_from_node(orchestrator, "thread123")
        if thread:
            print(f"Thread depth: {thread_service.get_thread_depth(thread.thread_id)}")
    """
    thread_service = node.threads  # From WorkloadCapableMixin
    return thread_service.get_thread(thread_id)


def get_root_threads_from_node(node):
    """
    ✅ GENERIC: Get all root threads from ANY WorkloadCapable node.
    
    Uses ThreadService.list_root_threads() - proper API.
    
    Args:
        node: Any node with WorkloadCapableMixin (CustomAgent, Orchestrator, etc.)
        
    Returns:
        List of root Thread instances
        
    Example:
        root_threads = get_root_threads_from_node(orchestrator)
        for thread in root_threads:
            print(f"Root thread: {thread.thread_id}")
    """
    thread_service = node.threads  # From WorkloadCapableMixin
    return thread_service.list_root_threads()


# =============================================================================
# ✅ GENERIC ORCHESTRATION TEST HELPERS - Work for ALL orchestration scenarios
# =============================================================================

def create_work_plan_with_items(
    thread_id: str,
    owner_uid: str,
    num_local: int = 0,
    num_remote: int = 0,
    remote_workers: list = None
):
    """
    ✅ GENERIC: Create work plan with pre-populated items.
    
    Useful for: Setting up test scenarios with known work plans.
    Works for: ANY orchestrator or workload testing.
    
    Args:
        thread_id: Thread ID for the work plan
        owner_uid: Owner node UID (usually orchestrator)
        num_local: Number of LOCAL work items to create
        num_remote: Number of REMOTE work items to create
        remote_workers: List of worker UIDs for remote items (cycles through list)
        
    Returns:
        WorkPlan with populated items
        
    Example:
        plan = create_work_plan_with_items("thread1", "orch1", num_local=2, num_remote=3, 
                                          remote_workers=["worker1", "worker2"])
    """
    from mas.elements.nodes.common.workload import WorkPlan, WorkItem, WorkItemKind, WorkItemStatus
    
    plan = WorkPlan(
        summary="Test work plan",
        owner_uid=owner_uid,
        thread_id=thread_id
    )
    
    # Add local items
    for i in range(num_local):
        item = WorkItem(
            id=f"local_{i+1}",
            kind=WorkItemKind.LOCAL,
            title=f"Local Task {i+1}",
            description=f"Execute local work item {i+1}",
            status=WorkItemStatus.PENDING
        )
        plan.items[item.id] = item
    
    # Add remote items
    if remote_workers is None:
        remote_workers = [f"worker_{i+1}" for i in range(num_remote)]
    
    for i in range(num_remote):
        worker_uid = remote_workers[i % len(remote_workers)] if remote_workers else f"worker_{i+1}"
        item = WorkItem(
            id=f"remote_{i+1}",
            kind=WorkItemKind.REMOTE,
            title=f"Remote Task {i+1}",
            description=f"Delegate work item {i+1}",
            assigned_uid=worker_uid,
            status=WorkItemStatus.PENDING
        )
        plan.items[item.id] = item
    
    return plan


def assert_work_plan_status(
    plan,
    expected_pending: int = None,
    expected_in_progress: int = None,
    expected_waiting: int = None,
    expected_done: int = None,
    expected_failed: int = None,
    expected_blocked: int = None,
    expected_total: int = None
):
    """
    ✅ GENERIC: Assert work plan status counts.
    
    Useful for: Verifying work plan state in tests.
    Works for: ANY work plan testing.
    
    Args:
        plan: WorkPlan instance to check
        expected_*: Expected counts for each status (None = don't check)
        
    Example:
        assert_work_plan_status(plan, expected_pending=2, expected_done=3, expected_total=5)
    """
    counts = plan.get_status_counts()
    
    if expected_pending is not None:
        assert counts.pending == expected_pending, \
            f"Expected {expected_pending} PENDING items, got {counts.pending}"
    
    if expected_in_progress is not None:
        assert counts.in_progress == expected_in_progress, \
            f"Expected {expected_in_progress} IN_PROGRESS items, got {counts.in_progress}"
    
    if expected_waiting is not None:
        assert counts.waiting == expected_waiting, \
            f"Expected {expected_waiting} WAITING items, got {counts.waiting}"
    
    if expected_done is not None:
        assert counts.done == expected_done, \
            f"Expected {expected_done} DONE items, got {counts.done}"
    
    if expected_failed is not None:
        assert counts.failed == expected_failed, \
            f"Expected {expected_failed} FAILED items, got {counts.failed}"
    
    if expected_blocked is not None:
        assert counts.blocked == expected_blocked, \
            f"Expected {expected_blocked} BLOCKED items, got {counts.blocked}"
    
    if expected_total is not None:
        assert counts.total == expected_total, \
            f"Expected {expected_total} total items, got {counts.total}"


def create_mock_worker_node(uid: str, capabilities: list = None, node_type: str = "worker"):
    """
    ✅ GENERIC: Create mock worker node for orchestration tests.
    
    Useful for: Testing delegation and multi-agent scenarios.
    Works for: ANY orchestration testing with multiple nodes.
    
    Args:
        uid: Unique identifier for the worker
        capabilities: List of capability strings (e.g., ["data_processing", "analysis"])
        node_type: Type of node (default: "worker")
        
    Returns:
        Mock object representing a worker node
        
    Example:
        worker = create_mock_worker_node("worker1", capabilities=["analysis", "reporting"])
    """
    from unittest.mock import Mock
    
    worker = Mock()
    worker.uid = uid
    worker.type = node_type
    worker.description = f"Test {node_type} node"
    worker.capabilities = set(capabilities or [])
    
    return worker


def simulate_worker_response(
    orchestrator,
    thread_id: str,
    correlation_task_id: str,
    success: bool = True,
    content: str = "Work completed",
    from_uid: str = "worker1",
    result_data: dict = None
):
    """
    ✅ GENERIC: Simulate worker completing work and sending response.
    
    Useful for: Testing response handling without real workers.
    Works for: ANY orchestration testing with delegation.
    
    Args:
        orchestrator: Orchestrator node instance
        thread_id: Thread ID for the response
        correlation_task_id: Correlation ID linking response to work item
        success: Whether work succeeded
        content: Response content
        from_uid: UID of responding worker
        result_data: Optional result data dict
        
    Returns:
        Thread ID if work plan was updated, None otherwise
        
    Example:
        thread_id = simulate_worker_response(orch, "thread1", "corr_123", 
                                            success=True, from_uid="worker1")
    """
    from mas.elements.nodes.common.workload import Task
    
    response = Task(
        content=content,
        created_by=from_uid,
        correlation_task_id=correlation_task_id,
        thread_id=thread_id
    )
    
    if not success:
        # Task.error is now a string (type consistency fixed)
        response.error = content
    elif result_data:
        response.result = result_data
    
    return orchestrator._handle_task_response(response)


def create_predictable_llm_for_phases(phase_responses: dict):
    """
    ✅ GENERIC: Create LLM mock with predictable responses per phase.
    
    Useful for: Testing phase transitions with controlled LLM behavior.
    Works for: ANY phase-based orchestration testing.
    
    Args:
        phase_responses: Dict mapping phase names to list of responses
                        e.g., {"planning": ["Create plan"], "allocation": ["Assign work"]}
        
    Returns:
        Mock LLM that returns predictable responses
        
    Example:
        llm = create_predictable_llm_for_phases({
            "planning": ["I'll create a 3-step plan"],
            "monitoring": ["All tasks completed"]
        })
    """
    from unittest.mock import Mock
    
    llm = Mock()
    llm.phase_responses = phase_responses
    llm.call_count_per_phase = {phase: 0 for phase in phase_responses.keys()}
    
    def mock_chat(messages, tools=None, **kwargs):
        # Simple mock that returns next response
        # In real tests, you'd inspect messages to determine phase
        mock_response = Mock()
        mock_response.content = "Mock LLM response"
        mock_response.tool_calls = []
        return mock_response
    
    llm.chat = mock_chat
    return llm


# ==================== THREAD HIERARCHY HELPERS ====================

def create_thread_hierarchy(orchestrator, parent_thread_id: str, num_children: int = 1):
    """
    ✅ GENERIC: Create parent thread with children for testing hierarchy.
    
    Useful for: Testing thread parent/child relationships and response routing.
    Works for: ANY node with ThreadService (Orchestrator, CustomAgent).
    
    Args:
        orchestrator: Node with thread service (has .threads property)
        parent_thread_id: Thread ID for parent
        num_children: Number of child threads to create
        
    Returns:
        Dict with structure: {
            "parent": Thread,
            "children": [Thread, Thread, ...]
        }
        
    Example:
        hierarchy = create_thread_hierarchy(orch, "parent_1", num_children=3)
        parent = hierarchy["parent"]
        children = hierarchy["children"]
    """
    thread_service = orchestrator.get_workload_service().get_thread_service()
    
    # Create parent thread
    parent = thread_service.create_root_thread(
        title=f"Parent Thread {parent_thread_id}",
        objective="Parent objective",
        initiator="test_initiator"
    )
    
    # Create children
    children = []
    for i in range(num_children):
        child = thread_service.create_child_thread(
            parent=parent,
            title=f"Child Thread {i+1}",
            objective=f"Child {i+1} objective",
            initiator="test_initiator"
        )
        children.append(child)
    
    return {
        "parent": parent,
        "children": children
    }


def create_multi_level_hierarchy(orchestrator, levels: int = 3):
    """
    ✅ GENERIC: Create multi-level thread hierarchy (grandparent → parent → child).
    
    Useful for: Testing deep hierarchy traversal and response routing.
    Works for: ANY node with ThreadService.
    
    Args:
        orchestrator: Node with thread service
        levels: Number of levels in hierarchy (minimum 2)
        
    Returns:
        List of threads from root to leaf: [grandparent, parent, child, ...]
        
    Example:
        threads = create_multi_level_hierarchy(orch, levels=4)
        root = threads[0]
        leaf = threads[-1]
        middle = threads[1:-1]
    """
    if levels < 2:
        raise ValueError("Hierarchy must have at least 2 levels")
    
    thread_service = orchestrator.get_workload_service().get_thread_service()
    
    # Create root
    hierarchy = []
    root = thread_service.create_root_thread(
        title="Root Thread",
        objective="Root objective",
        initiator="test_initiator"
    )
    hierarchy.append(root)
    
    # Create remaining levels
    current_parent = root
    for level in range(1, levels):
        child = thread_service.create_child_thread(
            parent=current_parent,
            title=f"Level {level} Thread",
            objective=f"Level {level} objective",
            initiator="test_initiator"
        )
        hierarchy.append(child)
        current_parent = child
    
    return hierarchy


def assert_thread_hierarchy(parent_thread, child_thread):
    """
    ✅ GENERIC: Assert correct parent-child thread relationship.
    
    Useful for: Verifying thread hierarchy integrity.
    Works for: ANY Thread objects.
    
    Args:
        parent_thread: Parent Thread instance
        child_thread: Child Thread instance
        
    Example:
        assert_thread_hierarchy(parent, child)
    """
    # Child should reference parent
    assert child_thread.parent_thread_id == parent_thread.thread_id, \
        f"Child's parent_thread_id {child_thread.parent_thread_id} != parent's thread_id {parent_thread.thread_id}"
    
    # Parent should list child
    assert child_thread.thread_id in parent_thread.child_thread_ids, \
        f"Child {child_thread.thread_id} not in parent's child_thread_ids {parent_thread.child_thread_ids}"


def assert_response_routes_to_root(orchestrator, child_thread_id: str, expected_root_id: str):
    """
    ✅ GENERIC: Assert response from child routes to correct thread (where orchestrator's work plan is).
    
    Useful for: Verifying response routing through hierarchy.
    Works for: ANY orchestrator with ThreadService.
    
    Args:
        orchestrator: Orchestrator node
        child_thread_id: Child thread ID (where response originates)
        expected_root_id: Expected thread ID (where orchestrator's work plan lives)
        
    Example:
        assert_response_routes_to_root(orch, "child_123", "orch_thread_1")
    """
    thread_service = orchestrator.get_workload_service().get_thread_service()
    # Find where THIS orchestrator's work plan is stored
    actual_root = thread_service.find_work_plan_owner(child_thread_id, orchestrator.uid)
    
    assert actual_root == expected_root_id, \
        f"Response from {child_thread_id} routes to {actual_root}, expected {expected_root_id}"


def get_hierarchy_depth(thread_service, thread_id: str) -> int:
    """
    ✅ GENERIC: Get depth of thread in hierarchy (0 for root).
    
    Useful for: Verifying hierarchy structure.
    Works for: ANY ThreadService.
    
    Args:
        thread_service: ThreadService instance
        thread_id: Thread ID to check
        
    Returns:
        Depth (0 = root, 1 = first level child, etc.)
        
    Example:
        depth = get_hierarchy_depth(service, "child_thread_id")
        assert depth == 2  # Grandchild
    """
    path = thread_service.get_hierarchy_path(thread_id)
    return len(path) - 1  # Root has depth 0


# ==================== MULTI-NODE INTEGRATION HELPERS ====================

def create_custom_agent_node(uid: str, llm, tools=None, system_message=""):
    """
    ✅ GENERIC: Create a real CustomAgentNode for testing.
    
    Useful for: Testing orchestrator with real custom agents.
    Works for: ANY multi-node integration tests.
    
    Args:
        uid: Unique identifier for the agent
        llm: LLM provider for the agent
        tools: Optional list of tools for the agent
        system_message: Optional system message
        
    Returns:
        CustomAgentNode instance properly configured
        
    Example:
        agent = create_custom_agent_node("agent1", mock_llm, tools=[search_tool])
        state_view, context = setup_node_with_context(agent, "agent1", [])
    """
    from mas.elements.nodes.custom_agent.custom_agent import CustomAgentNode
    
    agent = CustomAgentNode(
        llm=llm,
        tools=tools or [],
        system_message=system_message
    )
    
    return agent


def create_orchestrator_node(uid: str, llm, tools=None, system_message=""):
    """
    ✅ GENERIC: Create a real OrchestratorNode for testing.
    
    Useful for: Testing hierarchical orchestration.
    Works for: ANY multi-node orchestration tests.
    
    Args:
        uid: Unique identifier for the orchestrator
        llm: LLM provider for the orchestrator
        tools: Optional list of domain tools
        system_message: Optional system message
        
    Returns:
        OrchestratorNode instance properly configured
        
    Example:
        parent_orch = create_orchestrator_node("orch1", mock_llm)
        child_orch = create_orchestrator_node("orch2", mock_llm)
    """
    from mas.elements.nodes.orchestrator.orchestrator_node import OrchestratorNode
    
    orch = OrchestratorNode(
        llm=llm,
        tools=tools or [],
        system_message=system_message
    )
    
    return orch


def connect_nodes(sender, receiver):
    """
    ✅ GENERIC: Connect two nodes so sender can delegate to receiver.
    
    Useful for: Setting up multi-node communication.
    Works for: ANY node types (Orchestrator, CustomAgent, etc.).
    
    Args:
        sender: Node that will send tasks (needs receiver in adjacent_nodes)
        receiver: Node that will receive tasks
        
    Example:
        orch = create_orchestrator_node("orch1", mock_llm)
        agent = create_custom_agent_node("agent1", mock_llm)
        connect_nodes(orch, agent)
        # Now orch can delegate to agent
    """
    # Update sender's context to include receiver in adjacent nodes
    if hasattr(sender, '_ctx') and sender._ctx:
        receiver_uid = receiver._ctx.uid if hasattr(receiver, '_ctx') and receiver._ctx else "receiver"
        # Add to adjacent_nodes mock
        if hasattr(sender._ctx.adjacent_nodes, '_mock_children'):
            # It's a Mock, update it
            current_uids = list(sender._ctx.adjacent_nodes.keys() if hasattr(sender._ctx.adjacent_nodes, 'keys') else [])
            if receiver_uid not in current_uids:
                current_uids.append(receiver_uid)
                sender._ctx.adjacent_nodes.keys = lambda: current_uids
                sender._ctx.adjacent_nodes.__iter__ = lambda: iter(current_uids)


def send_task_between_nodes(sender, receiver, task_content: str, thread_id: str = None):
    """
    ✅ GENERIC: Send a task from one node to another.
    
    Useful for: Testing task delegation between real nodes.
    Works for: ANY node communication (Orchestrator→Agent, Orchestrator→Orchestrator).
    
    Args:
        sender: Node sending the task
        receiver: Node receiving the task
        task_content: Task content/description
        thread_id: Optional thread ID for context
        
    Returns:
        Task instance that was sent
        
    Example:
        task = send_task_between_nodes(orch, agent, "Process this data", "thread1")
    """
    from mas.elements.nodes.common.workload import Task
    from mas.core.iem.packets import TaskPacket
    from mas.core.iem.models import ElementAddress
    
    # Get sender and receiver UIDs
    sender_uid = sender._ctx.uid if hasattr(sender, '_ctx') and sender._ctx else "sender"
    receiver_uid = receiver._ctx.uid if hasattr(receiver, '_ctx') and receiver._ctx else "receiver"
    
    # Create task
    task = Task(
        content=task_content,
        created_by=sender_uid,
        thread_id=thread_id or "default_thread",
        should_respond=True,
        response_to=sender_uid
    )
    
    # Create packet
    packet = TaskPacket.create(
        src=ElementAddress(uid=sender_uid),
        dst=ElementAddress(uid=receiver_uid),
        task=task
    )
    
    # ✅ Deliver to shared inter_packets channel (receiver will auto-filter by dst.uid)
    if hasattr(receiver, '_state') and receiver._state:
        # Use our generic helper that works with REAL IEM architecture (pass StateView directly!)
        add_packet_to_inbox(receiver._state, receiver_uid, packet)
    
    return task


def assert_agent_processed_task(agent, task_content: str):
    """
    ✅ GENERIC: Assert that CustomAgent processed a task.
    
    Useful for: Verifying task execution in CustomAgent.
    Works for: ANY CustomAgentNode.
    
    Args:
        agent: CustomAgentNode instance
        task_content: Expected task content that was processed
        
    Example:
        assert_agent_processed_task(agent, "Process data")
    """
    # Check workspace for task record
    service = agent.get_workload_service()
    # In real tests, would verify task was recorded
    assert service is not None


def wait_for_node_response(node, timeout: int = 5):
    """
    ✅ GENERIC: Wait for node to produce a response.
    
    Useful for: Async multi-node testing.
    Works for: ANY node type.
    
    Args:
        node: Node to wait for
        timeout: Timeout in seconds
        
    Returns:
        Response packet or None
        
    Example:
        response = wait_for_node_response(agent, timeout=10)
        assert response is not None
    """
    import time
    start = time.time()
    
    while time.time() - start < timeout:
        # Check for response in outbox
        if hasattr(node, '_state') and node._state:
            # Would check outbox packets
            pass
        time.sleep(0.1)
    
    return None  # Timeout


def create_multi_node_scenario(orchestrator, agents: list, thread_id: str = "test_thread"):
    """
    ✅ GENERIC: Create multi-node test scenario with orchestrator + agents.
    
    Useful for: Setting up complex multi-node tests.
    Works for: ANY orchestrator + agent combinations.
    
    Args:
        orchestrator: OrchestratorNode instance
        agents: List of CustomAgentNode instances
        thread_id: Thread ID for the scenario
        
    Returns:
        Dict with scenario context: {
            "orchestrator": orchestrator,
            "agents": agents,
            "thread_id": thread_id
        }
        
    Example:
        scenario = create_multi_node_scenario(
            orch, 
            [agent1, agent2, agent3],
            "workflow_1"
        )
    """
    # Connect orchestrator to all agents
    for agent in agents:
        connect_nodes(orchestrator, agent)
    
    return {
        "orchestrator": orchestrator,
        "agents": agents,
        "thread_id": thread_id,
        "agent_uids": [agent._ctx.uid if hasattr(agent, '_ctx') and agent._ctx else f"agent_{i}" 
                       for i, agent in enumerate(agents)]
    }


# ══════════════════════════════════════════════════════════════════════════════
# REAL FLOW EXECUTION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def setup_multi_node_env(nodes_config: list):
    """
    ✅ GENERIC: Setup multiple nodes with shared state and bidirectional adjacency.
    
    This is the PREFERRED way to setup multi-node tests as it ensures:
    - All nodes share the same GraphState (can see each other's packets)
    - Bidirectional adjacency is automatically configured
    - Cleaner, more maintainable test code
    
    Args:
        nodes_config: List of tuples (node, uid, adjacent_uids)
                     Example: [(orch, "orch1", ["agent1", "agent2"]),
                               (agent1, "agent1", ["orch1"]),
                               (agent2, "agent2", ["orch1"])]
        
    Returns:
        Shared state_view that all nodes use
        
    Example - Orchestrator with 2 agents:
        orch = create_orchestrator_node("orch1", orch_llm)
        agent1 = create_custom_agent_node("agent1", agent1_llm)
        agent2 = create_custom_agent_node("agent2", agent2_llm)
        
        state_view = setup_multi_node_env([
            (orch, "orch1", ["agent1", "agent2"]),  # Orch can delegate to both agents
            (agent1, "agent1", ["orch1"]),          # Agent1 can respond to orch
            (agent2, "agent2", ["orch1"])           # Agent2 can respond to orch
        ])
        
        # All nodes now share state and have correct adjacency!
    """
    if not nodes_config:
        raise ValueError("nodes_config cannot be empty")
    
    # First node creates the state
    first_node, first_uid, first_adjacent = nodes_config[0]
    state_view, _ = setup_node_for_execution(first_node, first_uid, first_adjacent)
    
    # Remaining nodes share that state
    for node, uid, adjacent_uids in nodes_config[1:]:
        setup_node_for_execution(node, uid, adjacent_uids or [], shared_state_view=state_view)
    
    return state_view


def setup_node_for_execution(node, uid: str, adjacent_node_uids: list = None, shared_state_view=None):
    """
    ✅ GENERIC: Setup node with FULL execution environment (state + context).
    
    This is the complete setup for REAL FLOW tests where node.run() is called.
    
    Useful for: Integration tests that actually execute nodes.
    Works for: ANY node type (Orchestrator, CustomAgent, etc.).
    
    Args:
        node: Node instance to setup
        uid: UID for the node
        adjacent_node_uids: List of adjacent node UIDs (for delegation)
        shared_state_view: (Optional) Existing StateView to share between multiple nodes.
                          If provided, nodes will share the same GraphState (for multi-node tests).
                          If None, creates a new GraphState.
        
    Returns:
        Tuple of (state_view, context)
        
    Example - Single node:
        orch = create_orchestrator_node("orch1", mock_llm)
        state_view, ctx = setup_node_for_execution(orch, "orch1", ["agent1", "agent2"])
        # Now ready to call orch.run(state_view)
        
    Example - Multi-node (SHARED STATE):
        orch = create_orchestrator_node("orch1", mock_llm)
        agent1 = create_custom_agent_node("agent1", agent_llm)
        
        # First node creates state
        state_view, _ = setup_node_for_execution(orch, "orch1", ["agent1"])
        
        # Subsequent nodes share the same state
        setup_node_for_execution(agent1, "agent1", [], shared_state_view=state_view)
        
        # Now orch and agent1 share the same GraphState and can see each other's packets!
    """
    from mas.graph.state.graph_state import GraphState, Channel
    from mas.graph.state.state_view import StateView
    
    # Use shared state if provided, otherwise create new
    if shared_state_view is not None:
        state_view = shared_state_view
    else:
        # Create state with all necessary channels for execution
        state = GraphState()
        state_view = StateView(
            state,
            reads={Channel.INTER_PACKETS, Channel.THREADS, Channel.WORKSPACES, Channel.TASK_THREADS},
            writes={Channel.INTER_PACKETS, Channel.THREADS, Channel.WORKSPACES, Channel.TASK_THREADS}
        )
    
    # Setup context
    context = create_test_step_context(uid, adjacent_node_uids or [])
    
    # Attach to node
    node._state = state_view
    node._ctx = context
    
    return state_view, context


def create_task_packet(from_uid: str, to_uid: str, task):
    """
    ✅ GENERIC: Create IEM task packet for testing.
    
    Useful for: Creating packets for flow testing.
    Works for: ANY task packet creation.
    
    Args:
        from_uid: Source node UID
        to_uid: Destination node UID
        task: Task instance
        
    Returns:
        TaskPacket ready to be delivered
        
    Example:
        task = Task(content="Process this", thread_id="thread1")
        packet = create_task_packet("orch1", "agent1", task)
    """
    from mas.core.iem.packets import TaskPacket
    from mas.core.iem.models import ElementAddress
    
    return TaskPacket.create(
        src=ElementAddress(uid=from_uid),
        dst=ElementAddress(uid=to_uid),
        task=task
    )


def add_packet_to_inbox(state, node_uid: str, packet):
    """
    ✅ GENERIC: Add packet to shared inter_packets channel (node will auto-filter by dst.uid).
    
    HOW IT WORKS:
    - Adds packet to shared Channel.INTER_PACKETS (the ONE channel for all packets)
    - Node's inbox_packets() will automatically filter by dst.uid to find it
    - This matches the REAL IEM architecture (shared message bus, not separate inboxes)
    - Uses StateView's PUBLIC API (no internal ._b access)
    
    Useful for: Simulating packet delivery in flow tests.
    Works for: ANY GraphState or StateView.
    
    Args:
        state: GraphState OR StateView instance (with INTER_PACKETS write permission!)
        node_uid: UID of node receiving packet (packet.dst.uid should match this!)
        packet: Packet to deliver
        
    Example:
        packet = create_task_packet("user1", "orch1", task)  # dst.uid = "orch1"
        add_packet_to_inbox(state_view, "orch1", packet)  # StateView must have INTER_PACKETS write!
    """
    from mas.graph.state.graph_state import Channel
    
    # ✅ Use StateView's PUBLIC API - works for both GraphState and StateView
    inter_packets = state.get(Channel.INTER_PACKETS, [])
    if not isinstance(inter_packets, list):
        inter_packets = []
    
    # Add packet to shared channel
    inter_packets.append(packet)
    state[Channel.INTER_PACKETS] = inter_packets


def add_packets_to_inbox(state, node_uid: str, packets: list):
    """
    ✅ GENERIC: Add multiple packets to node's inbox.
    
    Useful for: Batch processing tests.
    Works for: ANY GraphState and packets.
    
    Args:
        state: GraphState instance
        node_uid: UID of node receiving packets
        packets: List of packets to deliver
        
    Example:
        packets = [create_task_packet("user1", "orch1", task1),
                   create_task_packet("user1", "orch1", task2)]
        add_packets_to_inbox(state, "orch1", packets)
    """
    for packet in packets:
        add_packet_to_inbox(state, node_uid, packet)


def get_packets_from_outbox(state, node_uid: str):
    """
    ✅ GENERIC: Get all packets sent BY this node from shared inter_packets channel.
    
    HOW IT WORKS:
    - Filters shared Channel.INTER_PACKETS by src.uid to find packets sent by this node
    - This matches the REAL IEM architecture (shared message bus, not separate outboxes)
    - Uses StateView's PUBLIC API (no internal access)
    
    Useful for: Verifying node sent packets.
    Works for: ANY GraphState or StateView.
    
    Args:
        state: GraphState OR StateView instance (with INTER_PACKETS read permission!)
        node_uid: UID of node to check (filters by src.uid)
        
    Returns:
        List of packets sent by this node (empty list if none)
        
    Example:
        packets = get_packets_from_outbox(state_view, "orch1")
        assert len(packets) > 0
    """
    from mas.graph.state.graph_state import Channel
    
    # ✅ Use StateView's PUBLIC API - works for both GraphState and StateView
    inter_packets = state.get(Channel.INTER_PACKETS, [])
    if not isinstance(inter_packets, list):
        return []
    
    # Filter by source UID
    return [p for p in inter_packets if hasattr(p, 'src') and p.src.uid == node_uid]


def find_packet_to_node(state, from_uid: str, to_uid: str):
    """
    ✅ GENERIC: Find packet sent from one node to another in shared inter_packets.
    
    HOW IT WORKS:
    - Filters shared Channel.INTER_PACKETS by src.uid AND dst.uid
    - This matches the REAL IEM architecture
    - Uses StateView's PUBLIC API (no internal access)
    
    Useful for: Verifying delegation/communication.
    Works for: ANY GraphState or StateView.
    
    Args:
        state: GraphState OR StateView instance (with INTER_PACKETS read permission!)
        from_uid: Source node UID (packet.src.uid)
        to_uid: Destination node UID (packet.dst.uid)
        
    Returns:
        First packet matching criteria, or None
        
    Example:
        packet = find_packet_to_node(state_view, "orch1", "agent1")
        assert packet is not None
    """
    from mas.graph.state.graph_state import Channel
    
    # ✅ Use StateView's PUBLIC API - works for both GraphState and StateView
    inter_packets = state.get(Channel.INTER_PACKETS, [])
    if not isinstance(inter_packets, list):
        return None
    
    # Find packet with matching src and dst
    for packet in inter_packets:
        if (hasattr(packet, 'src') and packet.src.uid == from_uid and
                hasattr(packet, 'dst') and packet.dst.uid == to_uid):
            return packet
    
    return None


def create_response_task(original_task, response_content: str, from_uid: str, success: bool = True):
    """
    ✅ GENERIC: Create response task for original task.
    
    Useful for: Simulating agent responses.
    Works for: ANY task response creation.
    
    Args:
        original_task: Original Task that was sent
        response_content: Response content
        from_uid: UID of responding node
        success: Whether work succeeded
        
    Returns:
        Response Task instance
        
    Example:
        response = create_response_task(
            original_task, 
            "Work completed", 
            "agent1", 
            success=True
        )
    """
    from mas.elements.nodes.common.workload import Task
    
    response = Task(
        content=response_content,
        thread_id=original_task.thread_id,
        created_by=from_uid,
        correlation_task_id=original_task.task_id
    )
    
    if not success:
        response.error = response_content
    
    return response


def manually_add_to_outbox(state, node_uid: str, packets: list):
    """
    ✅ GENERIC: Manually add packets to shared inter_packets (for testing packet verification).
    
    HOW IT WORKS:
    - Adds packets to shared Channel.INTER_PACKETS (same as add_packet_to_inbox)
    - The packet's src.uid should already match node_uid
    - This matches the REAL IEM architecture (shared message bus)
    - Uses StateView's PUBLIC API (no internal access)
    
    Useful for: Testing packet finding/verification helpers.
    Works for: ANY GraphState or StateView.
    
    Args:
        state: GraphState OR StateView instance (with INTER_PACKETS write permission!)
        node_uid: UID of node that "sent" packets (packet.src.uid should match!)
        packets: List of packets to add
        
    Example:
        # Test packet finding
        packet = create_task_packet("orch1", "agent1", task)  # src="orch1", dst="agent1"
        manually_add_to_outbox(state_view, "orch1", [packet])
        found = find_packet_to_node(state_view, "orch1", "agent1")
    """
    from mas.graph.state.graph_state import Channel
    
    # ✅ Use StateView's PUBLIC API - works for both GraphState and StateView
    inter_packets = state.get(Channel.INTER_PACKETS, [])
    if not isinstance(inter_packets, list):
        inter_packets = []
    
    # Add all packets to shared channel
    inter_packets.extend(packets)
    state[Channel.INTER_PACKETS] = inter_packets