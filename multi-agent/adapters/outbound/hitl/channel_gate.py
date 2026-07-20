"""
Channel-based ApprovalGate adapter.

Emits an ``approval_required`` event through the channel's outbound
path, then blocks on the channel's inbound path (``wait_for``) until
the human responds or the timeout expires.

Works identically for ``LocalInputCapableChannel`` (foreground,
same-process) and ``RedisInputCapableChannel`` (background,
cross-process) — the channel adapter hides the difference.
"""
import logging
from dataclasses import asdict
from typing import Optional

from mas.core.channels import InputCapableChannel
from mas.core.hitl.models import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResponse,
    HITLConfig,
)
from mas.core.hitl.ports import ApprovalGate

logger = logging.getLogger(__name__)


class ChannelApprovalGate(ApprovalGate):
    """ApprovalGate that uses an InputCapableChannel for transport."""

    def __init__(
        self,
        channel: InputCapableChannel,
        config: HITLConfig,
        audit=None,
    ) -> None:
        from mas.core.audit import NULL_AUDIT
        super().__init__(config)
        self._channel = channel
        self._audit = audit or NULL_AUDIT

    def _send_and_wait(
        self,
        request: ApprovalRequest,
        timeout: float,
    ) -> Optional[ApprovalResponse]:
        args_str = str(request.tool_args)
        channel_sid = self._channel.session_id
        logger.info(
            "HITL approval required: tool=%s, access_mode=%s, "
            "origin=%s (%s), session=%s, timeout=%ss",
            request.tool_name,
            request.tool_access_mode.value,
            request.origin.node_display_name,
            request.origin.node_uid,
            channel_sid,
            timeout,
        )
        logger.debug(
            "HITL request_id=%s, args=%s",
            request.request_id,
            args_str,
        )

        self._channel.emit({
            "type": "approval_required",
            "node": request.origin.node_uid,
            "display_name": request.origin.node_display_name,
            "request_id": request.request_id,
            "approval_type": request.type.value,
            "origin": asdict(request.origin),
            "tool_name": request.tool_name,
            "tool_args": request.tool_args,
            "tool_description": request.tool_description,
            "tool_access_mode": request.tool_access_mode.value,
            "reasoning": request.reasoning,
        })

        self._audit.approval_requested(
            channel_sid, request_id=request.request_id,
            tool_name=request.tool_name, node_uid=request.origin.node_uid)
        raw = self._channel.wait_for(request.request_id, timeout=timeout)
        if raw is None:
            logger.info(
                "HITL timeout: request_id=%s, applying default=%s",
                request.request_id,
                self._config.timeout_decision.value,
            )
            self._audit.approval_resolved(
                channel_sid, request_id=request.request_id,
                decision=self._config.timeout_decision.value, source="timeout")
            return None

        decision = raw.get("decision", "reject")
        logger.info(
            "HITL response: request_id=%s, decision=%s, feedback=%s",
            request.request_id,
            decision,
            raw.get("feedback", ""),
        )

        self._audit.approval_resolved(
            channel_sid, request_id=request.request_id,
            decision=decision, source="human")
        return ApprovalResponse(
            request_id=request.request_id,
            decision=ApprovalDecision(decision),
            feedback=raw.get("feedback", ""),
            modified_args=raw.get("modified_args", {}),
        )
