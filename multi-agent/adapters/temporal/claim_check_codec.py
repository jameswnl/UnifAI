"""
Claim-check PayloadCodec for Temporal ([2.4], issue #14).

State-by-reference without touching workflow/activity code: this codec
sits on the client's DataConverter and, when any payload's serialized
size exceeds ``threshold_bytes``, stashes the whole payload in a
``LargePayloadStore`` and puts a tiny reference on the wire instead. On
decode it fetches the original back. So GraphState can grow past
Temporal's ~2MB gRPC payload cap over a long run — only a claim-check
reference ever crosses the boundary.

Encoding format of the replacement payload:
    metadata = {"encoding": b"binary/claim-check-v1"}
    data     = <utf-8 key bytes>
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Sequence

from temporalio.api.common.v1 import Payload
from temporalio.converter import PayloadCodec

from mas.core.large_payload import LargePayloadStore

logger = logging.getLogger(__name__)

_CLAIM_ENCODING = b"binary/claim-check-v1"
_DEFAULT_THRESHOLD = 1_500_000  # ~1.5MB, safely under Temporal's ~2MB cap


class ClaimCheckCodec(PayloadCodec):

    def __init__(self, store: LargePayloadStore,
                 threshold_bytes: int = _DEFAULT_THRESHOLD) -> None:
        self._store = store
        self._threshold = threshold_bytes

    async def encode(self, payloads: Sequence[Payload]) -> List[Payload]:
        out: List[Payload] = []
        for p in payloads:
            raw = p.SerializeToString()
            if len(raw) > self._threshold:
                key = uuid.uuid4().hex
                self._store.put(key, raw)
                logger.debug("claim-check: offloaded %d bytes as %s", len(raw), key)
                out.append(Payload(
                    metadata={"encoding": _CLAIM_ENCODING},
                    data=key.encode("utf-8"),
                ))
            else:
                out.append(p)
        return out

    async def decode(self, payloads: Sequence[Payload]) -> List[Payload]:
        out: List[Payload] = []
        for p in payloads:
            if p.metadata.get("encoding") == _CLAIM_ENCODING:
                key = p.data.decode("utf-8")
                raw = self._store.get(key)
                if raw is None:
                    raise KeyError(f"claim-check payload {key} not found in store")
                restored = Payload()
                restored.ParseFromString(raw)
                out.append(restored)
            else:
                out.append(p)
        return out


def build_data_converter(store: LargePayloadStore, threshold_bytes: int):
    """pydantic_data_converter with the claim-check codec attached."""
    import dataclasses
    from temporalio.contrib.pydantic import pydantic_data_converter

    return dataclasses.replace(
        pydantic_data_converter,
        payload_codec=ClaimCheckCodec(store, threshold_bytes),
    )
