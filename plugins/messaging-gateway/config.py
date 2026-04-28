"""Gateway configuration — env-var driven."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class GatewayConfig:
    backend_url: str
    gateway_token: str
    enabled_platforms: tuple[str, ...]
    poll_interval_s: float
    poll_timeout_s: float

    # Stub adapter (dev/test only — never enable in prod)
    stub_enabled: bool
    stub_port: int

    # Discord adapter (Phase 1D)
    discord_token: str
    discord_default_user_id: int
    discord_mention_only: bool
    discord_allowed_channel_ids: frozenset[int]

    # Slack adapter (Phase 1C)
    slack_bot_token: str
    slack_signing_secret: str
    slack_app_token: str  # for socket-mode


def _csv_int_set(raw: str) -> frozenset[int]:
    out: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return frozenset(out)


def _csv_str_tuple(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in (raw or "").split(",") if p.strip())


def load_config() -> GatewayConfig:
    return GatewayConfig(
        backend_url=os.getenv("HARVIS_BACKEND_URL", "http://backend:8000").rstrip("/"),
        gateway_token=os.getenv("MESSAGING_GATEWAY_TOKEN", ""),
        enabled_platforms=_csv_str_tuple(os.getenv("ENABLED_PLATFORMS", "stub")),
        poll_interval_s=float(os.getenv("RUN_POLL_INTERVAL_S", "2")),
        poll_timeout_s=float(os.getenv("RUN_POLL_TIMEOUT_S", "1200")),
        stub_enabled=os.getenv("STUB_ENABLED", "false").lower() == "true",
        stub_port=int(os.getenv("STUB_PORT", "18800")),
        discord_token=os.getenv("DISCORD_BOT_TOKEN", "").strip(),
        discord_default_user_id=int(os.getenv("DISCORD_DEFAULT_USER_ID", "0") or "0"),
        discord_mention_only=os.getenv("DISCORD_MENTION_ONLY", "true").lower() == "true",
        discord_allowed_channel_ids=_csv_int_set(os.getenv("DISCORD_ALLOWED_CHANNEL_IDS", "")),
        slack_bot_token=os.getenv("SLACK_BOT_TOKEN", "").strip(),
        slack_signing_secret=os.getenv("SLACK_SIGNING_SECRET", "").strip(),
        slack_app_token=os.getenv("SLACK_APP_TOKEN", "").strip(),
    )
