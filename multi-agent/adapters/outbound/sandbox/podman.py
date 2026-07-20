"""Podman sandbox spawner — creates containers via the podman CLI.

Uses subprocess calls (no podman-py dependency) to manage container
lifecycle on the host Podman engine.
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

from mas.sandbox.spawner import SandboxSpawner, SpawnRequest, SpawnResult

logger = logging.getLogger(__name__)

_CONTAINER_PREFIX = "sb-"


class PodmanSandboxSpawner(SandboxSpawner):
    """Spawn sandbox containers via the ``podman`` CLI."""

    def __init__(
        self,
        network: str = "harness",
        max_sandboxes: int = 10,
    ) -> None:
        super().__init__(max_sandboxes=max_sandboxes)
        self._network = network

    # ── internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _run(
        args: list[str], *, check: bool = True, timeout: int = 60
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args, capture_output=True, text=True, check=check, timeout=timeout
        )

    def _container_name(self, name: str) -> str:
        return f"{_CONTAINER_PREFIX}{name}"

    def _inspect(self, container_name: str) -> dict[str, Any] | None:
        """Return inspect JSON for a container, or None if not found."""
        result = self._run(
            ["podman", "inspect", "--type", "container", container_name],
            check=False,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        if isinstance(data, list) and data:
            return data[0]
        return data if isinstance(data, dict) else None

    def _parse_host_port(self, container_name: str, container_port: int = 8080) -> str | None:
        """Query `podman port` for the host-mapped port."""
        result = self._run(
            ["podman", "port", container_name, f"{container_port}/tcp"],
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        # Output: "0.0.0.0:12345" or "[::]:12345"
        for line in result.stdout.strip().splitlines():
            parts = line.rsplit(":", 1)
            if len(parts) == 2:
                return parts[1].strip()
        return None

    # ── SandboxSpawner interface ─────────────────────────────────────

    def _do_spawn(self, request: SpawnRequest) -> SpawnResult:
        container_name = self._container_name(request.name)

        # Idempotent: reuse a running container with the same name
        info = self._inspect(container_name)
        if info is not None:
            state = info.get("State", {})
            if state.get("Running") or state.get("Status") == "running":
                logger.info(
                    "Container '%s' already running (idempotent)", container_name
                )
                host_port = self._parse_host_port(container_name)
                if host_port:
                    return SpawnResult(
                        name=request.name,
                        endpoint=f"http://localhost:{host_port}",
                    )
                return SpawnResult(
                    name=request.name,
                    endpoint=f"http://{container_name}:8080",
                )
            # Stale container — remove it
            self._run(["podman", "rm", "-f", container_name], check=False)
            logger.info("Removed stale container '%s'", container_name)

        # Build the `podman run` command
        cmd: list[str] = [
            "podman", "run", "-d",
            "--name", container_name,
            "--network", self._network,
            "-p", "8080",
        ]

        for key, value in request.env.items():
            cmd.extend(["-e", f"{key}={value}"])

        labels = {"spawned-by": "mas-harness"}
        labels.update(request.labels)
        for key, value in labels.items():
            cmd.extend(["--label", f"{key}={value}"])

        if request.cpu_limit:
            cmd.extend(["--cpus", self._cpu_limit_to_float(request.cpu_limit)])
        if request.memory_limit:
            cmd.extend(["--memory", self._memory_limit_to_bytes(request.memory_limit)])

        cmd.append(request.image)

        result = self._run(cmd)
        container_id = result.stdout.strip()[:12]
        logger.info(
            "Spawned Podman container '%s' (%s)", container_name, container_id
        )

        host_port = self._parse_host_port(container_name)
        if host_port:
            endpoint = f"http://localhost:{host_port}"
        else:
            endpoint = f"http://{container_name}:8080"

        return SpawnResult(name=request.name, endpoint=endpoint)

    def _do_destroy(self, name: str) -> None:
        container_name = self._container_name(name)
        result = self._run(
            ["podman", "rm", "-f", container_name], check=False
        )
        if result.returncode == 0:
            logger.info("Destroyed container '%s'", container_name)
        else:
            logger.warning(
                "Failed to destroy container '%s': %s",
                container_name,
                result.stderr.strip(),
            )

    def list_active(
        self, labels: dict[str, str] | None = None
    ) -> list[str]:
        filter_args: list[str] = []
        merged = {"spawned-by": "mas-harness"}
        if labels:
            merged.update(labels)
        for key, value in merged.items():
            filter_args.extend(["--filter", f"label={key}={value}"])

        result = self._run(
            ["podman", "ps", *filter_args, "--format", "{{.Names}}"],
            check=False,
        )
        if result.returncode != 0:
            return []
        names: list[str] = []
        for line in result.stdout.strip().splitlines():
            name = line.strip()
            if name.startswith(_CONTAINER_PREFIX):
                names.append(name[len(_CONTAINER_PREFIX):])
            elif name:
                names.append(name)
        return names

    # ── resource-limit helpers ───────────────────────────────────────

    @staticmethod
    def _cpu_limit_to_float(cpu: str) -> str:
        match = __import__("re").match(r"^(\d+)(m?)$", cpu)
        if not match:
            return cpu
        value, unit = int(match.group(1)), match.group(2)
        return str(value / 1000) if unit == "m" else str(value)

    @staticmethod
    def _memory_limit_to_bytes(mem: str) -> str:
        match = __import__("re").match(r"^(\d+)(Mi|Gi)$", mem)
        if not match:
            return mem
        value, unit = int(match.group(1)), match.group(2)
        if unit == "Gi":
            return f"{value}g"
        return f"{value}m"
