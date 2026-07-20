"""Unit tests for escalation v2: park-and-resume lifecycle."""

from unittest.mock import MagicMock

import pytest

from mas.session.domain.status import SessionStatus
from mas.session.execution.lifecycle import SessionLifecycle


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def lifecycle(repo):
    return SessionLifecycle(repository=repo)


def _make_record(status=SessionStatus.RUNNING):
    record = MagicMock()
    record.status = status
    record.run_id = "run-1"
    record.identity.id = "user-1"
    record.blueprint_id = "bp-1"
    record.metadata.status_message = ""
    record.metadata.tags = {}
    record.run_context.mark_finished.return_value = record.run_context
    return record


class TestPark:
    def test_park_sets_status(self, lifecycle, repo):
        record = _make_record()
        lifecycle.park(record, node_uid="diag_step", reason="need operator input")

        assert record.status == SessionStatus.PARKED
        assert "diag_step" in record.metadata.status_message
        assert "operator input" in record.metadata.status_message
        repo.save.assert_called_once_with(record)

    def test_park_default_reason(self, lifecycle):
        record = _make_record()
        lifecycle.park(record, node_uid="step_a")

        assert "awaiting human input" in record.metadata.status_message

    def test_park_noop_if_cancelled(self, lifecycle, repo):
        record = _make_record(status=SessionStatus.CANCELLED)
        lifecycle.park(record, node_uid="x")

        assert record.status == SessionStatus.CANCELLED
        repo.save.assert_not_called()

    def test_park_preserves_run_context(self, lifecycle):
        record = _make_record()
        lifecycle.park(record, node_uid="x")

        record.run_context.mark_finished.assert_not_called()


class TestUnpark:
    def test_unpark_sets_running(self, lifecycle, repo):
        record = _make_record(status=SessionStatus.PARKED)
        lifecycle.unpark(record)

        assert record.status == SessionStatus.RUNNING
        assert record.metadata.status_message == ""
        repo.save.assert_called_once_with(record)

    def test_unpark_with_context(self, lifecycle):
        record = _make_record(status=SessionStatus.PARKED)
        lifecycle.unpark(record, context={"fix": "apply patch X"})

        assert "fix" in record.metadata.tags["unpark_context"]

    def test_unpark_noop_if_not_parked(self, lifecycle, repo):
        record = _make_record(status=SessionStatus.RUNNING)
        lifecycle.unpark(record)

        repo.save.assert_not_called()

    def test_unpark_noop_if_completed(self, lifecycle, repo):
        record = _make_record(status=SessionStatus.COMPLETED)
        lifecycle.unpark(record)

        repo.save.assert_not_called()


class TestParkUnparkRoundtrip:
    def test_full_cycle(self, lifecycle, repo):
        record = _make_record(status=SessionStatus.RUNNING)

        lifecycle.park(record, node_uid="step_1", reason="waiting for approval")
        assert record.status == SessionStatus.PARKED

        lifecycle.unpark(record, context={"decision": "proceed"})
        assert record.status == SessionStatus.RUNNING
        assert record.metadata.status_message == ""

        assert repo.save.call_count == 2


class TestSessionStatusEnum:
    def test_parked_exists(self):
        assert SessionStatus.PARKED.value == "PARKED"

    def test_parked_is_not_in_non_runnable(self):
        from mas.session.domain.status import NON_RUNNABLE_STATUSES
        assert "PARKED" not in NON_RUNNABLE_STATUSES
