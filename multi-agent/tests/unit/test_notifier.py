"""Unit tests for the notifier port ([2.6], issue #16)."""

import pytest

from mas.core.notify import Notifier, NotifierHub, NULL_NOTIFIER
from outbound.notify import SlackNotifier, WebhookNotifier, build_notifier_hub


class Capture:
    def __init__(self):
        self.posts = []

    def __call__(self, url, body):
        self.posts.append((url, body))


class Exploding(Notifier):
    def send(self, kind, session_id, payload):
        raise RuntimeError("down")


@pytest.mark.unit
def test_webhook_envelope():
    post = Capture()
    hub = NotifierHub([WebhookNotifier("http://x/hook", post=post)])
    hub.session_escalated("s1", node_uid="fix", reason="retries_exhausted",
                          error="boom", attempts=2)
    url, body = post.posts[0]
    assert url == "http://x/hook"
    assert body["kind"] == "session.escalated"
    assert body["session_id"] == "s1"
    assert body["attempts"] == 2


@pytest.mark.unit
def test_slack_formats_text():
    post = Capture()
    hub = NotifierHub([SlackNotifier("http://slack/hook", post=post)])
    hub.approval_requested("s2", request_id="r1", tool_name="ssh_exec",
                           node_uid="n1")
    _, body = post.posts[0]
    assert "Approval required" in body["text"]
    assert "ssh_exec" in body["text"]
    assert "s2" in body["text"]


@pytest.mark.unit
def test_hub_swallows_failures_and_continues():
    post = Capture()
    hub = NotifierHub([Exploding(), WebhookNotifier("http://x", post=post)])
    hub.session_escalated("s3", node_uid="n", reason="r", error="e", attempts=1)
    assert len(post.posts) == 1  # second notifier still ran


@pytest.mark.unit
def test_build_from_config():
    class Cfg:
        notify_webhook_url = "http://x"
        notify_slack_webhook_url = ""

    hub = build_notifier_hub(Cfg())
    assert hub.enabled

    class Empty:
        notify_webhook_url = ""
        notify_slack_webhook_url = ""

    assert not build_notifier_hub(Empty()).enabled
    assert not NULL_NOTIFIER.enabled
