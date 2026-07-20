"""Unit tests for the persisting channel decorator ([1.2], issue #8)."""

from typing import Any, Dict, List

import pytest

from mas.core.channels.persisting import (
    PersistingChannel,
    PersistingChannelFactory,
)
from mas.core.channels.protocols import ChannelFactory, SessionChannel
from mas.session.storage.event_sink import SessionEventSink


class FakeSink(SessionEventSink):
    def __init__(self):
        self.events: Dict[str, List[dict]] = {}

    def append(self, session_id, event):
        self.events.setdefault(session_id, []).append(event)

    def list_events(self, session_id, offset=0, limit=1000):
        return self.events.get(session_id, [])[offset:offset + limit]

    def count(self, session_id):
        return len(self.events.get(session_id, []))

    def delete_session(self, session_id):
        return len(self.events.pop(session_id, []))


class FailingSink(FakeSink):
    def append(self, session_id, event):
        raise RuntimeError("db down")


class FakeChannel(SessionChannel):
    def __init__(self, session_id):
        self._sid = session_id
        self.emitted: List[Any] = []
        self.closed = False

    @property
    def session_id(self):
        return self._sid

    def emit(self, data):
        self.emitted.append(data)

    def is_active(self):
        return not self.closed

    def close(self, *, cancelled=False):
        self.closed = True


class FakeFactory(ChannelFactory):
    def create(self, session_id):
        return FakeChannel(session_id)

    def create_input_capable(self, session_id):
        return None

    def get_input_channel(self, session_id):
        return None

    def create_reader(self, session_id):
        return None

    def create_monitor(self):
        return None


@pytest.mark.unit
def test_emit_persists_and_streams():
    sink = FakeSink()
    factory = PersistingChannelFactory(FakeFactory(), sink)
    channel = factory.create("s1")

    channel.emit({"type": "node_started", "uid": "n1"})
    channel.emit({"type": "node_output", "uid": "n1", "output": "hi"})

    inner = channel._inner
    assert len(inner.emitted) == 2
    assert sink.count("s1") == 2
    assert sink.list_events("s1")[0]["type"] == "node_started"


@pytest.mark.unit
def test_sink_failure_does_not_break_streaming():
    channel = PersistingChannel(FakeChannel("s2"), FailingSink())
    channel.emit({"type": "x"})
    assert channel._inner.emitted == [{"type": "x"}]


@pytest.mark.unit
def test_non_dict_events_are_wrapped():
    sink = FakeSink()
    channel = PersistingChannel(FakeChannel("s3"), sink)
    channel.emit("plain string")
    assert sink.list_events("s3") == [{"data": "plain string"}]


@pytest.mark.unit
def test_channel_passthrough():
    sink = FakeSink()
    channel = PersistingChannel(FakeChannel("s4"), sink)
    assert channel.session_id == "s4"
    assert channel.is_active()
    channel.close()
    assert not channel.is_active()
