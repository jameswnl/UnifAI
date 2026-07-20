"""
Notifier port (plan item [2.6], issue #16).

Delivery path for human-facing signals — approval requests and
escalations — in headless deployments (the harness profile has no web
UI; approval events on the session stream have no watcher unless a
client subscribes). Products plug in their own implementation (RHDH
notifications, PagerDuty, ticketing); webhook and Slack ship built in.

Best-effort by design: notification failures are logged, never raised —
the workflow outcome must not depend on a chat service being up. The
audit trail ([1.3]) is the durable record of what was sent.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class Notifier(ABC):
    """One outbound human-notification target."""

    @abstractmethod
    def send(self, kind: str, session_id: str, payload: Dict[str, Any]) -> None:
        """Deliver one notification. kind: approval.requested | session.escalated."""
        ...


class NotifierHub:
    """Fans out to all configured notifiers; swallows individual failures."""

    def __init__(self, notifiers: List[Notifier] | None = None) -> None:
        self._notifiers = list(notifiers or [])

    @property
    def enabled(self) -> bool:
        return bool(self._notifiers)

    def notify(self, kind: str, session_id: str, payload: Dict[str, Any]) -> None:
        for notifier in self._notifiers:
            try:
                notifier.send(kind, session_id, payload)
            except Exception:  # noqa: BLE001 — best-effort by contract
                logger.exception("notifier %s failed for %s/%s",
                                 type(notifier).__name__, kind, session_id)

    # ── typed helpers ────────────────────────────────────────────────

    def approval_requested(self, session_id: str, *, request_id: str,
                           tool_name: str, node_uid: str,
                           reasoning: str = "") -> None:
        self.notify("approval.requested", session_id, {
            "request_id": request_id,
            "tool_name": tool_name,
            "node_uid": node_uid,
            "reasoning": reasoning,
        })

    def session_escalated(self, session_id: str, *, node_uid: str,
                          reason: str, error: str,
                          attempts: int) -> None:
        self.notify("session.escalated", session_id, {
            "node_uid": node_uid,
            "reason": reason,
            "error": error,
            "attempts": attempts,
        })


NULL_NOTIFIER = NotifierHub([])
