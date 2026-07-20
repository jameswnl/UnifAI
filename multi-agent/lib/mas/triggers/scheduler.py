"""
Scheduler loop ([4.1], issue #23).

A background thread that periodically wakes, launches any due schedules
via the TriggerService, and advances their next_run. Lightweight and
self-contained — the light (Podman) profile gets cron/interval triggers
without Temporal. The Temporal profile could instead use Temporal
Schedules; both share the Schedule model and store.

``tick`` is separated from the loop so it is unit-testable with an
injected clock.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable

from mas.triggers.schedule import compute_next_run, is_due

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, store, trigger_service, poll_seconds: int = 30,
                 clock: Callable[[], datetime] = None) -> None:
        self._store = store
        self._triggers = trigger_service
        self._poll_seconds = poll_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._stop = threading.Event()

    def tick(self) -> int:
        """Launch all due schedules once. Returns the count launched."""
        now = self._clock()
        launched = 0
        for schedule in self._store.list_all():
            # Newly-saved schedules have next_run computed at save time; a
            # missing next_run means 'compute from now' (first activation).
            if schedule.next_run is None:
                schedule.next_run = compute_next_run(schedule, now).isoformat()
                self._store.save(schedule)
                continue
            if is_due(schedule, now):
                try:
                    self._triggers.launch(
                        schedule.blueprint_id, schedule.inputs,
                        source=f"schedule:{schedule.schedule_id}")
                    launched += 1
                except Exception:  # noqa: BLE001 — one bad schedule ≠ stop
                    logger.exception("schedule %s launch failed",
                                     schedule.schedule_id)
                schedule.last_run = now.isoformat()
                schedule.next_run = compute_next_run(schedule, now).isoformat()
                self._store.save(schedule)
        return launched

    def start(self) -> None:
        threading.Thread(target=self._loop, name="scheduler",
                         daemon=True).start()
        logger.info("scheduler started (poll=%ss)", self._poll_seconds)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._poll_seconds):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 — loop must survive
                logger.exception("scheduler tick failed")
