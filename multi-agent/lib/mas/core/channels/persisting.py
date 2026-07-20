"""
Persisting channel decorators (plan item [1.2], issue #8).

Wraps any ChannelFactory so every event emitted on a session channel is
also appended to a SessionEventSink. Streaming behaviour is unchanged —
the sink write happens first, and a sink failure is logged but never
breaks the live stream (the transcript is best-effort durable, the run
itself must not die because the database hiccuped).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from mas.core.channels.protocols import (
    ChannelFactory,
    InputCapableChannel,
    SessionChannel,
)
from mas.session.storage.event_sink import SessionEventSink

logger = logging.getLogger(__name__)


def _to_event(data: Any) -> dict:
    if isinstance(data, dict):
        return data
    if hasattr(data, "model_dump"):
        return data.model_dump(mode="json")
    return {"data": str(data)}


class _PersistMixin:
    _sink: SessionEventSink
    _inner: SessionChannel

    def _persist(self, data: Any) -> None:
        try:
            self._sink.append(self._inner.session_id, _to_event(data))
        except Exception:  # noqa: BLE001 — transcript is best-effort
            logger.exception("transcript append failed for session %s",
                             self._inner.session_id)


class PersistingChannel(_PersistMixin, SessionChannel):

    def __init__(self, inner: SessionChannel, sink: SessionEventSink) -> None:
        self._inner = inner
        self._sink = sink

    @property
    def session_id(self) -> str:
        return self._inner.session_id

    def emit(self, data: Any) -> None:
        self._persist(data)
        self._inner.emit(data)

    def is_active(self) -> bool:
        return self._inner.is_active()

    def close(self, *, cancelled: bool = False) -> None:
        self._inner.close(cancelled=cancelled)

    def supports_input(self) -> bool:
        return self._inner.supports_input()


class PersistingInputChannel(_PersistMixin, InputCapableChannel):

    def __init__(self, inner: InputCapableChannel, sink: SessionEventSink) -> None:
        self._inner = inner
        self._sink = sink

    @property
    def session_id(self) -> str:
        return self._inner.session_id

    def emit(self, data: Any) -> None:
        self._persist(data)
        self._inner.emit(data)

    def is_active(self) -> bool:
        return self._inner.is_active()

    def close(self, *, cancelled: bool = False) -> None:
        self._inner.close(cancelled=cancelled)

    def wait_for(self, request_id: str, timeout: float) -> Optional[dict]:
        return self._inner.wait_for(request_id, timeout)

    def submit(self, request_id: str, data: dict) -> None:
        self._inner.submit(request_id, data)


class PersistingChannelFactory(ChannelFactory):
    """Decorates another factory; readers/monitors pass through untouched."""

    def __init__(self, inner: ChannelFactory, sink: SessionEventSink) -> None:
        self._inner = inner
        self._sink = sink

    def create(self, session_id: str) -> SessionChannel:
        return PersistingChannel(self._inner.create(session_id), self._sink)

    def create_input_capable(self, session_id: str) -> Optional[InputCapableChannel]:
        channel = self._inner.create_input_capable(session_id)
        if channel is None:
            return None
        return PersistingInputChannel(channel, self._sink)

    def get_input_channel(self, session_id: str) -> Optional[Any]:
        return self._inner.get_input_channel(session_id)

    def create_reader(self, session_id: str):
        return self._inner.create_reader(session_id)

    def create_monitor(self):
        return self._inner.create_monitor()
