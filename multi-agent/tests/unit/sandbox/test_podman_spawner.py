"""Unit tests for PodmanSandboxSpawner with mocked subprocess calls."""

import json
import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from mas.sandbox.spawner import SpawnRequest, SpawnResult
from outbound.sandbox.podman import PodmanSandboxSpawner


@pytest.fixture
def spawner():
    return PodmanSandboxSpawner(network="test-net", max_sandboxes=10)


def _req(name: str = "sb-abc123", **kw) -> SpawnRequest:
    defaults = {"name": name, "image": "sandbox:latest"}
    defaults.update(kw)
    return SpawnRequest(**defaults)


# ── spawn ────────────────────────────────────────────────────────────


class TestPodmanSpawn:
    @patch("outbound.sandbox.podman.PodmanSandboxSpawner._run")
    def test_spawn_new_container(self, mock_run, spawner):
        # inspect → not found; run → container id; port → host port
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="no such container"),  # inspect
            MagicMock(returncode=0, stdout="abc123def456\n"),  # podman run
            MagicMock(returncode=0, stdout="0.0.0.0:54321\n"),  # podman port
        ]

        result = spawner.spawn(_req())
        assert isinstance(result, SpawnResult)
        assert result.endpoint == "http://localhost:54321"
        assert result.name == "sb-abc123"

        # Verify the run command includes expected args
        run_call = mock_run.call_args_list[1]
        cmd = run_call[0][0]
        assert cmd[0:3] == ["podman", "run", "-d"]
        assert "--name" in cmd
        name_idx = cmd.index("--name")
        assert cmd[name_idx + 1] == "sb-sb-abc123"
        assert "--network" in cmd
        net_idx = cmd.index("--network")
        assert cmd[net_idx + 1] == "test-net"
        assert "sandbox:latest" in cmd

    @patch("outbound.sandbox.podman.PodmanSandboxSpawner._run")
    def test_spawn_idempotent_existing(self, mock_run, spawner):
        inspect_data = [{"State": {"Running": True, "Status": "running"}}]
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=json.dumps(inspect_data)),  # inspect
            MagicMock(returncode=0, stdout="0.0.0.0:12345\n"),  # port
        ]

        result = spawner.spawn(_req())
        assert result.endpoint == "http://localhost:12345"
        # Should not have called `podman run`
        assert len(mock_run.call_args_list) == 2

    @patch("outbound.sandbox.podman.PodmanSandboxSpawner._run")
    def test_spawn_removes_stale_container(self, mock_run, spawner):
        inspect_data = [{"State": {"Running": False, "Status": "exited"}}]
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=json.dumps(inspect_data)),  # inspect
            MagicMock(returncode=0, stdout=""),  # rm -f (stale)
            MagicMock(returncode=0, stdout="newid\n"),  # run
            MagicMock(returncode=0, stdout="0.0.0.0:33333\n"),  # port
        ]

        result = spawner.spawn(_req())
        assert result.endpoint == "http://localhost:33333"
        # Verify rm -f was called for the stale container
        rm_call = mock_run.call_args_list[1]
        assert rm_call[0][0][:3] == ["podman", "rm", "-f"]

    @patch("outbound.sandbox.podman.PodmanSandboxSpawner._run")
    def test_spawn_with_env_and_labels(self, mock_run, spawner):
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),  # inspect
            MagicMock(returncode=0, stdout="id\n"),  # run
            MagicMock(returncode=0, stdout="0.0.0.0:8080\n"),  # port
        ]

        req = _req(
            env={"FOO": "bar", "BAZ": "qux"},
            labels={"workflow": "wf-1"},
        )
        spawner.spawn(req)

        run_cmd = mock_run.call_args_list[1][0][0]
        assert "-e" in run_cmd
        env_pairs = []
        for i, arg in enumerate(run_cmd):
            if arg == "-e" and i + 1 < len(run_cmd):
                env_pairs.append(run_cmd[i + 1])
        assert "FOO=bar" in env_pairs
        assert "BAZ=qux" in env_pairs

        label_pairs = []
        for i, arg in enumerate(run_cmd):
            if arg == "--label" and i + 1 < len(run_cmd):
                label_pairs.append(run_cmd[i + 1])
        assert "spawned-by=mas-harness" in label_pairs
        assert "workflow=wf-1" in label_pairs

    @patch("outbound.sandbox.podman.PodmanSandboxSpawner._run")
    def test_spawn_fallback_endpoint_no_port(self, mock_run, spawner):
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),  # inspect
            MagicMock(returncode=0, stdout="id\n"),  # run
            MagicMock(returncode=1, stdout=""),  # port fails
        ]

        result = spawner.spawn(_req())
        assert result.endpoint == "http://sb-sb-abc123:8080"

    @patch("outbound.sandbox.podman.PodmanSandboxSpawner._run")
    def test_spawn_resource_limits(self, mock_run, spawner):
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),  # inspect
            MagicMock(returncode=0, stdout="id\n"),  # run
            MagicMock(returncode=0, stdout="0.0.0.0:8080\n"),  # port
        ]

        req = _req(cpu_limit="500m", memory_limit="1Gi")
        spawner.spawn(req)

        run_cmd = mock_run.call_args_list[1][0][0]
        cpus_idx = run_cmd.index("--cpus")
        assert run_cmd[cpus_idx + 1] == "0.5"
        mem_idx = run_cmd.index("--memory")
        assert run_cmd[mem_idx + 1] == "1g"


