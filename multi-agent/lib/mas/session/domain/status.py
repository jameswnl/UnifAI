from enum import Enum
from typing import FrozenSet


class SessionStatus(str, Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    # Automation gave up after exhausting retries; a human now
    # owns this run ([2.5], issue #15). Terminal in v1; modeled
    # as a state so park-and-resume (v2) is an enhancement.
    ESCALATED = "ESCALATED"
    # Shared-session specific busy statuses:
    # LOCKED   – session is reserved / queued for execution by another caller
    # IN_USE   – session is actively being executed by another caller
    LOCKED = "LOCKED"
    IN_USE = "IN_USE"


NON_RUNNABLE_STATUSES: FrozenSet[str] = frozenset({
    SessionStatus.PENDING.value,
    SessionStatus.QUEUED.value,
    SessionStatus.LOCKED.value,
})
