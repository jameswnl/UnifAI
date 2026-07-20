"""Webhook + Slack notifier adapters (plan item [2.6], issue #16).

Stdlib-only HTTP so the harness profile adds no dependency. The
``_post`` callable is injectable for tests.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Callable, Dict, Optional

from mas.core.notify import Notifier, NotifierHub

logger = logging.getLogger(__name__)

PostFn = Callable[[str, Dict[str, Any]], None]


def _default_post(url: str, body: Dict[str, Any], timeout: float = 5.0) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(body, default=str).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=timeout).close()


class WebhookNotifier(Notifier):
    """POSTs the raw notification envelope as JSON — the minimal target."""

    def __init__(self, url: str, post: Optional[PostFn] = None) -> None:
        self._url = url
        self._post = post or _default_post

    def send(self, kind: str, session_id: str, payload: Dict[str, Any]) -> None:
        self._post(self._url, {
            "kind": kind,
            "session_id": session_id,
            **payload,
        })


class SlackNotifier(Notifier):
    """Posts a readable message to a Slack incoming webhook."""

    _TEMPLATES = {
        "approval.requested": (
            ":raised_hand: *Approval required* — session `{session_id}`\n"
            "tool `{tool_name}` on node `{node_uid}` (request `{request_id}`)"
        ),
        "session.escalated": (
            ":rotating_light: *Escalated to human* — session `{session_id}`\n"
            "step `{node_uid}` gave up after {attempts} attempt(s): {error}"
        ),
    }

    def __init__(self, webhook_url: str, post: Optional[PostFn] = None) -> None:
        self._url = webhook_url
        self._post = post or _default_post

    def send(self, kind: str, session_id: str, payload: Dict[str, Any]) -> None:
        template = self._TEMPLATES.get(kind)
        if template:
            text = template.format(session_id=session_id, **{
                k: payload.get(k, "?") for k in
                ("tool_name", "node_uid", "request_id", "attempts", "error")
            })
        else:
            text = f"{kind} — session {session_id}: {json.dumps(payload, default=str)}"
        self._post(self._url, {"text": text})


def build_notifier_hub(cfg) -> NotifierHub:
    """Assemble the hub from config (empty URLs → disabled)."""
    notifiers = []
    if getattr(cfg, "notify_webhook_url", ""):
        notifiers.append(WebhookNotifier(cfg.notify_webhook_url))
    if getattr(cfg, "notify_slack_webhook_url", ""):
        notifiers.append(SlackNotifier(cfg.notify_slack_webhook_url))
    return NotifierHub(notifiers)
