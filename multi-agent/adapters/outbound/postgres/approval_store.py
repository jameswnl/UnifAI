"""PostgreSQL PendingApprovalStore ([2.2], issue #12)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import List, Optional

from mas.core.hitl.pending_store import PendingApproval, PendingApprovalStore

from outbound.postgres.db import PgCollection


class PgPendingApprovalStore(PendingApprovalStore):

    def __init__(self, dsn: str, table: str = "pending_approvals") -> None:
        self._col = PgCollection(dsn, table)

    @staticmethod
    def _pk(session_id: str, request_id: str) -> str:
        return f"{session_id}␟{request_id}"

    def create(self, approval: PendingApproval) -> None:
        self._col.upsert(self._pk(approval.session_id, approval.request_id),
                         asdict(approval))

    def resolve(self, session_id: str, request_id: str, *,
                decision: str, resolved_by: str = "") -> bool:
        doc = self._col.get(self._pk(session_id, request_id))
        if not doc:
            return False
        doc["status"] = "resolved"
        doc["decision"] = decision
        doc["resolved_by"] = resolved_by
        doc["resolved_at"] = datetime.now(timezone.utc).isoformat()
        self._col.upsert(self._pk(session_id, request_id), doc)
        return True

    def get(self, session_id: str, request_id: str) -> Optional[PendingApproval]:
        doc = self._col.get(self._pk(session_id, request_id))
        return PendingApproval(**doc) if doc else None

    def list_pending(self, session_id: str) -> List[PendingApproval]:
        rows = self._col.execute(
            "SELECT doc FROM {table} WHERE doc ->> 'session_id' = %s "
            "AND doc ->> 'status' = 'pending' ORDER BY doc ->> 'requested_at'",
            (session_id,),
        )
        return [PendingApproval(**r[0]) for r in rows]
