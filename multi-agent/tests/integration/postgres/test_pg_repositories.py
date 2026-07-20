"""
Contract tests for the PostgreSQL repositories ([1.1], issue #7).

Require a live PostgreSQL — set POSTGRES_DSN to run, e.g.:

    POSTGRES_DSN=postgresql://unifai:unifai@localhost:5432/unifai \
        pytest tests/integration/postgres -q

Skipped entirely when POSTGRES_DSN is unset so the unit lane stays hermetic.
"""

import os
import uuid

import pytest

DSN = os.environ.get("POSTGRES_DSN", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="POSTGRES_DSN not set"),
]


def _identity():
    from mas.core.identity import Identity, IdentityType
    return Identity(type=IdentityType.USER, id=f"pg-test-{uuid.uuid4().hex[:8]}")


@pytest.fixture()
def identity():
    return _identity()


class TestSessionRepository:

    @pytest.fixture()
    def repo(self):
        from outbound.postgres import PgSessionRepository
        return PgSessionRepository(DSN, table="test_sessions")

    def _record(self, identity, run_id):
        from mas.session.domain.session_record import SessionRecord
        from mas.core.execution_context import ExecutionContext
        return SessionRecord(
            run_id=run_id,
            identity=identity,
            blueprint_id="bp-1",
            run_context=ExecutionContext(),
        )

    def test_save_fetch_roundtrip(self, repo, identity):
        run_id = str(uuid.uuid4())
        repo.save(self._record(identity, run_id))
        fetched = repo.fetch(run_id)
        assert fetched.run_id == run_id
        assert fetched.identity.id == identity.id
        assert repo.list_runs(identity) == [run_id]
        assert repo.count(identity, {}) == 1
        assert repo.delete(run_id) is True
        assert repo.delete(run_id) is False
        with pytest.raises(KeyError):
            repo.fetch(run_id)

    def test_fetch_chat_projection(self, repo, identity):
        run_id = str(uuid.uuid4())
        record = self._record(identity, run_id)
        record.graph_state["messages"] = [
            {"role": "user", "content": "hi", "sender_id": identity.id}]
        record.graph_state["output"] = "answer"
        repo.save(record)
        chat = repo.fetch_chat(run_id)
        assert chat.output == "answer"
        assert len(chat.messages) == 1
        repo.delete(run_id)

    def test_group_count(self, repo, identity):
        for status in ("PENDING", "PENDING", "FAILED"):
            rid = str(uuid.uuid4())
            rec = self._record(identity, rid)
            rec.status = status
            repo.save(rec)
        groups = {g.fields["status"]: g.count
                  for g in repo.group_count(identity, ["status"])}
        assert groups == {"PENDING": 2, "FAILED": 1}
        assert repo.delete_by_identity(identity) == 3


class TestBlueprintRepository:

    @pytest.fixture()
    def repo(self):
        from outbound.postgres import PgBlueprintRepository
        return PgBlueprintRepository(DSN, table="test_blueprints")

    def _draft(self):
        from mas.blueprints.models.blueprint import BlueprintDraft
        return BlueprintDraft(name="t", description="d", nodes=[], plan=[])

    def test_crud_and_listing(self, repo, identity):
        r1, r2 = f"r-{uuid.uuid4().hex[:8]}", f"r-{uuid.uuid4().hex[:8]}"
        bp_id = repo.save(identity, self._draft(), rid_refs=[r1],
                          metadata={"k": "v"})
        assert repo.exists(bp_id)
        doc = repo.load(bp_id)
        assert doc.blueprint_id == bp_id and doc.metadata == {"k": "v"}

        assert repo.update(blueprint_id=bp_id, spec=self._draft(),
                           rid_refs=[r1, r2]) is True
        assert repo.load(bp_id).rid_refs == [r1, r2]

        assert repo.set_metadata(blueprint_id=bp_id, metadata={"k2": "v2"}) is True
        assert repo.load(bp_id).metadata == {"k": "v", "k2": "v2"}

        assert bp_id in repo.list_ids(identity=identity)
        summaries = repo.list_summaries(identity=identity)
        assert any(s.blueprint_id == bp_id for s in summaries)
        assert repo.list_direct_usage(r2) == [bp_id]
        assert repo.count(identity) >= 1

        assert repo.load_many([bp_id])[0].blueprint_id == bp_id
        assert repo.delete(bp_id) is True
        assert not repo.exists(bp_id)


