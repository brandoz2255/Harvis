"""Deployment-wide kill switch for the optional OpenClaw gateway."""
import os


def openclaw_disabled() -> bool:
    return os.getenv("HARVIS_OPENCLAW_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def require_openclaw() -> None:
    if openclaw_disabled():
        raise RuntimeError("OpenClaw gateway is disabled by deployment configuration")
