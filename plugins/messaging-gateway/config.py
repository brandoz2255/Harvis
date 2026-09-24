"""Gateway configuration.

Two sources feed the supervisor:

* The Harvis backend's per-user platform settings (the Messaging page). This
  is the normal path: the gateway pulls ``/api/messaging/gateway/config``
  every ``sync_interval_s`` seconds and whenever the backend pings
  ``POST /resync`` on the control port.
* Container environment variables (``ENABLED_PLATFORMS`` plus each
  platform's ``*_TOKEN``). Kept so installs that predate the settings page
  keep working; see :func:`env_fallback_specs`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from platforms.base import AdapterSpec


@dataclass(frozen=True)
class GatewayConfig:
    backend_url: str
    gateway_token: str
    enabled_platforms: tuple[str, ...]
    poll_interval_s: float
    poll_timeout_s: float
    sync_interval_s: float

    # Control port: /health, /status, /resync, /send-test, /webhook, stub /inject
    control_port: int

    # Stub adapter (dev/test only — never enable in prod)
    stub_enabled: bool


def _csv_str_tuple(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in (raw or "").split(",") if p.strip())


def load_config() -> GatewayConfig:
    return GatewayConfig(
        backend_url=os.getenv("HARVIS_BACKEND_URL", "http://backend:8000").rstrip("/"),
        gateway_token=os.getenv("MESSAGING_GATEWAY_TOKEN", ""),
        enabled_platforms=_csv_str_tuple(os.getenv("ENABLED_PLATFORMS", "stub")),
        poll_interval_s=float(os.getenv("RUN_POLL_INTERVAL_S", "2")),
        poll_timeout_s=float(os.getenv("RUN_POLL_TIMEOUT_S", "1200")),
        sync_interval_s=float(os.getenv("SETTINGS_SYNC_INTERVAL_S", "15")),
        control_port=int(os.getenv("CONTROL_PORT", os.getenv("STUB_PORT", "18800"))),
        stub_enabled=os.getenv("STUB_ENABLED", "false").lower() == "true",
    )


# Environment variables each platform reads when configured the legacy way.
# Keys match the Harvis messaging catalog so an adapter reads one shape.
ENV_FALLBACK_KEYS: dict[str, tuple[str, ...]] = {
    "discord": (
        "DISCORD_BOT_TOKEN",
        "DISCORD_ALLOWED_USERS",
        "DISCORD_DEFAULT_USER_ID",
        "DISCORD_MENTION_ONLY",
        "DISCORD_ALLOWED_CHANNEL_IDS",
    ),
    "slack": ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_ALLOWED_USERS"),
    "telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS"),
    "matrix": (
        "MATRIX_HOMESERVER",
        "MATRIX_ACCESS_TOKEN",
        "MATRIX_USER_ID",
        "MATRIX_ALLOWED_USERS",
    ),
    "email": (
        "EMAIL_ADDRESS",
        "EMAIL_PASSWORD",
        "EMAIL_IMAP_HOST",
        "EMAIL_IMAP_PORT",
        "EMAIL_SMTP_HOST",
        "EMAIL_SMTP_PORT",
        "EMAIL_ALLOWED_USERS",
    ),
    "whatsapp_cloud": (
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_VERIFY_TOKEN",
        "WHATSAPP_APP_SECRET",
        "WHATSAPP_ALLOWED_USERS",
    ),
    "signal": ("SIGNAL_HTTP_URL", "SIGNAL_ACCOUNT", "SIGNAL_ALLOWED_USERS"),
    "stub": (),
}


def env_fallback_specs(cfg: GatewayConfig) -> list[AdapterSpec]:
    """Adapters requested through ENABLED_PLATFORMS + env vars (legacy path)."""
    specs: list[AdapterSpec] = []
    for name in cfg.enabled_platforms:
        if name == "stub":
            if cfg.stub_enabled:
                specs.append(AdapterSpec(platform="stub", owner_user_id=None, env={}, source="env"))
            continue
        keys = ENV_FALLBACK_KEYS.get(name)
        if keys is None:
            continue
        env = {k: os.getenv(k, "").strip() for k in keys if os.getenv(k, "").strip()}
        if not env:
            continue
        owner = None
        raw_owner = env.get("DISCORD_DEFAULT_USER_ID") if name == "discord" else None
        if raw_owner and raw_owner.isdigit() and int(raw_owner) > 0:
            owner = int(raw_owner)
        specs.append(AdapterSpec(platform=name, owner_user_id=owner, env=env, source="env"))
    return specs
