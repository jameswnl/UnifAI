"""Sandbox spawner port — platform abstraction for ephemeral containers.

Defines the interface for spawning and destroying sandbox containers
on demand.  Implementations (Podman, K8s) live in adapters/outbound/sandbox/.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
import urllib.request
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class SpawnRequest(BaseModel):
    """What to spawn: image, naming, resource limits."""

    name: str
    image: str
    env: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    cpu_limit: str = Field(default="1")
    memory_limit: str = Field(default="512Mi")
    timeout_seconds: int = Field(default=300, ge=5, le=600)
    health_path: str = "/healthz"

    @field_validator("cpu_limit")
    @classmethod
    def _validate_cpu_limit(cls, v: str) -> str:
        match = re.match(r"^(\d+)(m?)$", v)
        if not match:
            raise ValueError(f"Invalid cpu_limit format: {v}")
        value, unit = int(match.group(1)), match.group(2)
        cores = value / 1000 if unit == "m" else value
        if cores > 4:
            raise ValueError(f"cpu_limit {v} exceeds maximum of 4 cores")
        return v

    @field_validator("memory_limit")
    @classmethod
    def _validate_memory_limit(cls, v: str) -> str:
        match = re.match(r"^(\d+)(Mi|Gi)$", v)
        if not match:
            raise ValueError(f"Invalid memory_limit format: {v}")
        value, unit = int(match.group(1)), match.group(2)
        mib = value if unit == "Mi" else value * 1024
        if mib > 4096:
            raise ValueError(f"memory_limit {v} exceeds maximum of 4Gi")
        return v


class SpawnResult(BaseModel):
    """Endpoint information for a spawned sandbox container."""

    name: str
    endpoint: str


class SandboxSpawner(ABC):
    """Port for spawning ephemeral sandbox containers.

    Implementations manage the full container lifecycle: create, health-poll,
    destroy, and reconciliation listing.  Concurrency is capped at
    ``max_sandboxes`` to prevent resource exhaustion.
    """

    def __init__(self, max_sandboxes: int = 10) -> None:
        self._active_count = 0
        self._max_sandboxes = max_sandboxes
        self._lock = threading.Lock()

    def spawn(self, request: SpawnRequest) -> SpawnResult:
        """Create a sandbox container and return its endpoint.

        Raises ``RuntimeError`` if the concurrency cap is reached.
        """
        with self._lock:
            if self._active_count >= self._max_sandboxes:
                raise RuntimeError(
                    f"Concurrency cap reached: {self._active_count}/"
                    f"{self._max_sandboxes} sandboxes active"
                )
            self._active_count += 1

        try:
            return self._do_spawn(request)
        except Exception:
            with self._lock:
                self._active_count = max(0, self._active_count - 1)
            raise

    @abstractmethod
    def _do_spawn(self, request: SpawnRequest) -> SpawnResult:
        """Implementation-specific container creation."""

    def destroy(self, name: str) -> None:
        """Destroy a sandbox container by name."""
        try:
            self._do_destroy(name)
        finally:
            with self._lock:
                self._active_count = max(0, self._active_count - 1)

    @abstractmethod
    def _do_destroy(self, name: str) -> None:
        """Implementation-specific container destruction."""

    @abstractmethod
    def list_active(
        self, labels: dict[str, str] | None = None
    ) -> list[str]:
        """List active sandbox names matching the given labels."""

    def wait_ready(
        self,
        endpoint: str,
        *,
        timeout: float = 60.0,
        health_path: str = "/healthz",
    ) -> bool:
        """Poll the health endpoint until it returns 200 or timeout."""
        url = f"{endpoint.rstrip('/')}{health_path}"
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                pass
            time.sleep(2.0)
        return False

    @property
    def active_count(self) -> int:
        return self._active_count


def compute_sandbox_name(
    session_id: str, node_uid: str, attempt: int
) -> str:
    """Content-hash sandbox name for idempotent retries.

    Same (session_id, node_uid, attempt) always produces the same name,
    so a retried step can detect and reuse (or clean up) its predecessor.
    """
    raw = f"{session_id}:{node_uid}:{attempt}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return f"sb-{digest}"
