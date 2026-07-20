"""MongoDB ScheduleStore ([4.1], issue #23)."""

from __future__ import annotations

from dataclasses import asdict
from typing import List, Optional

from pymongo import MongoClient

from mas.triggers.schedule import Schedule
from mas.triggers.schedule_store import ScheduleStore


class MongoScheduleStore(ScheduleStore):

    def __init__(self, mongodb_ip: str = "127.0.0.1", mongodb_port: int = 27017,
                 db_name: str = "unifai", coll_name: str = "schedules") -> None:
        client = MongoClient(f"mongodb://{mongodb_ip}:{mongodb_port}/")
        self._coll = client[db_name][coll_name]
        self._coll.create_index("schedule_id", unique=True, name="uq_schedule_id")

    def save(self, schedule: Schedule) -> None:
        self._coll.update_one(
            {"schedule_id": schedule.schedule_id},
            {"$set": asdict(schedule)}, upsert=True,
        )

    def get(self, schedule_id: str) -> Optional[Schedule]:
        doc = self._coll.find_one({"schedule_id": schedule_id}, {"_id": 0})
        return Schedule(**doc) if doc else None

    def list_all(self) -> List[Schedule]:
        return [Schedule(**doc) for doc in self._coll.find({}, {"_id": 0})]

    def delete(self, schedule_id: str) -> bool:
        return self._coll.delete_one({"schedule_id": schedule_id}).deleted_count > 0
