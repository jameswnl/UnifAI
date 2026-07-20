"""
SessionEventSink port — durable transcript storage (plan item [1.2], issue #8).

Every event emitted on a session channel is appended here, giving a
permanent, queryable record of a run (the "transcript") independent of the
live-streaming transport (Redis TTL streams / in-process queues).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class SessionEventSink(ABC):

    @abstractmethod
    def append(self, session_id: str, event: Dict[str, Any]) -> None:
        """Append one event to the session's transcript."""
        ...

    @abstractmethod
    def list_events(self, session_id: str, offset: int = 0,
                    limit: int = 1000) -> List[Dict[str, Any]]:
        """Return events in append order."""
        ...

    @abstractmethod
    def count(self, session_id: str) -> int: ...

    @abstractmethod
    def delete_session(self, session_id: str) -> int:
        """Remove a session's transcript. Returns number of events deleted."""
        ...
