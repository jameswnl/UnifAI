"""HTTP client for the sandbox agent runtime.

Speaks the ``/v1/agent/run`` contract exposed by the
``lightspeed-agentic-sandbox`` image.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Request / response models ───────────────────────────────────────


class SandboxRunRequest(BaseModel):
    """POST /v1/agent/run request body."""

    query: str
    context: dict[str, Any] = Field(default_factory=dict)
    system_prompt: str = Field(default="", alias="systemPrompt")
    output_schema: dict[str, Any] | None = Field(default=None, alias="outputSchema")
    allowed_tools: list[str] | None = Field(default=None, alias="allowedTools")
    denied_tools: list[str] | None = Field(default=None, alias="deniedTools")

    model_config = {"populate_by_name": True}


class SandboxRunResponse(BaseModel):
    """Parsed POST /v1/agent/run response."""

    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    summary: str = ""


class TranscriptEvent(BaseModel):
    """Single JSONL event from GET /v1/agent/events."""

    ts: str = ""
    type: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


# ── Client ───────────────────────────────────────────────────────────


class SandboxClient:
    """Stateless HTTP client for a running sandbox container."""

    def __init__(self, timeout: float = 300.0) -> None:
        self._timeout = timeout

    def run(
        self,
        endpoint: str,
        request: SandboxRunRequest,
        *,
        auth_token: str = "",
    ) -> SandboxRunResponse:
        """POST /v1/agent/run and return the parsed response."""
        url = f"{endpoint.rstrip('/')}/v1/agent/run"
        body = request.model_dump(by_alias=True, exclude_none=True)
        data = json.dumps(body).encode()

        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            raw = json.loads(resp.read())

        success = raw.get("success", False)
        output = raw.get("output", {})
        if isinstance(output, str):
            output = {"result": output}
        # Fold unknown top-level keys into output
        for k, v in raw.items():
            if k not in ("success", "output", "error", "summary"):
                output.setdefault(k, v)

        return SandboxRunResponse(
            success=success,
            output=output,
            error=raw.get("error", ""),
            summary=raw.get("summary", ""),
        )

    def collect_events(
        self,
        endpoint: str,
        *,
        auth_token: str = "",
    ) -> list[TranscriptEvent]:
        """GET /v1/agent/events and return parsed transcript events."""
        url = f"{endpoint.rstrip('/')}/v1/agent/events"
        headers: dict[str, str] = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                text = resp.read().decode()
        except Exception:
            logger.debug("No transcript events available", exc_info=True)
            return []

        events: list[TranscriptEvent] = []
        for line in text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(TranscriptEvent.model_validate_json(line))
            except Exception:
                logger.debug("Skipping unparseable event line: %s", line[:120])
        return events