class TestResourceRepository:

    @pytest.fixture()
    def repo(self):
        from outbound.postgres import PgResourceRepository
        return PgResourceRepository(DSN, table="test_resources")

    def _resource(self, identity, dep: str, name="res-a"):
        from mas.resources.models import Resource
        from mas.core.enums import ResourceCategory
        return Resource(
            identity=identity,
            category=ResourceCategory.LLM,
            type="openai",
            name=name,
            cfg_dict={"model_name": "gpt-4o", "nested": {"rid": dep}},
            nested_refs=[dep],
        )

    def test_crud_and_queries(self, repo, identity):
        from mas.resources.models import ResourceQuery
        from mas.core.enums import ResourceCategory

        dep = f"dep-{uuid.uuid4().hex[:8]}"
        res = self._resource(identity, dep)
        rid = repo.save(res)
        assert repo.exists(rid)
        cat = ResourceCategory.LLM.value
        assert repo.get(rid).name == "res-a"
        assert repo.meta(rid) == (cat, "openai")

        found = repo.find_by_name(identity, cat, "openai", "res-a")
        assert found is not None and found.rid == rid

        results = repo.find_resources(ResourceQuery(
            identity=identity, category=ResourceCategory.LLM))
        assert [r.rid for r in results] == [rid]
        assert repo.count_resources(ResourceQuery(identity=identity)) == 1

        assert repo.list_nested_usage(dep) == [rid]
        assert repo.count_nested(dep) == 1
        assert repo.count_by_config_field(identity, "model_name", "gpt-4o") == 1
        assert repo.count_by_config_field(
            identity, "model_name", "gpt-4o", exclude_rid=rid) == 0

        repo.delete(rid)
        assert not repo.exists(rid)


class TestCredentialStores:

    def test_credential_roundtrip_with_encryption(self):
        from outbound.postgres import PgCredentialStore
        from mas.core.auth.credentials.models import StoredCredential, TokenStatus
        from cryptography.fernet import Fernet

        store = PgCredentialStore(DSN, table="test_credentials",
                                  encryption_key=Fernet.generate_key().decode())
        user = f"u-{uuid.uuid4().hex[:8]}"
        cred = StoredCredential(
            user_id=user,
            server_identifier="https://auth.example.com/",
            scheme_type="oauth2",
            access_token="secret-token",
            status=TokenStatus.ACTIVE,
        )
        store.upsert(cred)

        loaded = store.find_by_server(user, "https://auth.example.com")
        assert loaded is not None
        assert loaded.access_token == "secret-token"

        store.update_status(user, "https://auth.example.com", "revoked")
        assert store.find_by_server(user, "https://auth.example.com") is None
        store.delete(user, "https://auth.example.com")

    def test_server_config_roundtrip(self):
        from outbound.postgres import PgServerConfigStore
        from mas.core.auth.credentials.models import ClientConfig

        store = PgServerConfigStore(DSN, table="test_server_configs")
        ident = f"https://mcp.example.com/{uuid.uuid4().hex[:6]}"
        store.save("u1", ClientConfig(server_identifier=ident, client_id="cid"))
        assert store.find_by_server("u1", ident) is not None
        assert store.find_by_server("u1", "") is None


class TestSessionEventStore:

    def test_append_list_count_delete(self):
        from outbound.postgres.event_store import PgSessionEventStore

        store = PgSessionEventStore(DSN, table="test_session_events")
        sid = f"s-{uuid.uuid4().hex[:8]}"
        store.append(sid, {"type": "node_started", "uid": "n1"})
        store.append(sid, {"type": "node_output", "uid": "n1", "output": "hi"})

        assert store.count(sid) == 2
        events = store.list_events(sid)
        assert [e["type"] for e in events] == ["node_started", "node_output"]
        assert store.list_events(sid, offset=1) == [events[1]]
        assert store.delete_session(sid) == 2
        assert store.count(sid) == 0
