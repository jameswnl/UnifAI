import secrets
from global_utils.config.config import SharedConfig


class AppConfig(SharedConfig):
    mongo_db: str = "UnifAI"
    blueprint_coll: str = "blueprints"
    resources_coll: str = "resources"
    session_coll: str = "workflow_sessions"
    shares_coll: str = "shares"
    templates_coll: str = "templates"
    credentials_coll: str = "credentials"
    server_configs_coll: str = "server_configs"
    hostname: str = "0.0.0.0"
    port: str = "8002"
    version: str = "1.0.0"
    admin_allowed_users: list = []  # Populate with user_ids (usernames) to grant admin access
    secret_key: str = ""

    # Session cookie — must match Identity so Flask never re-signs with different attributes
    session_cookie_secure: bool = False
    session_cookie_http_only: bool = True
    session_cookie_samesite: str = "Lax"

    # Storage
    shared_storage: str = "/app/shared"
    # Platform-only API surface (shares, statistics, templates, collaboration,
    # workspace). The harness deployment profile sets PLATFORM_ENDPOINTS=false.
    platform_endpoints: bool = True
    # Persistence backend: "mongo" (default, full platform) or "postgres"
    # (harness profile; currently requires PLATFORM_ENDPOINTS=false).
    db_backend: str = "mongo"
    postgres_dsn: str = "postgresql://unifai:unifai@localhost:5432/unifai"
    # Durable transcript: persist every session event to the database
    # (session_events). Disable only for throwaway dev runs.
    transcript_persistence: bool = True
    # Audit trail: typed records for lifecycle + approval decisions
    audit_enabled: bool = True
    # Notifier targets ([2.6]): empty = disabled
    notify_webhook_url: str = ""
    notify_slack_webhook_url: str = ""
    # Durable HITL ([2.2], issue #12): persist pending approvals and allow
    # long waits. Default 24h replaces the old hard 300s cap.
    durable_approvals: bool = True
    hitl_timeout_seconds: float = 86400.0
    hitl_response_ttl_seconds: int = 86400
    # Thin harness auth ([4.2], issue #24)
    harness_auth_enabled: bool = False
    harness_auth_mode: str = "bearer"        # bearer | k8s
    harness_auth_bearer_token: str = ""
    harness_auth_exempt_prefixes: list = ["/api/health", "/api/triggers/webhook"]
    k8s_api_server: str = "https://kubernetes.default.svc"
    k8s_ca_cert: str = ""
    k8s_reviewer_token: str = ""
    # Observability ([4.3], issue #25)
    otel_enabled: bool = False
    otel_exporter: str = "console"       # console | otlp
    otel_endpoint: str = ""              # OTLP collector base URL
    # Triggers ([4.1], issue #23)
    triggers_enabled: bool = True
    trigger_webhook_token: str = ""      # empty = open (dev); set to require header
    scheduler_enabled: bool = False
    scheduler_poll_seconds: int = 30
    # Engine ([4.4], issue #26): default to the in-process engine so the
    # out-of-box harness/installer profile needs no Temporal. Set
    # ENGINE_NAME=temporal for the distributed/OpenShift profile.
    engine_name: str = "langgraph"
    # LangGraph durability ([2.3]): Postgres checkpointer + resume-on-startup
    # (requires engine_name=langgraph and db_backend=postgres)
    langgraph_checkpointing: bool = False
    resume_on_startup: bool = False
    # Temporal large-payload offload ([2.4]): stash oversized payloads in
    # Postgres (claim-check codec) so GraphState can exceed Temporal's ~2MB cap
    large_payload_offload: bool = False
    large_payload_threshold_bytes: int = 1_500_000
    temporal_task_queue: str = "graph-engine"
    # Redis streaming tuning
    redis_stream_ttl: int = 3600
    redis_stream_block_ms: int = 5000
    redis_stream_batch_size: int = 50

    # Collaboration hub — Redis-backed multi-user session presence ──────────
    collaboration_presence_ttl: int = 300
    collaboration_edit_lock_ttl_sec: int = 180

    # Directory provider: "sso" (via Identity pod) or "" to disable
    directory_provider: str = ""
    directory_timeout: int = 10

    # Identity HTTP base for directory + teams HTTP APIs (optional override).
    # When empty, ``identity_host`` is used for ``IdentityDirectoryClient`` and auth decorators.
    directory_sso_url: str = ""

    # Auth
    oauth_state_secret: str = secrets.token_urlsafe(32)
    identity_host: str = "http://localhost:13456"
    oauth_callback_path: str = "/api/credentials/callback"
    identity_provider_mode: str = ""
    credential_encryption_key: str = ""

