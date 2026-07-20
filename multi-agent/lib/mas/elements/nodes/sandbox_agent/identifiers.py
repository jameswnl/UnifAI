from dataclasses import dataclass
from enum import Enum


class Identifier(str, Enum):
    TYPE = "sandbox_agent_node"


@dataclass(frozen=True)
class META:
    name: str = "Sandbox Agent"
    description: str = (
        "Runs an agent step in an ephemeral sandbox container via the "
        "/v1/agent/run contract. Each execution spawns a fresh container "
        "and destroys it on completion."
    )
    tags: tuple = ("sandbox", "agent", "ephemeral", "container")
