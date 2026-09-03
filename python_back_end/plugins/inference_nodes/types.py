"""Shapes shared by the inference-nodes plugin.

An *inference node* is any box — this laptop, a desktop across the LAN, a rented GPU
behind a tunnel — that serves models over an OpenAI-shaped HTTP API and is not the
Ollama daemon ``OLLAMA_URL`` points at. FreeToken is the first one; vLLM, SGLang and
llama-server speak the same dialect and fit the same spec unchanged.

Kept free of I/O so ``registry``, ``probe``, ``policy`` and the tests can share it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DIALECTS = ("openai", "ollama")


def clean_base(url: str) -> str:
    """Root URL only. A ``…/v1`` base points at the same server and would double the
    path on every route this plugin builds from it."""
    return (url or "").strip().rstrip("/").removesuffix("/v1").rstrip("/")


@dataclass(frozen=True)
class NodeSpec:
    """How to reach one node. Immutable so a probe can never mutate configuration."""

    name: str
    base_url: str
    dialect: str = "openai"
    label: str = ""
    token: str = ""            # bearer token sent on every call; never surfaced
    hardware: str = ""         # free text for the picker: "RTX 5070 Laptop 8GB"
    source: str = "env"        # "env" | "db"
    enabled: bool = True
    priority: int = 100        # lower wins when two nodes report the same model

    def __post_init__(self) -> None:
        name = (self.name or "").strip()
        if not name:
            raise ValueError("inference node needs a name")
        base = clean_base(self.base_url)
        if not base.startswith(("http://", "https://")):
            raise ValueError(
                f"inference node {name!r}: base_url must be http(s), got {self.base_url!r}"
            )
        dialect = (self.dialect or "openai").strip().lower()
        if dialect not in DIALECTS:
            raise ValueError(f"inference node {name!r}: unknown dialect {self.dialect!r}")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "base_url", base)
        object.__setattr__(self, "dialect", dialect)
        object.__setattr__(self, "label", (self.label or "").strip() or name)
        object.__setattr__(self, "hardware", (self.hardware or "").strip())
        object.__setattr__(self, "token", (self.token or "").strip())

    @property
    def chat_url(self) -> str:
        # Ollama serves the OpenAI shape under /v1 too, so one URL covers both dialects.
        return f"{self.base_url}/v1/chat/completions"

    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def public(self) -> dict:
        """What the API and the picker may see. The token is a boolean here, on purpose."""
        return {
            "name": self.name,
            "label": self.label,
            "base_url": self.base_url,
            "dialect": self.dialect,
            "hardware": self.hardware,
            "source": self.source,
            "enabled": self.enabled,
            "priority": self.priority,
            "has_token": bool(self.token),
        }


@dataclass
class NodeState:
    """What is known about one node as of the last probe.

    Mirrors ``owui_compat.ollama_hosts.HostState`` deliberately: *absent* (the node
    answered and does not have the model) and *unknown* (the node did not answer) are
    different facts, and ``last_good_models`` is what lets a picker keep showing a model
    on a box that is asleep instead of making it vanish.
    """

    spec: NodeSpec
    reachable: bool = False
    models: set[str] = field(default_factory=set)
    ctx: dict[str, int] = field(default_factory=dict)      # model → context window, tokens
    error: str | None = None                                # exception class name or HTTP code
    health: dict = field(default_factory=dict)              # node's /health, when it has one
    stats: dict = field(default_factory=dict)               # node's /v1/stats, when it has one
    last_good_models: set[str] = field(default_factory=set)
    last_good_at: float = 0.0
    probed_at: float = 0.0

    def has(self, model: str) -> bool:
        return bool(model) and model in self.models

    def public(self) -> dict:
        out = self.spec.public()
        out.update(
            reachable=self.reachable,
            error=self.error,
            models=sorted(self.models),
            ctx=dict(self.ctx),
            health=self.health,
            stats=self.stats,
            last_good_models=sorted(self.last_good_models),
            last_good_at=self.last_good_at,
            probed_at=self.probed_at,
        )
        return out
