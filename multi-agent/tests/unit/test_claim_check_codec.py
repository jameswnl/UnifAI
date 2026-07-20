"""Unit tests for the Temporal claim-check codec ([2.4], issue #14)."""

import asyncio

import pytest

from mas.core.large_payload import LargePayloadStore


class MemoryBlobStore(LargePayloadStore):
    def __init__(self):
        self.blobs = {}

    def put(self, key, data):
        self.blobs[key] = data

    def get(self, key):
        return self.blobs.get(key)

    def delete(self, key):
        self.blobs.pop(key, None)


def _payload(data: bytes):
    from temporalio.api.common.v1 import Payload
    return Payload(metadata={"encoding": b"json/plain"}, data=data)


def _roundtrip(codec, payloads):
    async def go():
        encoded = await codec.encode(payloads)
        decoded = await codec.decode(encoded)
        return encoded, decoded
    return asyncio.run(go())


@pytest.mark.unit
def test_small_payload_passes_through_unchanged():
    from temporal.claim_check_codec import ClaimCheckCodec

    store = MemoryBlobStore()
    codec = ClaimCheckCodec(store, threshold_bytes=1000)
    p = _payload(b"x" * 100)

    encoded, decoded = _roundtrip(codec, [p])
    assert encoded[0].data == b"x" * 100          # not offloaded
    assert store.blobs == {}
    assert decoded[0].data == b"x" * 100


@pytest.mark.unit
def test_large_payload_is_offloaded_and_restored():
    from temporal.claim_check_codec import ClaimCheckCodec

    store = MemoryBlobStore()
    codec = ClaimCheckCodec(store, threshold_bytes=1000)
    big = b"y" * 5000
    p = _payload(big)

    encoded, decoded = _roundtrip(codec, [p])
    # On the wire it's a tiny reference, not the 5KB payload
    assert encoded[0].metadata["encoding"] == b"binary/claim-check-v1"
    assert len(encoded[0].data) < 100
    assert len(store.blobs) == 1
    # Decoded payload is byte-identical to the original
    assert decoded[0].data == big
    assert decoded[0].metadata["encoding"] == b"json/plain"


@pytest.mark.unit
def test_mixed_batch():
    from temporal.claim_check_codec import ClaimCheckCodec

    store = MemoryBlobStore()
    codec = ClaimCheckCodec(store, threshold_bytes=1000)
    small, big = _payload(b"s"), _payload(b"b" * 5000)

    _, decoded = _roundtrip(codec, [small, big])
    assert decoded[0].data == b"s"
    assert decoded[1].data == b"b" * 5000
    assert len(store.blobs) == 1  # only the big one offloaded


@pytest.mark.unit
def test_missing_claim_raises():
    from temporal.claim_check_codec import ClaimCheckCodec
    from temporalio.api.common.v1 import Payload

    codec = ClaimCheckCodec(MemoryBlobStore(), threshold_bytes=1000)
    dangling = Payload(metadata={"encoding": b"binary/claim-check-v1"},
                       data=b"nonexistent-key")

    with pytest.raises(KeyError):
        asyncio.run(codec.decode([dangling]))
