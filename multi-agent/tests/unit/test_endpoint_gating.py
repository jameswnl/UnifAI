"""
Harness-profile feature gating (plan item [0.2]).

Verifies that PLATFORM_ENDPOINTS=false exposes only the execution surface
and that the platform-only endpoint groups register when enabled.
"""

import pytest
from flask import Flask

from inbound.flask.endpoints import register_all_endpoints


EXECUTION_PREFIXES = (
    "/api/health",
    "/api/blueprints",
    "/api/sessions",
    "/api/catalog",
    "/api/resources",
    "/api/graph",
    "/api/actions",
    "/api/credentials",
)

PLATFORM_PREFIXES = (
    "/api/shares",
    "/api/statistics",
    "/api/templates",
    "/api/collaboration",
    "/api/workspace",
)


def _rules(platform_endpoints: bool) -> set[str]:
    app = Flask(__name__)
    register_all_endpoints(app, platform_endpoints=platform_endpoints)
    return {rule.rule for rule in app.url_map.iter_rules()}


@pytest.mark.unit
def test_harness_profile_exposes_execution_surface_only():
    rules = _rules(platform_endpoints=False)

    for prefix in EXECUTION_PREFIXES:
        assert any(r.startswith(prefix) for r in rules), f"missing {prefix}"

    for prefix in PLATFORM_PREFIXES:
        assert not any(r.startswith(prefix) for r in rules), f"unexpected {prefix}"


@pytest.mark.unit
def test_platform_profile_exposes_everything():
    rules = _rules(platform_endpoints=True)

    for prefix in EXECUTION_PREFIXES + PLATFORM_PREFIXES:
        assert any(r.startswith(prefix) for r in rules), f"missing {prefix}"


@pytest.mark.unit
def test_node_spec_builds_without_optional_extras():
    # NodeSpec must be importable and contain the always-available core
    # configs regardless of which optional extras are installed.
    from mas.elements.nodes.types import NodeSpec, _node_configs
    from mas.elements.nodes.custom_agent.config import CustomAgentNodeConfig

    assert CustomAgentNodeConfig in _node_configs
    assert len(_node_configs) >= 7
    assert NodeSpec is not None
