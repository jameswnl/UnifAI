"""PostgreSQL ResourceRepository (plan item [1.1], issue #7)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mas.core.dto import GroupedCount
from mas.core.identity import Identity
from mas.resources.models import Resource, ResourceQuery
from mas.resources.repository.base import ResourceRepository

from outbound.postgres.db import PgCollection, doc_filter_clause


class PgResourceRepository(ResourceRepository):

    def __init__(self, dsn: str, table: str = "resources") -> None:
        self._col = PgCollection(dsn, table)

    # ── CRUD ─────────────────────────────────────────────────────────

    def save(self, doc: Resource) -> str:
        self._col.insert(doc.rid, doc.model_dump(mode="json"),
                         identity=doc.identity)
        return doc.rid

    def update(self, doc: Resource) -> str:
        if not self._col.exists(doc.rid):
            raise KeyError(f"No document found with rid: {doc.rid}")
        self._col.upsert(doc.rid, doc.model_dump(mode="json"),
                         identity=doc.identity)
        return doc.rid

    def get(self, rid: str) -> Resource:
        raw = self._col.get(rid)
        if not raw:
            raise KeyError(rid)
        return Resource(**raw)

    def delete(self, rid: str) -> None:
        self._col.delete(rid)

    def delete_by_identity(self, identity: Identity) -> int:
        return self._col.delete_by_identity(identity)

    def find_by_name(self, identity: Identity, category: str,
                     type: str, name: str) -> Optional[Resource]:
        clause, params = self._col._identity_clause(identity)
        rows = self._col.execute(
            f"""
            SELECT doc FROM {{table}}
            WHERE {clause}
              AND doc->>'category' = %s AND doc->>'type' = %s
              AND doc->>'name' = %s
            LIMIT 1
            """,
            params + (category, type, name),
        )
        return Resource(**rows[0][0]) if rows else None

    # ── queries ──────────────────────────────────────────────────────

    _SORT_FIELDS = {"created", "updated", "name", "type", "category"}

    def _query_clause(self, query: ResourceQuery):
        clause, params = self._col._identity_clause(query.identity)
        if query.category:
            clause += " AND doc->>'category' = %s"
            params += (query.category.value,)
        if query.type:
            clause += " AND doc->>'type' = %s"
            params += (query.type,)
        return clause, params

    def find_resources(self, query: ResourceQuery) -> List[Resource]:
        clause, params = self._query_clause(query)
        sort_by = query.sort_by if query.sort_by in self._SORT_FIELDS else "created"
        direction = "DESC" if query.sort_order == "desc" else "ASC"
        rows = self._col.execute(
            f"""
            SELECT doc FROM {{table}} WHERE {clause}
            ORDER BY doc->>'{sort_by}' {direction}
            LIMIT {int(query.limit)} OFFSET {int(query.offset)}
            """,
            params,
        )
        return [Resource(**r[0]) for r in rows]

    def count_resources(self, query: ResourceQuery) -> int:
        clause, params = self._query_clause(query)
        rows = self._col.execute(
            f"SELECT count(*) FROM {{table}} WHERE {clause}", params)
        return rows[0][0]

    def count(self, identity: Identity, filter: dict | None = None) -> int:
        return self._col.count_where(identity, filter)

    def meta(self, rid: str) -> tuple[str, str]:
        rows = self._col.execute(
            "SELECT doc->>'category', doc->>'type' FROM {table} WHERE pk = %s",
            (rid,),
        )
        if not rows:
            raise KeyError(rid)
        return rows[0][0], rows[0][1]

    def count_nested(self, rid: str) -> int:
        # Mongo used a regex over cfg_dict; textual containment is equivalent
        rows = self._col.execute(
            "SELECT count(*) FROM {table} WHERE (doc->'cfg_dict')::text LIKE %s",
            (f"%{rid}%",),
        )
        return rows[0][0]

    def list_nested_usage(self, rid: str) -> List[str]:
        rows = self._col.execute(
            "SELECT pk FROM {table} WHERE doc->'nested_refs' ? %s", (rid,))
        return [r[0] for r in rows]

    def exists(self, rid: str) -> bool:
        return self._col.exists(rid)

    def count_by_config_field(self, identity: Identity, field: str,
                              value: str, exclude_rid: str = "") -> int:
        clause, params = self._col._identity_clause(identity)
        path = "{cfg_dict," + ",".join(field.split(".")) + "}"
        sql = f"SELECT count(*) FROM {{table}} WHERE {clause} AND doc #>> %s = %s"
        params += (path, value)
        if exclude_rid:
            sql += " AND pk != %s"
            params += (exclude_rid,)
        return self._col.execute(sql, params)[0][0]

    def group_count(self, identity: Identity, group_by: List[str],
                    filter: Dict[str, Any] | None = None) -> List[GroupedCount]:
        clause, params = self._col._identity_clause(identity)
        extra, extra_params = doc_filter_clause(filter)
        paths = tuple("{" + ",".join(f.split(".")) + "}" for f in group_by)
        select = ", ".join("doc #>> %s" for _ in group_by)
        positions = ", ".join(str(i + 1) for i in range(len(group_by)))
        rows = self._col.execute(
            f"SELECT {select}, count(*) FROM {{table}} "
            f"WHERE {clause}{extra} GROUP BY {positions}",
            paths + params + extra_params,
        )
        return [GroupedCount(fields=dict(zip(group_by, row[:-1])), count=row[-1])
                for row in rows]
