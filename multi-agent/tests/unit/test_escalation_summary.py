"""Unit tests for escalation summary ([4.5], issue #27)."""

import pytest

from mas.session.escalation_summary import (
    EscalationSummarizer,
    build_template_summary,
)


_ESCALATION = {
    "type": "session.escalated",
    "node_uid": "fix_step",
    "reason": "retries_exhausted",
    "error": "ConnectionError: db unreachable",
    "attempts": [
        {"attempt": 1, "error": "ConnectionError: timeout"},
        {"attempt": 2, "error": "ConnectionError: db unreachable"},
    ],
}


@pytest.mark.unit
def test_template_summary_contains_facts():
    text = build_template_summary(_ESCALATION)
    assert "fix_step" in text
    assert "retries_exhausted" in text
    assert "2 attempt(s)" in text
    assert "attempt 1" in text and "attempt 2" in text
    assert "db unreachable" in text


@pytest.mark.unit
def test_template_handles_missing_fields():
    text = build_template_summary({"type": "session.escalated"})
    assert "unknown step" in text
    assert "Recommended" in text


@pytest.mark.unit
def test_summarizer_without_llm_returns_template():
    s = EscalationSummarizer(llm=None)
    assert s.summarize(_ESCALATION) == build_template_summary(_ESCALATION)


@pytest.mark.unit
def test_summarizer_uses_llm_when_present():
    class FakeReply:
        content = "On-call brief: fix_step failed twice on DB connectivity."

    class FakeLLM:
        def __init__(self):
            self.calls = []

        def chat(self, messages):
            self.calls.append(messages)
            return FakeReply()

    llm = FakeLLM()
    out = EscalationSummarizer(llm=llm).summarize(_ESCALATION)
    assert out == "On-call brief: fix_step failed twice on DB connectivity."
    # the prompt carried the template facts
    assert "fix_step" in llm.calls[0][0].content


@pytest.mark.unit
def test_summarizer_falls_back_when_llm_raises():
    class BoomLLM:
        def chat(self, messages):
            raise RuntimeError("llm down")

    out = EscalationSummarizer(llm=BoomLLM()).summarize(_ESCALATION)
    assert out == build_template_summary(_ESCALATION)


@pytest.mark.unit
def test_summarizer_falls_back_on_empty_llm_output():
    class EmptyReply:
        content = "   "

    class EmptyLLM:
        def chat(self, messages):
            return EmptyReply()

    out = EscalationSummarizer(llm=EmptyLLM()).summarize(_ESCALATION)
    assert out == build_template_summary(_ESCALATION)
