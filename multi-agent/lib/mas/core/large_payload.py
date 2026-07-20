"""
Large-payload (blob) store port ([2.4], issue #14).

Backing store for the Temporal claim-check codec: oversized activity /
workflow payloads are stashed here and replaced on the wire with a small
reference, keeping every Temporal payload under the ~2MB gRPC cap even
as GraphState (chat history, artifacts) grows across a long run.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class LargePayloadStore(ABC):

    @abstractmethod
    def put(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def get(self, key: str) -> Optional[bytes]: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...
