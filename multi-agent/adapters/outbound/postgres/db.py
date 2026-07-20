"""
PostgreSQL document store helper (plan item [1.1], issue #7).

One table per collection, mirroring the Mongo document layout:

    pk            TEXT PRIMARY KEY   -- run_id / blueprint_id / rid / key
    identity_type TEXT               -- extracted for indexed owner scoping
    identity_id   TEXT
    doc           JSONB              -- full model_dump(mode="json") document
    created_at    TIMESTAMPTZ
    updated_at    TIMESTAMPTZ

Documents keep the exact same shape as the Mongo backend so the two
backends stay interchangeable behind the repository ports.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from psycopg_pool import ConnectionPool
from psycopg.types.json import Jsonb

from mas.core.identity import Identity

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    pk            TEXT PRIMARY KEY,
    identity_type TEXT NOT NULL DEFAULT '',
    identity_id   TEXT NOT NULL DEFAULT '',
    doc           JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS {table}_identity_idx
    ON {table} (identity_type, identity_id);
"""

_pools: Dict[str, ConnectionPool] = {}


def get_pool(dsn: str) -> ConnectionPool:
    """Return (and cache) a connection pool for *dsn*."""
    pool = _pools.get(dsn)
    if pool is None:
        pool = ConnectionPool(dsn, min_size=1, max_size=10, open=True)
        _pools[dsn] = pool
    return pool


def identity_pair(identity: Optional[Identity]) -> Tuple[str, str]:
    if identity is None:
        return "", ""
    return identity.type.value, identity.id


class PgCollection:
    """Minimal Mongo-flavoured document API over one JSONB table."""

    def __init__(self, dsn: str, table: str) -> None:
        if not table.replace("_", "").isalnum():
            raise ValueError(f"invalid table name: {table}")
        self._pool = get_pool(dsn)
        self._table = table
        with self._pool.connection() as conn:
            conn.execute(_TABLE_DDL.format(table=table))

    # ── low-level helpers ────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> list:
        # Literal replacement, not str.format(): SQL legitimately contains
        # JSONB path braces like '{graph_state,messages}'.
        with self._pool.connection() as conn:
            cur = conn.execute(sql.replace("{table}", self._table), params)
            if cur.description is None:
                return []
            return cur.fetchall()

    def rowcount(self, sql: str, params: tuple = ()) -> int:
        with self._pool.connection() as conn:
            cur = conn.execute(sql.replace("{table}", self._table), params)
            return cur.rowcount

    # ── document operations ──────────────────────────────────────────

    def upsert(self, pk: str, doc: Dict[str, Any],
               identity: Optional[Identity] = None) -> None:
        itype, iid = identity_pair(identity)
        self.execute(
            """
            INSERT INTO {table} (pk, identity_type, identity_id, doc)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (pk) DO UPDATE
                SET doc = EXCLUDED.doc,
                    identity_type = EXCLUDED.identity_type,
                    identity_id = EXCLUDED.identity_id,
                    updated_at = now()
            """,
            (pk, itype, iid, Jsonb(_jsonable(doc))),
        )

    def insert(self, pk: str, doc: Dict[str, Any],
               identity: Optional[Identity] = None) -> None:
        itype, iid = identity_pair(identity)
        self.execute(
            "INSERT INTO {table} (pk, identity_type, identity_id, doc)"
            " VALUES (%s, %s, %s, %s)",
            (pk, itype, iid, Jsonb(_jsonable(doc))),
        )

    def get(self, pk: str) -> Optional[Dict[str, Any]]:
        rows = self.execute("SELECT doc FROM {table} WHERE pk = %s", (pk,))
        return rows[0][0] if rows else None

    def delete(self, pk: str) -> bool:
        return self.rowcount("DELETE FROM {table} WHERE pk = %s", (pk,)) > 0

    def exists(self, pk: str) -> bool:
        rows = self.execute("SELECT 1 FROM {table} WHERE pk = %s LIMIT 1", (pk,))
        return bool(rows)

    # ── identity-scoped operations ───────────────────────────────────

    def _identity_clause(self, identity: Optional[Identity]) -> Tuple[str, tuple]:
        if identity is None:
            return "TRUE", ()
        itype, iid = identity_pair(identity)
        return "identity_type = %s AND identity_id = %s", (itype, iid)

    def find_by_identity(self, identity: Optional[Identity],
                         order_by: str = "updated_at DESC",
                         limit: Optional[int] = None,
                         offset: int = 0) -> List[Dict[str, Any]]:
        clause, params = self._identity_clause(identity)
        sql = f"SELECT doc FROM {{table}} WHERE {clause} ORDER BY {order_by}"
        if limit is not None:
            sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
        return [r[0] for r in self.execute(sql, params)]

    def delete_by_identity(self, identity: Identity) -> int:
        clause, params = self._identity_clause(identity)
        return self.rowcount(f"DELETE FROM {{table}} WHERE {clause}", params)

    def count_where(self, identity: Optional[Identity] = None,
                    doc_filter: Optional[Dict[str, Any]] = None) -> int:
        """Count rows scoped by identity and flat/dotted doc-field equality."""
        clause, params = self._identity_clause(identity)
        extra, extra_params = doc_filter_clause(doc_filter)
        rows = self.execute(
            f"SELECT count(*) FROM {{table}} WHERE {clause}{extra}",
            params + extra_params,
        )
        return rows[0][0]


def doc_filter_clause(doc_filter: Optional[Dict[str, Any]]) -> Tuple[str, tuple]:
    """Translate a flat/dot-notation equality filter into JSONB predicates.

    Supports the subset of Mongo-style filters the services actually use:
    ``{"status": "FAILED", "metadata.foo": "bar"}``. Anything fancier
    belongs in a dedicated SQL method on the repository.
    """
    if not doc_filter:
        return "", ()
    clauses: List[str] = []
    params: List[Any] = []
    for key, value in doc_filter.items():
        if isinstance(value, dict):
            raise NotImplementedError(
                f"operator filters are not supported by the postgres backend: {key}={value!r}"
            )
        path = "{" + ",".join(key.split(".")) + "}"
        clauses.append("doc #>> %s = %s")
        params.append(path)
        params.append(value if isinstance(value, str) else json.dumps(value))
    return " AND " + " AND ".join(clauses), tuple(params)


def _jsonable(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Round-trip through json to normalise datetimes etc. defensively."""
    return json.loads(json.dumps(doc, default=str))
