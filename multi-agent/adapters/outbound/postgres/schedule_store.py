"""PostgreSQL ScheduleStore ([4.1], issue #23)."""

from __future__ import annotations

from dataclasses import asdict
from typing import List, Optional

from mas.triggers.schedule import Schedule
from mas.triggers.schedule_store import ScheduleStore

from outbound.postgres.db import PgCollection


class PgScheduleStore(ScheduleStore):

    def __init__(self, dsn: str, table: str = "schedules") -> None:
        self._col = PgCollection(dsn, table)

    def save(self, schedule: Schedule) -> None:
        self._col.upsert(schedule.schedule_id, asdict(schedule))

    def get(self, schedule_id: str) -> Optional[Schedule]:
        doc = self._col.get(schedule_id)
        return Schedule(**doc) if doc else None

    def list_all(self) -> List[Schedule]:
        rows = self._col.execute("SELECT doc FROM {table}")
        return [Schedule(**r[0]) for r in rows]

    def delete(self, schedule_id: str) -> bool:
        return self._col.delete(schedule_id)