# ── destroy ──────────────────────────────────────────────────────────


class TestPodmanDestroy:
    @patch("outbound.sandbox.podman.PodmanSandboxSpawner._run")
    def test_destroy_calls_rm_force(self, mock_run, spawner):
        mock_run.return_value = MagicMock(returncode=0)
        spawner._active_count = 1  # simulate a prior spawn

        spawner.destroy("sb-abc123")
        mock_run.assert_called_once_with(
            ["podman", "rm", "-f", "sb-sb-abc123"], check=False
        )

    @patch("outbound.sandbox.podman.PodmanSandboxSpawner._run")
    def test_destroy_tolerates_failure(self, mock_run, spawner):
        mock_run.return_value = MagicMock(
            returncode=1, stderr="no such container"
        )
        spawner._active_count = 1

        spawner.destroy("gone")  # should not raise


# ── list_active ──────────────────────────────────────────────────────


class TestPodmanListActive:
    @patch("outbound.sandbox.podman.PodmanSandboxSpawner._run")
    def test_list_active_parses_names(self, mock_run, spawner):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="sb-abc\nsb-def\n"
        )

        names = spawner.list_active()
        assert names == ["abc", "def"]

    @patch("outbound.sandbox.podman.PodmanSandboxSpawner._run")
    def test_list_active_with_labels(self, mock_run, spawner):
        mock_run.return_value = MagicMock(returncode=0, stdout="sb-xyz\n")

        spawner.list_active({"workflow": "wf-1"})
        cmd = mock_run.call_args[0][0]
        assert "--filter" in cmd
        filters = []
        for i, arg in enumerate(cmd):
            if arg == "--filter" and i + 1 < len(cmd):
                filters.append(cmd[i + 1])
        assert "label=spawned-by=mas-harness" in filters
        assert "label=workflow=wf-1" in filters

    @patch("outbound.sandbox.podman.PodmanSandboxSpawner._run")
    def test_list_active_empty(self, mock_run, spawner):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        assert spawner.list_active() == []

    @patch("outbound.sandbox.podman.PodmanSandboxSpawner._run")
    def test_list_active_on_error(self, mock_run, spawner):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert spawner.list_active() == []


# ── resource-limit helpers ───────────────────────────────────────────


class TestResourceHelpers:
    def test_cpu_limit_millicores(self):
        assert PodmanSandboxSpawner._cpu_limit_to_float("500m") == "0.5"
        assert PodmanSandboxSpawner._cpu_limit_to_float("1000m") == "1.0"
        assert PodmanSandboxSpawner._cpu_limit_to_float("100m") == "0.1"

    def test_cpu_limit_whole_cores(self):
        assert PodmanSandboxSpawner._cpu_limit_to_float("2") == "2"
        assert PodmanSandboxSpawner._cpu_limit_to_float("4") == "4"

    def test_memory_limit_mi(self):
        assert PodmanSandboxSpawner._memory_limit_to_bytes("512Mi") == "512m"
        assert PodmanSandboxSpawner._memory_limit_to_bytes("1024Mi") == "1024m"

    def test_memory_limit_gi(self):
        assert PodmanSandboxSpawner._memory_limit_to_bytes("1Gi") == "1g"
        assert PodmanSandboxSpawner._memory_limit_to_bytes("4Gi") == "4g"
