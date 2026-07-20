"""Unit tests for the sandbox spawner port, models, and null adapter."""

import pytest

from mas.sandbox.spawner import (
    SandboxSpawner,
    SpawnRequest,
    SpawnResult,
    compute_sandbox_name,
)
from outbound.sandbox.null import NullSandboxSpawner


# ── compute_sandbox_name ────────────────────────────────────────────


class TestComputeSandboxName:
    def test_deterministic(self):
        a = compute_sandbox_name("sess-1", "node-a", 0)
        b = compute_sandbox_name("sess-1", "node-a", 0)
        assert a == b

    def test_differs_on_attempt(self):
        a = compute_sandbox_name("sess-1", "node-a", 0)
        b = compute_sandbox_name("sess-1", "node-a", 1)
        assert a != b

    def test_differs_on_session(self):
        a = compute_sandbox_name("sess-1", "node-a", 0)
        b = compute_sandbox_name("sess-2", "node-a", 0)
        assert a != b

    def test_differs_on_node(self):
        a = compute_sandbox_name("sess-1", "node-a", 0)
        b = compute_sandbox_name("sess-1", "node-b", 0)
        assert a != b

    def test_format(self):
        name = compute_sandbox_name("sess-1", "node-a", 0)
        assert name.startswith("sb-")
        assert len(name) == 15  # "sb-" + 12 hex chars


# ── SpawnRequest validation ─────────────────────────────────────────


class TestSpawnRequest:
    def test_defaults(self):
        r = SpawnRequest(name="test", image="img:latest")
        assert r.cpu_limit == "1"
        assert r.memory_limit == "512Mi"
        assert r.timeout_seconds == 300
        assert r.health_path == "/healthz"
        assert r.env == {}
        assert r.labels == {}

    def test_cpu_limit_millicores(self):
        r = SpawnRequest(name="t", image="i", cpu_limit="500m")
        assert r.cpu_limit == "500m"

    def test_cpu_limit_whole_cores(self):
        r = SpawnRequest(name="t", image="i", cpu_limit="4")
        assert r.cpu_limit == "4"

    def test_cpu_limit_exceeds_max(self):
        with pytest.raises(ValueError, match="exceeds maximum"):
            SpawnRequest(name="t", image="i", cpu_limit="5")

    def test_cpu_limit_millicores_exceeds_max(self):
        with pytest.raises(ValueError, match="exceeds maximum"):
            SpawnRequest(name="t", image="i", cpu_limit="5000m")

    def test_cpu_limit_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid cpu_limit"):
            SpawnRequest(name="t", image="i", cpu_limit="abc")

    def test_memory_limit_mi(self):
        r = SpawnRequest(name="t", image="i", memory_limit="1024Mi")
        assert r.memory_limit == "1024Mi"

    def test_memory_limit_gi(self):
        r = SpawnRequest(name="t", image="i", memory_limit="4Gi")
        assert r.memory_limit == "4Gi"

    def test_memory_limit_exceeds_max(self):
        with pytest.raises(ValueError, match="exceeds maximum"):
            SpawnRequest(name="t", image="i", memory_limit="5Gi")

    def test_memory_limit_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid memory_limit"):
            SpawnRequest(name="t", image="i", memory_limit="512mb")

    def test_timeout_bounds(self):
        with pytest.raises(ValueError):
            SpawnRequest(name="t", image="i", timeout_seconds=2)
        with pytest.raises(ValueError):
            SpawnRequest(name="t", image="i", timeout_seconds=700)


# ── SpawnResult ─────────────────────────────────────────────────────


class TestSpawnResult:
    def test_basic(self):
        r = SpawnResult(name="sb-abc", endpoint="http://localhost:9999")
        assert r.name == "sb-abc"
        assert r.endpoint == "http://localhost:9999"


# ── SandboxSpawner concurrency ──────────────────────────────────────


class _StubSpawner(SandboxSpawner):
    """Minimal concrete spawner for testing the ABC's concurrency logic."""

    def __init__(self, max_sandboxes: int = 2) -> None:
        super().__init__(max_sandboxes=max_sandboxes)
        self.spawned: list[str] = []
        self.destroyed: list[str] = []
        self.fail_next = False

    def _do_spawn(self, request: SpawnRequest) -> SpawnResult:
        if self.fail_next:
            raise RuntimeError("forced failure")
        self.spawned.append(request.name)
        return SpawnResult(name=request.name, endpoint=f"http://{request.name}:8080")

    def _do_destroy(self, name: str) -> None:
        self.destroyed.append(name)

    def list_active(self, labels=None) -> list[str]:
        return list(self.spawned)


class TestSandboxSpawnerConcurrency:
    def _req(self, name: str) -> SpawnRequest:
        return SpawnRequest(name=name, image="img:latest")

    def test_spawn_increments_active(self):
        s = _StubSpawner(max_sandboxes=5)
        assert s.active_count == 0
        s.spawn(self._req("a"))
        assert s.active_count == 1

    def test_destroy_decrements_active(self):
        s = _StubSpawner(max_sandboxes=5)
        s.spawn(self._req("a"))
        s.destroy("a")
        assert s.active_count == 0

    def test_concurrency_cap(self):
        s = _StubSpawner(max_sandboxes=2)
        s.spawn(self._req("a"))
        s.spawn(self._req("b"))
        with pytest.raises(RuntimeError, match="Concurrency cap"):
            s.spawn(self._req("c"))

    def test_spawn_failure_decrements(self):
        s = _StubSpawner(max_sandboxes=2)
        s.fail_next = True
        with pytest.raises(RuntimeError, match="forced failure"):
            s.spawn(self._req("a"))
        assert s.active_count == 0

    def test_destroy_never_goes_negative(self):
        s = _StubSpawner(max_sandboxes=5)
        s.destroy("nonexistent")
        assert s.active_count == 0


# ── NullSandboxSpawner ──────────────────────────────────────────────


class TestNullSandboxSpawner:
    def test_spawn_raises(self):
        s = NullSandboxSpawner()
        req = SpawnRequest(name="x", image="img:latest")
        with pytest.raises(RuntimeError, match="disabled"):
            s.spawn(req)

    def test_destroy_noop(self):
        s = NullSandboxSpawner()
        s.destroy("anything")  # should not raise

    def test_list_active_empty(self):
        s = NullSandboxSpawner()
        assert s.list_active() == []
        assert s.list_active({"foo": "bar"}) == []
