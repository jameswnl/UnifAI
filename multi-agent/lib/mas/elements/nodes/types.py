from typing import Union, Annotated
from pydantic import Field

from mas.elements.nodes.custom_agent.config import CustomAgentNodeConfig
from mas.elements.nodes.mock_agent.config import MockAgentNodeConfig
from mas.elements.nodes.llm_merger.config import MergerLLMNodeConfig
from mas.elements.nodes.final_answer.config import FinalAnswerNodeConfig
from mas.elements.nodes.user_question.config import UserQuestionNodeConfig
from mas.elements.nodes.branch_chooser.config import BranchChooserNodeConfig
from mas.elements.nodes.orchestrator.config import OrchestratorNodeConfig

_node_configs: list[type] = [
    CustomAgentNodeConfig,
    MockAgentNodeConfig,
    # MergerLLMNodeConfig,
    FinalAnswerNodeConfig,
    UserQuestionNodeConfig,
    BranchChooserNodeConfig,
    OrchestratorNodeConfig,
]

# Extra-dependent node configs: each import needs its optional dependency
# ([a2a], [langgraph], [claude]). A missing extra removes the node type from
# NodeSpec; a blueprint referencing it then fails validation with an unknown
# discriminator value instead of crashing the process at import time.
try:
    from mas.elements.nodes.a2a_agent.config import A2AAgentNodeConfig
    _node_configs.append(A2AAgentNodeConfig)
except ImportError:
    pass

try:
    from mas.elements.nodes.deep_agent.config import DeepAgentNodeConfig
    _node_configs.append(DeepAgentNodeConfig)
except ImportError:
    pass

try:
    from mas.elements.nodes.claude_agent.config import ClaudeAgentNodeConfig
    _node_configs.append(ClaudeAgentNodeConfig)
except ImportError:
    pass

# Union type for backward compatibility with blueprints
NodeSpec = Annotated[
    Union[tuple(_node_configs)],
    Field(discriminator="type"),
]
