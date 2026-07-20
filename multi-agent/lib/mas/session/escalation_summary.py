"""
Escalation summary ([4.5], issue #27).

Turns a raw escalation package (the audit record + attempt history) into
a short, human-readable brief so the on-call engineer doesn't start from
a raw transcript. The deterministic template summary is always available
and testable; an optional LLM pass rewrites it more fluently when a
summarizer LLM is configured, degrading cleanly to the template on any
error or when no LLM is present.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def build_template_summary(escalation: Dict[str, Any]) -> str:
    """Deterministic human brief from the escalation audit record."""
    node = escalation.get("node_uid") or "unknown step"
    reason = escalation.get("reason", "unknown")
    attempts: List[Dict[str, Any]] = escalation.get("attempts") or []
    error = escalation.get("error", "")

    lines = [
        f"Escalation: step '{node}' handed off to a human ({reason}).",
    ]
    if attempts:
        lines.append(f"The agent made {len(attempts)} attempt(s):")
        for a in attempts:
            lines.append(f"  - attempt {a.get('attempt', '?')}: "
                         f"{a.get('error', 'no detail')}")
    if error:
        lines.append(f"Final error: {error}")
    lines.append("Recommended: review the transcript and audit trail, then "
                 "resolve the underlying issue before re-running.")
    return "\n".join(lines)


class EscalationSummarizer:
    """Builds a summary, optionally refining it with an LLM."""

    def __init__(self, llm: Optional[Any] = None) -> None:
        self._llm = llm

    def summarize(self, escalation: Dict[str, Any]) -> str:
        template = build_template_summary(escalation)
        if self._llm is None:
            return template
        try:
            from mas.elements.llms.common.chat.message import ChatMessage, Role
            prompt = (
                "Rewrite the following automation-escalation notes as a concise "
                "on-call brief (max 4 sentences), preserving all facts:\n\n"
                + template
            )
            reply = self._llm.chat([ChatMessage(role=Role.USER, content=prompt)])
            text = getattr(reply, "content", "").strip()
            return text or template
        except Exception:  # noqa: BLE001 — LLM is an enhancement, not a gate
            logger.warning("LLM escalation summary failed; using template",
                           exc_info=True)
            return template
