"""
Application-level node retry with failure history (plan item [2.1], issue #11).

Why not the engine's native retries (e.g. Temporal RetryPolicy): those
re-run a node with an *identical* input, so an agent's second attempt has
no idea a first attempt happened and repeats the same failure. This loop
lives above the engine seam: on failure it records an attempt — into the
``failure_history`` state channel *and* as a conversation message — so
the next attempt (and, on exhaustion, the escalation package) sees what
was already tried. Used by both engines:

- LangGraph: node callables are wrapped at plan-compile time
  (``BaseGraphBuilder.compile_from_plan``)
- Temporal: ``NodeExecutor.execute_node`` wraps the node invocation
  (native activity retries stay for transport-level errors only)

Per-step policy is declared in the blueprint step meta::

    plan:
      - uid: fix_step
        node: fixer
        meta:
          max_retries: 2        # attempts = max_retries + 1; default 0
          retry_backoff_s: 5.0  # sleep between attempts; default 0
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)


class RetriesExhaustedError(Exception):
    """All attempts for a step failed. Carries the attempt history."""

    def __init__(self, node_uid: str, attempts: list[dict], last: Exception):
        self.node_uid = node_uid
        self.attempts = attempts
        self.last = last
        super().__init__(
            f"step '{node_uid}' failed after {len(attempts)} attempt(s): {last}"
        )


def _record_failure(state: Any, node_uid: str, attempt: int,
                    max_attempts: int, error: Exception) -> dict:
    record = {
        "node_uid": node_uid,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "error": f"{type(error).__name__}: {error}",
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    # In-place mutation: the same GraphState object flows through all
    # attempts (and, on the Temporal path, is serialized after the activity),
    # and this loop is infrastructure — StateView channel permissions don't
    # apply here.
    try:
        state["failure_history"].append(record)
        if attempt < max_attempts:
            from mas.elements.llms.common.chat.message import ChatMessage
            # Message-driven agents read the conversation; give the next
            # attempt explicit context so it can adapt instead of repeating.
            state["messages"].append(ChatMessage(
                role="user",
                sender_id="retry-loop",
                content=(
                    f"[retry context] Attempt {attempt}/{max_attempts} of step "
                    f"'{node_uid}' failed with: {record['error']}. "
                    "Do not repeat the same approach — adjust based on this failure."
                ),
                metadata={"retry_context": True},
            ))
    except Exception:  # noqa: BLE001 — recording must not mask the real error
        logger.exception("failed to record failure history for %s", node_uid)
    return record


def run_node_with_retry(node_uid: str, run: Callable[[], Any],
                        state: Any, meta: Any) -> Any:
    """Run a node with per-step retry policy from its StepMeta."""
    max_retries = int(getattr(meta, "max_retries", 0) or 0)
    backoff_s = float(getattr(meta, "retry_backoff_s", 0.0) or 0.0)
    max_attempts = max_retries + 1

    attempts: list[dict] = []
    for attempt in range(1, max_attempts + 1):
        try:
            return run()
        except Exception as exc:  # noqa: BLE001 — policy decides, not us
            attempts.append(
                _record_failure(state, node_uid, attempt, max_attempts, exc))
            if attempt >= max_attempts:
                if max_retries:
                    raise RetriesExhaustedError(node_uid, attempts, exc) from exc
                raise
            logger.warning("step %s attempt %d/%d failed (%s); retrying",
                           node_uid, attempt, max_attempts, exc)
            if backoff_s:
                time.sleep(backoff_s)


def wrap_step_func(uid: str, func: Any) -> Callable:
    """Wrap a plan-step callable (LangGraph path) with the retry loop.

    Step meta is read lazily from the node's bound StepContext at call
    time (context is injected during runtime-plan build).
    """

    def _wrapped(state, config=None, **kwargs):
        meta = None
        try:
            meta = func.get_context().metadata
        except Exception:  # noqa: BLE001 — nodes without context: no retries
            pass
        if config is not None:
            kwargs["config"] = config
        return run_node_with_retry(
            uid, lambda: func(state, **kwargs), state, meta)

    # LangGraph inspects callables; keep a useful name
    _wrapped.__name__ = f"retrying_{uid}"
    return _wrapped
