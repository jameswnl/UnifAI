"""PostgreSQL SessionRepository (plan item [1.1], issue #7).

Core session persistence for the harness profile. The platform-analytics
methods (activity series, system analytics dashboards) are only reachable
through the statistics endpoints, which the harness profile disables —
they raise NotImplementedError here until someone needs them on Postgres.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from mas.core.dto import GroupedCount
from mas.core.identity import Identity
from mas.session.domain.models import SessionChat, SystemAnalyticsData, TimeSeriesPoint
from mas.session.domain.session_record import SessionRecord
from mas.session.repository.repository import SessionRepository

from outbound.postgres.db import PgCollection, doc_filter_clause

_ANALYTICS_MSG = (
    "platform analytics are not implemented on the postgres backend "
    "(statistics endpoints are platform-profile only; use the mongo backend)"
)


class PgSessionRepository(SessionRepository):

    def __init__(self, dsn: str, table: str = "workflow_sessions") -> None:
        self._col = PgCollection(dsn, table)

    # ── core CRUD ────────────────────────────────────────────────────

    def save(self, record: SessionRecord) -> None:
        self._col.upsert(record.run_id, record.model_dump(mode="json"),
                         identity=record.identity)

    def fetch(self, run_id: str) -> SessionRecord:
        doc = self._col.get(run_id)
        if not doc:
            raise KeyError(f"No session for {run_id}")
        return SessionRecord.model_validate(doc)

    def fetch_chat(self, run_id: str) -> SessionChat:
        rows = self._col.execute(
            """
            SELECT doc #> '{graph_state,messages}',
                   doc #> '{graph_state,output}',
                   doc ->> 'status',
                   doc #>> '{metadata,status_message}'
            FROM {table} WHERE pk = %s
            """,
            (run_id,),
        )
        if not rows:
            raise KeyError(f"No session for {run_id}")
        messages, output, status, status_message = rows[0]
        return SessionChat.model_validate({
            "messages": messages or [],
            "output": output if output is not None else "",
            "status": status,
            "status_message": status_message,
        })

    def list_runs(self, identity: Identity) -> List[str]:
        return [d["run_id"] for d in self._col.find_by_identity(identity)]

    def list_docs(self, identity: Identity) -> List[Mapping[str, Any]]:
        return self._col.find_by_identity(identity)

    def delete(self, run_id: str) -> bool:
        return self._col.delete(run_id)

    def delete_by_identity(self, identity: Identity) -> int:
        return self._col.delete_by_identity(identity)

    # ── owner-scoped statistics ──────────────────────────────────────

    def count(self, identity: Identity, filter: Dict[str, Any]) -> int:
        return self._col.count_where(identity, filter)

    def group_count(self, identity: Identity, group_by: List[str],
                    filter: Dict[str, Any] = None) -> List[GroupedCount]:
        return self._group_count(identity, group_by, filter)

    # ── system-wide analytics (platform profile only) ────────────────

    def count_system(self, since: Optional[datetime] = None) -> int:
        sql = "SELECT count(*) FROM {table}"
        params: tuple = ()
        if since is not None:
            sql += " WHERE updated_at >= %s"
            params = (since,)
        return self._col.execute(sql, params)[0][0]

    def get_distinct_identities(self, since: Optional[datetime] = None) -> List[Dict[str, str]]:
        sql = "SELECT DISTINCT identity_type, identity_id FROM {table}"
        params: tuple = ()
        if since is not None:
            sql += " WHERE updated_at >= %s"
            params = (since,)
        return [{"type": t, "id": i} for t, i in self._col.execute(sql, params)]

    def group_count_system(self, group_by: List[str],
                           filter: Dict[str, Any] = None,
                           since: Optional[datetime] = None) -> List[GroupedCount]:
        return self._group_count(None, group_by, filter)

    def get_session_activity_series(self, *args, **kwargs) -> List[TimeSeriesPoint]:
        raise NotImplementedError(_ANALYTICS_MSG)

    def get_system_analytics(self, *args, **kwargs) -> SystemAnalyticsData:
        raise NotImplementedError(_ANALYTICS_MSG)

    # ── helpers ──────────────────────────────────────────────────────

    def _group_count(self, identity: Optional[Identity], group_by: List[str],
                     filter: Optional[Dict[str, Any]]) -> List[GroupedCount]:
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
        result: List[GroupedCount] = []
        for row in rows:
            *values, cnt = row
            result.append(GroupedCount(
                fields=dict(zip(group_by, values)), count=cnt))
        return result
