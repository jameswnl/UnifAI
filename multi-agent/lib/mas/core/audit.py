"""
Audit trail (plan item [1.3], issue #9).

Typed, append-only records for security-relevant actions: session
lifecycle transitions and HITL approval decisions. Reuses the
SessionEventSink port for storage — an audit record is an event on a
dedicated store (``audit_events`` table/collection), so both database
backends come for free.

Auditing is best-effort by design: a failed append is logged, never
raised — the workflow must not die because the audit store hiccuped.
The durable transcript ([1.2]) provides the redundant raw record.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from mas.session.storage.event_sink import SessionEventSink

logger = logging.getLogger(__name__)


class AuditTrail:
    """Thin typed facade over a SessionEventSink used as the audit store."""

    def __init__(self, sink: Optional[SessionEventSink]) -> None:
        self._sink = sink

    @property
    def enabled(self) -> bool:
        return self._sink is not None

    def record(self, session_id: str, type: str, **data: Any) -> None:
        if self._sink is None:
            return
        try:
            self._sink.append(session_id, {
                "type": type,
                "ts": datetime.now(timezone.utc).isoformat(),
                **data,
            })
        except Exception:  # noqa: BLE001 — audit must never kill the run
            logger.exception("audit append failed (session=%s type=%s)",
                             session_id, type)

    # ── typed helpers ────────────────────────────────────────────────

    def session_started(self, session_id: str, *, identity: str, scope: str) -> None:
        self.record(session_id, "session.started", identity=identity, scope=scope)

    def session_completed(self, session_id: str) -> None:
        self.record(session_id, "session.completed")

    def session_failed(self, session_id: str, *, error: str) -> None:
        self.record(session_id, "session.failed", error=error)

    def session_cancelled(self, session_id: str) -> None:
        self.record(session_id, "session.cancelled")

    def approval_requested(self, session_id: str, *, request_id: str,
                           tool_name: str, node_uid: str) -> None:
        self.record(session_id, "approval.requested", request_id=request_id,
                    tool_name=tool_name, node_uid=node_uid)

    def approval_resolved(self, session_id: str, *, request_id: str,
                          decision: str, source: str = "") -> None:
        self.record(session_id, "approval.resolved", request_id=request_id,
                    decision=decision, source=source)

    def list(self, session_id: str, offset: int = 0,
             limit: int = 1000) -> list[Dict[str, Any]]:
        if self._sink is None:
            return []
        return self._sink.list_events(session_id, offset=offset, limit=limit)


NULL_AUDIT = AuditTrail(None)
