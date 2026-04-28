"""ACP adapter config — env-var driven."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ACPConfig:
    backend_url: str
    gateway_token: str
    default_user_id: int
    poll_interval_s: float
    poll_timeout_s: float


def load_config() -> ACPConfig:
    return ACPConfig(
        backend_url=os.getenv("HARVIS_BACKEND_URL", "http://localhost:9000").rstrip("/"),
        gateway_token=os.getenv("MESSAGING_GATEWAY_TOKEN", ""),
        default_user_id=int(os.getenv("HARVIS_USER_ID", "0") or "0"),
        poll_interval_s=float(os.getenv("RUN_POLL_INTERVAL_S", "1.5")),
        poll_timeout_s=float(os.getenv("RUN_POLL_TIMEOUT_S", "1200")),
    )
