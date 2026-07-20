from typing import Literal, Optional

from pydantic import Field

from mas.elements.nodes.common.base_config import NodeBaseConfig


class SandboxAgentNodeConfig(NodeBaseConfig):
    type: Literal["sandbox_agent_node"] = "sandbox_agent_node"
    image: str = Field(
        default="",
        description="Sandbox container image. Falls back to SANDBOX_IMAGE config.",
    )
    system_prompt: str = Field(
        default="",
        description="System prompt passed to the sandbox agent.",
    )
    output_schema: Optional[dict] = Field(
        default=None,
        description="JSON Schema the sandbox agent must conform to.",
    )
    allowed_tools: Optional[list[str]] = Field(
        default=None,
        description="Tool allowlist for the sandbox agent.",
    )
    denied_tools: Optional[list[str]] = Field(
        default=None,
        description="Tool denylist for the sandbox agent.",
    )
    timeout_seconds: int = Field(
        default=300,
        ge=5,
        le=600,
        description="Max execution time for the sandbox.",
    )
