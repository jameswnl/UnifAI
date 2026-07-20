"""
Schedule model + next-run computation ([4.1], issue #23).

A schedule launches a blueprint on a recurring cadence — either a cron
expression (``cron``) or a fixed interval (``interval_seconds``). The
next-run computation is a pure function so it is unit-testable without a
clock or a running loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import uuid4


@dataclass
class Schedule:
    blueprint_id: str
    cron: Optional[str] = None
    interval_seconds: Optional[int] = None
    inputs: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    schedule_id: str = field(default_factory=lambda: uuid4().hex)
    next_run: Optional[str] = None       # ISO 8601 UTC
    last_run: Optional[str] = None

    def __post_init__(self):
        if not self.cron and not self.interval_seconds:
            raise ValueError("schedule needs either 'cron' or 'interval_seconds'")


def compute_next_run(schedule: Schedule, after: datetime) -> datetime:
    """Next fire time strictly after *after* (a tz-aware UTC datetime)."""
    if schedule.interval_seconds:
        return after + timedelta(seconds=schedule.interval_seconds)

    # cron — croniter is optional; a clear error beats a silent misfire.
    try:
        from croniter import croniter
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "cron schedules require the 'croniter' package; use interval_seconds"
        ) from e
    return croniter(schedule.cron, after).get_next(datetime).astimezone(timezone.utc)


def is_due(schedule: Schedule, now: datetime) -> bool:
    if not schedule.enabled or not schedule.next_run:
        return False
    return datetime.fromisoformat(schedule.next_run) <= now
