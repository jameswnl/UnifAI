"""
Durable pending-approval store ([2.2], issue #12).

Persists every HITL approval request so a pause survives process
restarts and can be listed / resolved out-of-band — replacing the
ephemeral, TTL-bound Redis gate keys (the old 300s/600s caps made
multi-day approval waits impossible). The live channel still delivers
the unblock to a waiting gate in-process; this store is the durable
system-of-record for what is (or was) awaiting a human.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class PendingApproval:
    request_id: str
    session_id: str
    tool_name: str
    node_uid: str
    status: str = "pending"          # pending | resolved
    decision: Optional[str] = None   # approve | reject | modify | redirect
    reasoning: str = ""
    requested_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None
    resolved_by: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)


class PendingApprovalStore(ABC):

    @abstractmethod
    def create(self, approval: PendingApproval) -> None: ...

    @abstractmethod
    def resolve(self, session_id: str, request_id: str, *,
                decision: str, resolved_by: str = "") -> bool:
        """Mark an approval resolved. Returns False if not found."""
        ...

    @abstractmethod
    def get(self, session_id: str, request_id: str) -> Optional[PendingApproval]: ...

    @abstractmethod
    def list_pending(self, session_id: str) -> List[PendingApproval]: ...
