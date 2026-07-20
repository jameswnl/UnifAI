"""
Temporal client factory.

Provides an async function to connect to the Temporal server
using configuration from AppConfig.

Uses pydantic_data_converter so Temporal natively serializes/deserializes
Pydantic models — no manual model_dump / model_validate needed in
workflow and activity params.

Shared by both inbound (worker) and outbound (executor/submitter)
Temporal adapters.
"""
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from config.app_config import AppConfig
from global_utils.utils.util import get_temporal_url


def _build_data_converter(cfg: AppConfig):
    """pydantic converter, optionally with the claim-check codec ([2.4], #14).

    Enabled by ``large_payload_offload`` on the postgres backend so large
    GraphState payloads are stashed in the DB and referenced on the wire,
    keeping every Temporal payload under the ~2MB cap.
    """
    if getattr(cfg, "large_payload_offload", False) and cfg.db_backend == "postgres":
        from outbound.postgres.blob_store import PgLargePayloadStore
        from temporal.claim_check_codec import build_data_converter
        store = PgLargePayloadStore(dsn=cfg.postgres_dsn)
        return build_data_converter(store, cfg.large_payload_threshold_bytes)
    return pydantic_data_converter


async def get_temporal_client() -> Client:
    cfg = AppConfig.get_instance()
    return await Client.connect(
        get_temporal_url(),
        namespace=cfg.temporal_namespace,
        data_converter=_build_data_converter(cfg),
    )
