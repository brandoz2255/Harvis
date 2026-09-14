"""Inference nodes — other model servers Harvis can send a chat to.

The Ollama daemon at ``OLLAMA_URL`` stays the default and keeps every lane that
depends on its native API (model listing, task detection, the resolver). A *node* is
an additional OpenAI-dialect server — FreeToken today — that ``model_proxy`` checks
first when a model name is not one Ollama knows. See ``docs/inference-nodes.md``.
"""

from .policy import shape_body as shape_body_for_node, thinking_mode  # noqa: F401
from .probe import (  # noqa: F401
    attach,
    invalidate,
    live_stats,
    node_for_url,
    resolve as resolve_node,
    snapshot,
    unreachable_models,
)
from .registry import configured_nodes, env_nodes, parse_env  # noqa: F401
from .taskgen import complete as node_complete  # noqa: F401
from .types import NodeSpec, NodeState  # noqa: F401
