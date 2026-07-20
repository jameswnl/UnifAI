from mas.elements.common.base_factory import BaseFactory
from mas.elements.nodes.sandbox_agent.config import SandboxAgentNodeConfig
from mas.elements.nodes.sandbox_agent.identifiers import Identifier
from mas.elements.nodes.sandbox_agent.sandbox_agent import SandboxAgentNode


class SandboxAgentNodeFactory(BaseFactory[SandboxAgentNodeConfig, SandboxAgentNode]):

    def accepts(self, cfg: SandboxAgentNodeConfig, element_type: str) -> bool:
        return element_type == Identifier.TYPE

    def create(self, cfg: SandboxAgentNodeConfig, **deps) -> SandboxAgentNode:
        spawner = deps.pop("sandbox_spawner", None)
        if spawner is None:
            raise ValueError(
                "sandbox_agent_node requires a sandbox_spawner dependency. "
                "Set SANDBOX_SPAWNER=podman or SANDBOX_SPAWNER=k8s."
            )
        image = cfg.image or deps.pop("sandbox_image", "")
        if not image:
            raise ValueError(
                "sandbox_agent_node requires an image. Set it in the node "
                "config or via the SANDBOX_IMAGE environment variable."
            )
        return SandboxAgentNode(
            spawner=spawner,
            image=image,
            system_prompt=cfg.system_prompt,
            output_schema=cfg.output_schema,
            allowed_tools=cfg.allowed_tools,
            denied_tools=cfg.denied_tools,
            timeout_seconds=cfg.timeout_seconds,
        )
