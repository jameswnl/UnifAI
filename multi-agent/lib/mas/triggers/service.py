"""
Trigger service ([4.1], issue #23).

Launches a blueprint as a fire-and-forget workflow in response to an
external event (alert webhook) or a schedule. Proactive, event-driven
execution is central to every target use case (SRE alert response, CVE
triage, fleet diagnostics).

Fire-and-forget strategy:
  - Temporal engine → session_service.submit() (durable background run)
  - LangGraph engine → a daemon thread running session_service.run(),
    which under [2.3] is checkpointed and resumable.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from mas.core.identity import Identity, IdentityType

logger = logging.getLogger(__name__)


class TriggerService:
    def __init__(self, session_service, service_user: str = "system") -> None:
        self._sessions = session_service
        self._service_identity = Identity(type=IdentityType.USER, id=service_user)

    def launch(self, blueprint_id: str, inputs: Optional[Dict[str, Any]] = None,
               *, source: str = "trigger", identity: Optional[Identity] = None) -> str:
        """Create a session for *blueprint_id* and start it in the background.

        Returns the run_id immediately.
        """
        who = identity or self._service_identity
        run_id = self._sessions.create(
            identity=who,
            blueprint_id=blueprint_id,
            metadata={"trigger_source": source},
        )
        self._launch_background(run_id, inputs or {})
        logger.info("trigger '%s' launched blueprint %s as session %s",
                    source, blueprint_id, run_id)
        return run_id

    def _launch_background(self, run_id: str, inputs: Dict[str, Any]) -> None:
        # Prefer the durable background engine (Temporal) when available.
        try:
            self._sessions.submit(run_id, inputs)
            return
        except TypeError:
            pass  # no background engine (langgraph profile) — fall through

        def _run():
            try:
                self._sessions.run(run_id, inputs, stream=False)
            except Exception:  # noqa: BLE001 — background run, log only
                logger.exception("triggered session %s failed", run_id)

        threading.Thread(target=_run, name=f"trigger-{run_id}",
                         daemon=True).start()
