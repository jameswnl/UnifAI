"""Unit tests for triggers + scheduler ([4.1], issue #23)."""

from datetime import datetime, timedelta, timezone

import pytest

from mas.triggers.schedule import Schedule, compute_next_run, is_due
from mas.triggers.scheduler import Scheduler
from mas.triggers.schedule_store import ScheduleStore


class MemScheduleStore(ScheduleStore):
    def __init__(self):
        self.items = {}

    def save(self, schedule):
        self.items[schedule.schedule_id] = schedule

    def get(self, schedule_id):
        return self.items.get(schedule_id)

    def list_all(self):
        return list(self.items.values())

    def delete(self, schedule_id):
        return self.items.pop(schedule_id, None) is not None


class FakeTriggers:
    def __init__(self):
        self.launches = []

    def launch(self, blueprint_id, inputs, source=""):
        self.launches.append((blueprint_id, inputs, source))
        return "run-x"


# ── schedule model ───────────────────────────────────────────────────

@pytest.mark.unit
def test_schedule_requires_cron_or_interval():
    with pytest.raises(ValueError):
        Schedule(blueprint_id="bp")


@pytest.mark.unit
def test_interval_next_run():
    s = Schedule(blueprint_id="bp", interval_seconds=300)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert compute_next_run(s, now) == now + timedelta(seconds=300)


@pytest.mark.unit
def test_is_due():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    past = Schedule(blueprint_id="bp", interval_seconds=60,
                    next_run=(now - timedelta(seconds=1)).isoformat())
    future = Schedule(blueprint_id="bp", interval_seconds=60,
                      next_run=(now + timedelta(seconds=60)).isoformat())
    disabled = Schedule(blueprint_id="bp", interval_seconds=60, enabled=False,
                        next_run=(now - timedelta(seconds=1)).isoformat())
    assert is_due(past, now) is True
    assert is_due(future, now) is False
    assert is_due(disabled, now) is False


# ── scheduler tick ───────────────────────────────────────────────────

@pytest.mark.unit
def test_tick_activates_then_fires():
    store = MemScheduleStore()
    triggers = FakeTriggers()
    t = [datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)]
    sched = Scheduler(store, triggers, clock=lambda: t[0])

    store.save(Schedule(blueprint_id="bp", interval_seconds=300,
                        schedule_id="s1"))

    # First tick: computes next_run (activation), does not fire yet.
    assert sched.tick() == 0
    assert triggers.launches == []
    assert store.get("s1").next_run is not None

    # Advance past next_run → fires.
    t[0] = t[0] + timedelta(seconds=301)
    assert sched.tick() == 1
    assert triggers.launches[0][0] == "bp"
    assert triggers.launches[0][2] == "schedule:s1"
    # next_run advanced past now
    assert datetime.fromisoformat(store.get("s1").next_run) > t[0]


@pytest.mark.unit
def test_tick_skips_disabled():
    store = MemScheduleStore()
    triggers = FakeTriggers()
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    store.save(Schedule(blueprint_id="bp", interval_seconds=60, enabled=False,
                        schedule_id="s2",
                        next_run=(now - timedelta(seconds=1)).isoformat()))
    assert Scheduler(store, triggers, clock=lambda: now).tick() == 0


# ── trigger service launch strategy ──────────────────────────────────

@pytest.mark.unit
def test_launch_uses_submit_when_available():
    from mas.triggers.service import TriggerService

    class Sessions:
        def __init__(self):
            self.submitted = None

        def create(self, identity, blueprint_id, metadata):
            return "run-1"

        def submit(self, run_id, inputs):
            self.submitted = (run_id, inputs)

    sessions = Sessions()
    run_id = TriggerService(sessions).launch("bp", {"k": "v"}, source="webhook")
    assert run_id == "run-1"
    assert sessions.submitted == ("run-1", {"k": "v"})


@pytest.mark.unit
def test_launch_falls_back_to_thread_without_engine():
    import threading
    from mas.triggers.service import TriggerService

    done = threading.Event()

    class Sessions:
        def create(self, identity, blueprint_id, metadata):
            return "run-2"

        def submit(self, run_id, inputs):
            raise TypeError("no background engine")

        def run(self, run_id, inputs, stream=False):
            done.set()

    run_id = TriggerService(Sessions()).launch("bp", {})
    assert run_id == "run-2"
    assert done.wait(timeout=2.0), "background thread did not run session"
