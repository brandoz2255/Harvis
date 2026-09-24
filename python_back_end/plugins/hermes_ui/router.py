"""Assembles the Hermes UI facade: REST stubs + the JSON-RPC WebSocket."""
from fastapi import APIRouter

from .audio import router as audio_router
from .bots import router as bots_router
from .cron import router as cron_router
from .messaging import router as messaging_router
from .profiles import router as profiles_router
from .rest import router as rest_router
from .rest_capabilities import router as capabilities_router
from .rest_harvis import router as harvis_router
from .rest_providers import router as providers_router
from .rest_settings import router as settings_router
from .ws import router as ws_router

router = APIRouter()
# Settings/messaging routes go first: rest.py ends with a catch-all.
router.include_router(settings_router)
router.include_router(profiles_router)
router.include_router(messaging_router)
router.include_router(cron_router)
router.include_router(audio_router)
router.include_router(capabilities_router)
router.include_router(harvis_router)
router.include_router(providers_router)
router.include_router(bots_router)
router.include_router(rest_router)
router.include_router(ws_router)
