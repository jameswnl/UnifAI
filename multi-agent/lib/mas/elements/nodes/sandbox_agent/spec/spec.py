from mas.core.enums import ResourceCategory
from mas.elements.common.base_element_spec import BaseElementSpec
from mas.elements.nodes.sandbox_agent.config import SandboxAgentNodeConfig
from mas.elements.nodes.sandbox_agent.identifiers import Identifier, META
from mas.elements.nodes.sandbox_agent.sandbox_agent import SandboxAgentNode
from mas.elements.nodes.sandbox_agent.sandbox_agent_node_factory import (
    SandboxAgentNodeFactory,
)


class SandboxAgentNodeElementSpec(BaseElementSpec):
    category = ResourceCategory.NODE
    type_key = Identifier.TYPE
    name = META.name
    description = META.description
    config_schema = SandboxAgentNodeConfig
    factory_cls = SandboxAgentNodeFactory
    reads = SandboxAgentNode.total_reads()
    writes = SandboxAgentNode.total_writes()
    tags = META.tags
