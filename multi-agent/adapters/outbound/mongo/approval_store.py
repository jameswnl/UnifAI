"""MongoDB PendingApprovalStore ([2.2], issue #12)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import List, Optional

from pymongo import ASCENDING, MongoClient

from mas.core.hitl.pending_store import PendingApproval, PendingApprovalStore


class MongoPendingApprovalStore(PendingApprovalStore):

    def __init__(self, mongodb_ip: str = "127.0.0.1", mongodb_port: int = 27017,
                 db_name: str = "unifai", coll_name: str = "pending_approvals") -> None:
        client = MongoClient(f"mongodb://{mongodb_ip}:{mongodb_port}/")
        self._coll = client[db_name][coll_name]
        self._coll.create_index(
            [("session_id", ASCENDING), ("request_id", ASCENDING)],
            unique=True, name="uq_session_request",
        )
        self._coll.create_index(
            [("session_id", ASCENDING), ("status", ASCENDING)],
            name="session_status_idx",
        )

    def create(self, approval: PendingApproval) -> None:
        doc = asdict(approval)
        self._coll.update_one(
            {"session_id": approval.session_id, "request_id": approval.request_id},
            {"$set": doc}, upsert=True,
        )

    def resolve(self, session_id: str, request_id: str, *,
                decision: str, resolved_by: str = "") -> bool:
        res = self._coll.update_one(
            {"session_id": session_id, "request_id": request_id},
            {"$set": {
                "status": "resolved",
                "decision": decision,
                "resolved_by": resolved_by,
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        return res.matched_count > 0

    def get(self, session_id: str, request_id: str) -> Optional[PendingApproval]:
        doc = self._coll.find_one(
            {"session_id": session_id, "request_id": request_id}, {"_id": 0})
        return PendingApproval(**doc) if doc else None

    def list_pending(self, session_id: str) -> List[PendingApproval]:
        cursor = (self._coll.find(
            {"session_id": session_id, "status": "pending"}, {"_id": 0})
            .sort("requested_at", ASCENDING))
        return [PendingApproval(**doc) for doc in cursor]
