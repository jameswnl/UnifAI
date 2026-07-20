"""PostgreSQL BlueprintRepository (plan item [1.1], issue #7)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from psycopg.types.json import Jsonb

from mas.blueprints.models.blueprint import (
    BlueprintDocument,
    BlueprintDraft,
    BlueprintSummary,
)
from mas.blueprints.models.prompt_shortcuts import PromptShortcuts
from mas.blueprints.repository.repository import BlueprintRepository
from mas.core.enums import ResourceCategory
from mas.core.identity import Identity

from outbound.postgres.db import PgCollection, _jsonable


class PgBlueprintRepository(BlueprintRepository):

    def __init__(self, dsn: str, table: str = "blueprints") -> None:
        self._col = PgCollection(dsn, table)

    # ── CRUD ─────────────────────────────────────────────────────────

    def save(self, identity: Identity, spec: BlueprintDraft,
             rid_refs: list[str], metadata: Dict[str, Any] = {}) -> str:
        new_id = str(uuid4())
        now = datetime.now(timezone.utc)
        doc = {
            "blueprint_id": new_id,
            "identity": identity.model_dump(mode="json"),
            "created_at": getattr(spec, "created_at", now),
            "updated_at": now,
            "spec_dict": spec.model_dump(mode="json"),
            "rid_refs": rid_refs,
            "metadata": metadata,
        }
        self._col.insert(new_id, doc, identity=identity)
        return new_id

    def update(self, *, blueprint_id: str, spec: BlueprintDraft,
               rid_refs: list[str]) -> bool:
        patch = {
            "spec_dict": spec.model_dump(mode="json"),
            "rid_refs": rid_refs,
            "updated_at": datetime.now(timezone.utc),
        }
        return self._col.rowcount(
            "UPDATE {table} SET doc = doc || %s, updated_at = now() WHERE pk = %s",
            (Jsonb(_jsonable(patch)), blueprint_id),
        ) == 1

    def set_metadata(self, *, blueprint_id: str, metadata: Dict[str, Any]) -> bool:
        if not isinstance(metadata, dict):
            raise ValueError(f"metadata must be a dictionary, got: {type(metadata)}")
        # Key-level merge into doc.metadata (mirrors Mongo's dot-notation $set)
        patch = {"updated_at": str(datetime.now(timezone.utc))}
        return self._col.rowcount(
            """
            UPDATE {table}
            SET doc = jsonb_set(doc || %s, '{metadata}',
                                coalesce(doc->'metadata', '{}'::jsonb) || %s),
                updated_at = now()
            WHERE pk = %s
            """,
            (Jsonb(patch), Jsonb(_jsonable(metadata)), blueprint_id),
        ) == 1

    def set_prompt_shortcuts(self, *, blueprint_id: str,
                             shortcuts: PromptShortcuts) -> bool:
        now = str(datetime.now(timezone.utc))
        storage = shortcuts.to_storage()
        if storage:
            sql = """
                UPDATE {table}
                SET doc = jsonb_set(doc, '{spec_dict,prompt_shortcuts}', %s)
                          || jsonb_build_object('updated_at', %s::text),
                    updated_at = now()
                WHERE pk = %s
            """
            params = (Jsonb(_jsonable(storage)), now, blueprint_id)
        else:
            sql = """
                UPDATE {table}
                SET doc = (doc #- '{spec_dict,prompt_shortcuts}')
                          || jsonb_build_object('updated_at', %s::text),
                    updated_at = now()
                WHERE pk = %s
            """
            params = (now, blueprint_id)
        return self._col.rowcount(sql, params) >= 1

    def load(self, blueprint_id: str) -> BlueprintDocument:
        doc = self._col.get(blueprint_id)
        if not doc:
            raise KeyError(f"No blueprint {blueprint_id}")
        return BlueprintDocument.model_validate(doc)

    def delete(self, blueprint_id: str) -> bool:
        return self._col.delete(blueprint_id)

    def delete_by_identity(self, identity: Identity) -> int:
        return self._col.delete_by_identity(identity)

    def exists(self, blueprint_id: str) -> bool:
        return self._col.exists(blueprint_id)

    def load_many(self, blueprint_ids: List[str]) -> List[BlueprintDocument]:
        if not blueprint_ids:
            return []
        rows = self._col.execute(
            "SELECT doc FROM {table} WHERE pk = ANY(%s)", (blueprint_ids,))
        return [BlueprintDocument.model_validate(r[0]) for r in rows]

    # ── listing ──────────────────────────────────────────────────────

    def list_ids(self, *, identity: Optional[Identity] = None,
                 skip: int = 0, limit: int = 100,
                 sort_desc: bool = True) -> List[str]:
        docs = self._col.find_by_identity(
            identity,
            order_by=f"updated_at {'DESC' if sort_desc else 'ASC'}",
            limit=limit, offset=skip)
        return [d["blueprint_id"] for d in docs]

    def list_docs(self, identity: Optional[Identity] = None,
                  skip: int = 0, limit: int = 100,
                  sort_desc: bool = True) -> List[BlueprintDocument]:
        docs = self._col.find_by_identity(
            identity,
            order_by=f"updated_at {'DESC' if sort_desc else 'ASC'}",
            limit=limit, offset=skip)
        return [BlueprintDocument.model_validate(d) for d in docs]

    def list_summaries(self, identity: Optional[Identity] = None,
                       skip: int = 0, limit: int = 100,
                       sort_desc: bool = True) -> List[BlueprintSummary]:
        docs = self._col.find_by_identity(
            identity,
            order_by=f"updated_at {'DESC' if sort_desc else 'ASC'}",
            limit=limit, offset=skip)
        summaries = []
        for doc in docs:
            spec = doc.get("spec_dict", {})
            summaries.append(BlueprintSummary(
                blueprint_id=doc["blueprint_id"],
                identity=Identity(**doc["identity"]),
                name=spec.get("name", "Untitled blueprint"),
                description=spec.get("description", ""),
                created_at=doc["created_at"],
                updated_at=doc["updated_at"],
                metadata=doc.get("metadata", {}),
            ))
        return summaries

    # ── usage queries ────────────────────────────────────────────────

    def list_direct_usage(self, rid: str) -> List[str]:
        rows = self._col.execute(
            "SELECT doc->>'blueprint_id' FROM {table} WHERE doc->'rid_refs' ? %s",
            (rid,),
        )
        return [r[0] for r in rows]

    def count_usage(self, rid: str) -> int:
        # Mirrors the Mongo $or over spec_dict.<cat>.rid / .config.rid by
        # searching resource entries in each category array.
        clauses = []
        params: List[Any] = []
        for cat in ResourceCategory.list_values():
            clauses.append(
                "EXISTS (SELECT 1 FROM jsonb_array_elements("
                "coalesce(doc #> ARRAY['spec_dict', %s], '[]'::jsonb)) e "
                "WHERE e->>'rid' = %s OR e#>>'{config,rid}' = %s)"
            )
            params += [cat, rid, rid]
        rows = self._col.execute(
            f"SELECT count(*) FROM {{table}} WHERE {' OR '.join(clauses)}",
            tuple(params),
        )
        return rows[0][0]

    def count(self, identity: Optional[Identity] = None) -> int:
        return self._col.count_where(identity)
