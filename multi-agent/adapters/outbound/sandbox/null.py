"""Null sandbox spawner — used when sandboxing is disabled."""

from __future__ import annotations

from mas.sandbox.spawner import SandboxSpawner, SpawnRequest, SpawnResult


class NullSandboxSpawner(SandboxSpawner):
    """No-op spawner for environments without container sandboxing."""

    def __init__(self) -> None:
        super().__init__(max_sandboxes=0)

    def spawn(self, request: SpawnRequest) -> SpawnResult:
        raise RuntimeError(
            "Sandbox spawning is disabled (SANDBOX_SPAWNER=none). "
            "Set SANDBOX_SPAWNER=podman or SANDBOX_SPAWNER=k8s to enable."
        )

    def _do_spawn(self, request: SpawnRequest) -> SpawnResult:
        raise RuntimeError("unreachable")

    def _do_destroy(self, name: str) -> None:
        pass

    def list_active(
        self, labels: dict[str, str] | None = None
    ) -> list[str]:
        return []
