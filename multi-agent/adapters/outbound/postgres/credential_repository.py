"""PostgreSQL CredentialStore + ServerConfigStore (plan item [1.1], issue #7).

Mirrors the Mongo implementations, including Fernet field encryption for
access/refresh tokens when an encryption key is configured.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from mas.core.auth.credentials.models import ClientConfig, StoredCredential, TokenStatus
from mas.core.auth.credentials.ports import CredentialStore, ServerConfigStore
from global_utils.utils.crypto import FieldCipher

from outbound.postgres.db import PgCollection

_ENCRYPTED_FIELDS = ("access_token", "refresh_token")


class PgCredentialStore(CredentialStore):

    def __init__(self, dsn: str, table: str = "credentials",
                 encryption_key: str = "") -> None:
        self._col = PgCollection(dsn, table)
        self._cipher = FieldCipher(encryption_key) if encryption_key else None

    @staticmethod
    def _pk(user_id: str, server_identifier: str) -> str:
        return f"{user_id}␟{server_identifier.rstrip('/')}"

    def upsert(self, credential: StoredCredential) -> None:
        doc = credential.model_dump(mode="json")
        doc["server_identifier"] = credential.server_identifier.rstrip("/")
        doc["updated_at"] = str(datetime.now(timezone.utc))
        if self._cipher:
            for field in _ENCRYPTED_FIELDS:
                if doc.get(field):
                    doc[field] = self._cipher.encrypt(doc[field])
        self._col.upsert(self._pk(credential.user_id, doc["server_identifier"]), doc)

    def find_by_server(self, user_id: str, server_identifier: str,
                       scheme_type: str = "") -> Optional[StoredCredential]:
        doc = self._col.get(self._pk(user_id, server_identifier))
        if not doc or doc.get("status") != TokenStatus.ACTIVE.value:
            return None
        if scheme_type and doc.get("scheme_type") != scheme_type:
            return None
        return self._to_model(doc)

    def delete(self, user_id: str, server_identifier: str) -> None:
        self._col.delete(self._pk(user_id, server_identifier))

    def update_status(self, user_id: str, server_identifier: str, status: str) -> None:
        doc = self._col.get(self._pk(user_id, server_identifier))
        if doc:
            doc["status"] = status
            doc["updated_at"] = str(datetime.now(timezone.utc))
            self._col.upsert(self._pk(user_id, server_identifier), doc)

    def _to_model(self, doc: dict) -> StoredCredential:
        for legacy in ("_id", "_expires_at", "staged", "server_url_normalised",
                       "mcp_server_url", "server_url", "auth_rid"):
            doc.pop(legacy, None)
        if self._cipher:
            for field in _ENCRYPTED_FIELDS:
                if doc.get(field):
                    doc[field] = self._cipher.decrypt(doc[field])
        return StoredCredential.model_validate(doc)


class PgServerConfigStore(ServerConfigStore):

    def __init__(self, dsn: str, table: str = "server_configs") -> None:
        self._col = PgCollection(dsn, table)

    def find_by_server(self, user_id: str, server_identifier: str) -> Optional[ClientConfig]:
        if not server_identifier:
            return None
        doc = self._col.get(server_identifier.rstrip("/"))
        return ClientConfig.model_validate(doc) if doc else None

    def save(self, user_id: str, config: ClientConfig) -> None:
        doc = config.model_dump(mode="json")
        doc["server_identifier"] = config.server_identifier.rstrip("/")
        self._col.upsert(doc["server_identifier"], doc)
