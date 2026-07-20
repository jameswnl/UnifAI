"""
Postgres-backed LangGraph checkpointer ([2.3], issue #13).

Gives the in-process (LangGraph) engine crash-survival without Temporal:
graph state is persisted after every node (super-step) keyed by the
session id (used as the LangGraph ``thread_id``). On restart, the resume
service (``mas.session.execution.resume``) re-runs non-terminal sessions,
and the executor detects the existing checkpoint and continues from the
last completed node instead of restarting the graph.

This is the harness-lite durability story — the 1–2 container profile
gets the same "a replica crash doesn't lose the workflow" guarantee that
Temporal provides for the distributed profile.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def build_langgraph_checkpointer(cfg) -> Optional[object]:
    """Return a set-up PostgresSaver, or None when checkpointing is off.

    Enabled only for the langgraph engine on the postgres backend with
    ``langgraph_checkpointing`` set. Any import/setup failure degrades to
    None (no checkpointing) rather than blocking startup.
    """
    if not getattr(cfg, "langgraph_checkpointing", False):
        return None
    if cfg.engine_name != "langgraph":
        return None
    if cfg.db_backend != "postgres":
        logger.warning("langgraph_checkpointing requires db_backend=postgres; "
                       "checkpointing disabled")
        return None

    try:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
        from langgraph.checkpoint.postgres import PostgresSaver

        # Dedicated pool: PostgresSaver requires autocommit + dict rows,
        # which differ from the document-store pool's settings.
        pool = ConnectionPool(
            cfg.postgres_dsn, min_size=1, max_size=10, open=True,
            kwargs={"autocommit": True, "row_factory": dict_row},
        )
        saver = PostgresSaver(pool)
        saver.setup()
        logger.info("LangGraph Postgres checkpointer enabled")
        return saver
    except Exception:  # noqa: BLE001 — degrade, don't block startup
        logger.exception("failed to build LangGraph checkpointer; disabled")
        return None
