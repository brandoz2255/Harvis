"""Harvis ACP adapter — exposes Harvis as an Agent Client Protocol agent.

The editor (Zed, VS Code, etc.) launches this module as a subprocess and
speaks JSON-RPC over its stdio. Each prompt routes through the existing
Harvis messaging plugin (POST /api/messaging/inbound), so ACP is effectively
"another platform" in the same dispatch chain Discord and Slack use.

Adapted from NousResearch/hermes-agent (MIT) — acp_adapter/. The Hermes
implementation is ~2,300 lines and tightly coupled to the AIAgent runtime;
this port keeps the protocol surface and replaces the runtime with HTTP
calls to the Harvis backend.
"""

__version__ = "0.1.0"
