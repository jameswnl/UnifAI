"""MongoDB SessionEventSink (plan item [1.2], issue #8)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from pymongo import ASCENDING, MongoClient

from mas.session.storage.event_sink import SessionEventSink


class MongoSessionEventStore(SessionEventSink):

    def __init__(self, mongodb_ip: str = "127.0.0.1", mongodb_port: int = 27017,
                 db_name: str = "unifai", coll_name: str = "session_events") -> None:
        client = MongoClient(f"mongodb://{mongodb_ip}:{mongodb_port}/")
        self._coll = client[db_name][coll_name]
        self._coll.create_index(
            [("session_id", ASCENDING), ("seq", ASCENDING)],
            name="session_seq_idx",
        )

    def append(self, session_id: str, event: Dict[str, Any]) -> None:
        self._coll.insert_one({
            "session_id": session_id,
            "seq": self._coll.count_documents({"session_id": session_id}),
            "event": json.loads(json.dumps(event, default=str)),
            "ts": datetime.now(timezone.utc),
        })

    def list_events(self, session_id: str, offset: int = 0,
                    limit: int = 1000) -> List[Dict[str, Any]]:
        cursor = (self._coll.find({"session_id": session_id}, {"_id": 0, "event": 1})
                  .sort("seq", ASCENDING).skip(offset).limit(limit))
        return [doc["event"] for doc in cursor]

    def count(self, session_id: str) -> int:
        return self._coll.count_documents({"session_id": session_id})

    def delete_session(self, session_id: str) -> int:
        return self._coll.delete_many({"session_id": session_id}).deleted_count
