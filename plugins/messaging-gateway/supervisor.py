"""Adapter supervisor — keeps the running adapters equal to the desired set.

Desired = the backend's per-user platform settings (pulled through the
bridge) plus the env-var fallback specs. Each spec is keyed
``platform:owner`` and fingerprinted on its settings, so saving a token in
the Harvis UI restarts exactly that adapter, disabling a platform stops it,
and nothing needs a container restart.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

from platforms.base import AdapterSpec, BasePlatformAdapter

logger = logging.getLogger(__name__)

AdapterFactory = Callable[[AdapterSpec], BasePlatformAdapter]
InboundHandler = Callable[[BasePlatformAdapter, object], Awaitable[None]]


def build_adapter(spec: AdapterSpec) -> BasePlatformAdapter:
    """Import lazily so a platform with a missing dependency only breaks itself."""
    name = spec.platform
    if name == "stub":
        from platforms.stub import StubAdapter
        return StubAdapter(spec)
    if name == "slack":
        from platforms.slack import SlackAdapter
        return SlackAdapter(spec)
    if name == "discord":
        from platforms.discord import DiscordAdapter
        return DiscordAdapter(spec)
    if name == "telegram":
        from platforms.telegram import TelegramAdapter
        return TelegramAdapter(spec)
    if name == "matrix":
        from platforms.matrix import MatrixAdapter
        return MatrixAdapter(spec)
    if name == "email":
        from platforms.email import EmailAdapter
        return EmailAdapter(spec)
    if name == "whatsapp_cloud":
        from platforms.whatsapp_cloud import WhatsAppCloudAdapter
        return WhatsAppCloudAdapter(spec)
    if name == "signal":
        from platforms.signal import SignalAdapter
        return SignalAdapter(spec)
    raise ValueError(f"unsupported platform: {name}")


RETRY_AFTER_S = 60.0

SUPPORTED_PLATFORMS: tuple[str, ...] = (
    "telegram", "slack", "discord", "matrix", "email", "whatsapp_cloud", "signal", "stub",
)


class _Running:
    __slots__ = ("adapter", "task", "spec")

    def __init__(self, adapter: BasePlatformAdapter, task: asyncio.Task, spec: AdapterSpec):
        self.adapter = adapter
        self.task = task
        self.spec = spec


class AdapterSupervisor:
    def __init__(self, inbound: InboundHandler, factory: AdapterFactory = build_adapter):
        self._inbound = inbound
        self._factory = factory
        self._running: dict[str, _Running] = {}
        self._failed: dict[str, str] = {}  # key -> error for specs whose adapter could not be built
        self._lock = asyncio.Lock()
        self._started_at = time.time()
        self.last_sync_at: Optional[float] = None
        self.last_sync_ok: bool = False
        self.config_version: Optional[str] = None

    # ------------------------------------------------------------------
    # Reconcile
    # ------------------------------------------------------------------

    async def sync(self, desired: list[AdapterSpec]) -> dict:
        """Start/restart/stop adapters so the running set matches ``desired``."""
        async with self._lock:
            wanted: dict[str, AdapterSpec] = {}
            for spec in desired:
                if spec.platform not in SUPPORTED_PLATFORMS:
                    continue
                # Settings win over env for the same platform+owner key.
                if spec.key in wanted and spec.source == "env":
                    continue
                wanted[spec.key] = spec

            changed = {"started": [], "restarted": [], "stopped": []}

            for key in list(self._running):
                if key not in wanted:
                    await self._stop(key)
                    changed["stopped"].append(key)
                elif self._running[key].spec.fingerprint != wanted[key].fingerprint:
                    await self._stop(key)
                    self._start(wanted[key])
                    changed["restarted"].append(key)
                elif self._running[key].task.done() and self._retry_due(key):
                    # Crashed or exited: retry with the same spec, but not
                    # more often than once a minute so a bad token doesn't
                    # hammer the platform's API.
                    await self._stop(key)
                    self._start(wanted[key])
                    changed["restarted"].append(key)

            for key, spec in wanted.items():
                if key not in self._running and key not in changed["restarted"]:
                    self._start(spec)
                    changed["started"].append(key)

            for key in list(self._failed):
                if key not in wanted:
                    self._failed.pop(key, None)

            self.last_sync_at = time.time()
            if any(changed.values()):
                logger.info("supervisor sync: %s", {k: v for k, v in changed.items() if v})
            return changed

    def _retry_due(self, key: str) -> bool:
        since = self._running[key].adapter.status().get("since") or 0
        return time.time() - float(since) >= RETRY_AFTER_S

    def _start(self, spec: AdapterSpec) -> None:
        try:
            adapter = self._factory(spec)
        except Exception as e:  # noqa: BLE001 — surfaced as adapter status
            self._failed[spec.key] = f"{e.__class__.__name__}: {e}"[:300]
            logger.error("[%s] cannot build adapter: %s", spec.key, self._failed[spec.key])
            return
        self._failed.pop(spec.key, None)
        adapter.set_inbound(self._inbound)
        task = asyncio.create_task(self._guard(adapter), name=f"adapter-{spec.key}")
        self._running[spec.key] = _Running(adapter, task, spec)
        logger.info("[%s] adapter started (source=%s)", spec.key, spec.source)

    async def _guard(self, adapter: BasePlatformAdapter) -> None:
        try:
            await adapter.start()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            adapter._mark_error(f"{e.__class__.__name__}: {e}")
            logger.exception("[%s] adapter crashed", adapter.key)
        else:
            if adapter.status()["state"] not in ("error", "stopped"):
                adapter._mark_disconnected()

    async def _stop(self, key: str) -> None:
        run = self._running.pop(key, None)
        if run is None:
            return
        try:
            await asyncio.wait_for(run.adapter.stop(), timeout=10)
        except Exception:  # noqa: BLE001
            logger.exception("[%s] stop raised", key)
        run.task.cancel()
        try:
            await asyncio.wait_for(run.task, timeout=10)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception:  # noqa: BLE001
            pass
        logger.info("[%s] adapter stopped", key)

    async def stop_all(self) -> None:
        async with self._lock:
            for key in list(self._running):
                await self._stop(key)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[BasePlatformAdapter]:
        run = self._running.get(key)
        return run.adapter if run else None

    def adapters(self) -> list[BasePlatformAdapter]:
        return [run.adapter for run in self._running.values()]

    def for_platform(self, platform: str) -> list[BasePlatformAdapter]:
        return [a for a in self.adapters() if a.name == platform]

    def status(self) -> dict:
        adapters = {key: run.adapter.status() for key, run in self._running.items()}
        for key, err in self._failed.items():
            platform, _, owner = key.partition(":")
            adapters[key] = {
                "platform": platform,
                "owner_user_id": int(owner) if owner.isdigit() else None,
                "state": "error", "error": err, "since": self.last_sync_at, "display": None,
                "source": "settings", "fingerprint": "", "has_test_target": False,
            }
        return {
            "ok": True,
            "uptime_s": round(time.time() - self._started_at, 1),
            "supported": list(SUPPORTED_PLATFORMS),
            "last_sync_at": self.last_sync_at,
            "last_sync_ok": self.last_sync_ok,
            "adapters": adapters,
        }


__all__ = ["AdapterSupervisor", "SUPPORTED_PLATFORMS", "build_adapter"]
