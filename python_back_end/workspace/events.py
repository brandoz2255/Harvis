"""The event every workspace lane streams: token, tool_call, tool_result, log, done, error.

It started life as the OpenClaw gateway's event, which is why the old name is still exported.
"""

import json
from typing import Optional


class WorkspaceEvent:
    """A single event streamed from a workspace run."""

    def __init__(self, event_type: str, data: dict):
        self.type = event_type   # "token" | "tool_call" | "tool_result" | "log" | "done" | "error"
        self.data = data
        # Sub-agent tracking.
        # run_id  — the lane's own id for this agent invocation.
        # agent_label — human-readable label: "Agent" | "Sub-Agent 1" | "Sub-Agent 2" …
        self.run_id: Optional[str] = None
        self.agent_label: Optional[str] = None

    def to_sse(self) -> str:
        """Format as a Server-Sent Event string for streaming to the frontend."""
        payload: dict = {"type": self.type, **self.data}
        if self.run_id:
            payload["run_id"] = self.run_id
        if self.agent_label:
            payload["agent_label"] = self.agent_label
        return f"data: {json.dumps(payload)}\n\n"


OpenClawEvent = WorkspaceEvent
