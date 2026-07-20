"""PostgreSQL SessionEventSink (plan item [1.2], issue #8)."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from psycopg.types.json import Jsonb

from mas.session.storage.event_sink import SessionEventSink

from outbound.postgres.db import get_pool

_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id TEXT NOT NULL,
    event      JSONB NOT NULL,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS {table}_session_idx ON {table} (session_id, id);
"""


class PgSessionEventStore(SessionEventSink):

    def __init__(self, dsn: str, table: str = "session_events") -> None:
        if not table.replace("_", "").isalnum():
            raise ValueError(f"invalid table name: {table}")
        self._pool = get_pool(dsn)
        self._table = table
        with self._pool.connection() as conn:
            conn.execute(_DDL.replace("{table}", table))

    def append(self, session_id: str, event: Dict[str, Any]) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                f"INSERT INTO {self._table} (session_id, event) VALUES (%s, %s)",
                (session_id, Jsonb(json.loads(json.dumps(event, default=str)))),
            )

    def list_events(self, session_id: str, offset: int = 0,
                    limit: int = 1000) -> List[Dict[str, Any]]:
        with self._pool.connection() as conn:
            cur = conn.execute(
                f"SELECT event FROM {self._table} WHERE session_id = %s"
                f" ORDER BY id LIMIT %s OFFSET %s",
                (session_id, limit, offset),
            )
            return [row[0] for row in cur.fetchall()]

    def count(self, session_id: str) -> int:
        with self._pool.connection() as conn:
            cur = conn.execute(
                f"SELECT count(*) FROM {self._table} WHERE session_id = %s",
                (session_id,),
            )
            return cur.fetchone()[0]

    def delete_session(self, session_id: str) -> int:
        with self._pool.connection() as conn:
            cur = conn.execute(
                f"DELETE FROM {self._table} WHERE session_id = %s",
                (session_id,),
            )
            return cur.rowcount
