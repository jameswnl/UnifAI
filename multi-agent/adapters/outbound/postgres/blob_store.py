"""PostgreSQL LargePayloadStore ([2.4], issue #14)."""

from __future__ import annotations

from typing import Optional

from mas.core.large_payload import LargePayloadStore

from outbound.postgres.db import get_pool

_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    key   TEXT PRIMARY KEY,
    data  BYTEA NOT NULL,
    ts    TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class PgLargePayloadStore(LargePayloadStore):

    def __init__(self, dsn: str, table: str = "large_payloads") -> None:
        if not table.replace("_", "").isalnum():
            raise ValueError(f"invalid table name: {table}")
        self._pool = get_pool(dsn)
        self._table = table
        with self._pool.connection() as conn:
            conn.execute(_DDL.replace("{table}", table))

    def put(self, key: str, data: bytes) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                f"INSERT INTO {self._table} (key, data) VALUES (%s, %s)"
                f" ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data",
                (key, data),
            )

    def get(self, key: str) -> Optional[bytes]:
        with self._pool.connection() as conn:
            cur = conn.execute(
                f"SELECT data FROM {self._table} WHERE key = %s", (key,))
            row = cur.fetchone()
            return bytes(row[0]) if row else None

    def delete(self, key: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(f"DELETE FROM {self._table} WHERE key = %s", (key,))
