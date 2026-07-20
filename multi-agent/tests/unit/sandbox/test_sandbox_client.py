"""Unit tests for the sandbox HTTP client and contract models."""

import json
from unittest.mock import MagicMock, patch

import pytest

from mas.sandbox.client import (
    SandboxClient,
    SandboxRunRequest,
    SandboxRunResponse,
    TranscriptEvent,
)


class TestSandboxRunRequest:
    def test_serializes_with_aliases(self):
        req = SandboxRunRequest(
            query="What happened?",
            systemPrompt="You are helpful.",
            outputSchema={"type": "object"},
            allowedTools=["kubectl"],
            deniedTools=["rm"],
        )
        d = req.model_dump(by_alias=True, exclude_none=True)
        assert d["query"] == "What happened?"
        assert d["systemPrompt"] == "You are helpful."
        assert d["outputSchema"] == {"type": "object"}
        assert d["allowedTools"] == ["kubectl"]
        assert d["deniedTools"] == ["rm"]

    def test_minimal_request(self):
        req = SandboxRunRequest(query="test")
        d = req.model_dump(by_alias=True, exclude_none=True)
        assert d == {"query": "test", "context": {}, "systemPrompt": ""}


class TestSandboxRunResponse:
    def test_success(self):
        r = SandboxRunResponse(success=True, output={"result": "ok"})
        assert r.success
        assert r.output == {"result": "ok"}

    def test_failure(self):
        r = SandboxRunResponse(success=False, error="boom")
        assert not r.success
        assert r.error == "boom"


class TestTranscriptEvent:
    def test_parse_jsonl(self):
        line = '{"ts": "2024-01-01T00:00:00Z", "type": "tool_call", "data": {"name": "ls"}}'
        e = TranscriptEvent.model_validate_json(line)
        assert e.type == "tool_call"
        assert e.data["name"] == "ls"


class TestSandboxClient:
    @patch("mas.sandbox.client.urllib.request.urlopen")
    def test_run_success(self, mock_urlopen):
        response_body = json.dumps({
            "success": True,
            "output": {"diagnosis": "all good"},
            "summary": "Everything fine",
        }).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = SandboxClient(timeout=10)
        result = client.run(
            "http://localhost:8080",
            SandboxRunRequest(query="diagnose"),
        )

        assert result.success
        assert result.output == {"diagnosis": "all good"}
        assert result.summary == "Everything fine"

    @patch("mas.sandbox.client.urllib.request.urlopen")
    def test_run_failure(self, mock_urlopen):
        response_body = json.dumps({
            "success": False,
            "error": "agent crashed",
        }).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = SandboxClient()
        result = client.run("http://localhost:8080", SandboxRunRequest(query="x"))
        assert not result.success
        assert result.error == "agent crashed"

    @patch("mas.sandbox.client.urllib.request.urlopen")
    def test_run_folds_extra_keys(self, mock_urlopen):
        response_body = json.dumps({
            "success": True,
            "output": {},
            "custom_metric": 42,
        }).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = SandboxClient()
        result = client.run("http://localhost:8080", SandboxRunRequest(query="x"))
        assert result.output["custom_metric"] == 42

    @patch("mas.sandbox.client.urllib.request.urlopen")
    def test_collect_events(self, mock_urlopen):
        events = (
            '{"ts": "t1", "type": "tool_call", "data": {"name": "ls"}}\n'
            '{"ts": "t2", "type": "result", "data": {"summary": "done"}}\n'
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = events.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = SandboxClient()
        result = client.collect_events("http://localhost:8080")
        assert len(result) == 2
        assert result[0].type == "tool_call"
        assert result[1].type == "result"

    @patch("mas.sandbox.client.urllib.request.urlopen")
    def test_collect_events_graceful_failure(self, mock_urlopen):
        mock_urlopen.side_effect = ConnectionError("refused")

        client = SandboxClient()
        result = client.collect_events("http://localhost:8080")
        assert result == []

    @patch("mas.sandbox.client.urllib.request.urlopen")
    def test_run_with_auth_token(self, mock_urlopen):
        response_body = json.dumps({"success": True, "output": {}}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = SandboxClient()
        client.run(
            "http://localhost:8080",
            SandboxRunRequest(query="x"),
            auth_token="secret-token",
        )

        call_args = mock_urlopen.call_args[0][0]
        assert call_args.get_header("Authorization") == "Bearer secret-token"
