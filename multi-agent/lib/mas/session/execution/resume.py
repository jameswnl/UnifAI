"""
Resume-on-startup for the LangGraph engine ([2.3], issue #13).

A replica that dies mid-execution leaves sessions in RUNNING status with
a LangGraph checkpoint holding their progress. On startup this service
finds those sessions and re-runs them; the checkpointed executor detects
the existing checkpoint and continues from the last completed node
instead of restarting the graph.

At-least-once semantics: the node that was in flight when the replica
died is re-executed, so side-effectful steps must be safe to retry —
high-risk steps default to no retry and should carry idempotency in
their tools. Runs in a background thread so startup is not blocked.
"""

from __future__ import annotations

import logging
import threading

from mas.session.domain.status import SessionStatus

logger = logging.getLogger(__name__)


class ResumeService:
    def __init__(self, session_repo, session_manager, foreground_runner) -> None:
        self._repo = session_repo
        self._manager = session_manager
        self._runner = foreground_runner

    def resume_all(self) -> int:
        """Resume every RUNNING session. Returns the count attempted."""
        try:
            run_ids = self._repo.list_run_ids_by_status(SessionStatus.RUNNING.value)
        except Exception:  # noqa: BLE001 — never block startup
            logger.exception("resume scan failed")
            return 0

        if not run_ids:
            return 0

        logger.info("resuming %d interrupted session(s): %s", len(run_ids), run_ids)
        for run_id in run_ids:
            self._resume_one(run_id)
        return len(run_ids)

    def resume_all_async(self) -> None:
        threading.Thread(target=self.resume_all, name="resume-on-startup",
                         daemon=True).start()

    def _resume_one(self, run_id: str) -> None:
        try:
            session = self._manager.get_session(run_id)
            self._runner.run(session, scope="public", stream=False)
            logger.info("resumed session %s to completion", run_id)
        except Exception:  # noqa: BLE001 — one bad session must not stop others
            logger.exception("failed to resume session %s", run_id)
