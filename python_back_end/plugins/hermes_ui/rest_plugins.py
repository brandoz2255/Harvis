"""The desktop plugin backend door: ``/api/plugins/<id>/...``.

The desktop's ``pluginRest`` scopes every plugin's REST calls to this namespace.
Before this file the facade's catch-all answered all of them with a generic 404,
so a plugin could not tell "this plugin has no backend in Harvis" from a typo.
Backends Harvis does have are registered in BACKENDS and mounted by their own
routers (mods: plugins/mods/routes.py); everything else gets a plain answer.
"""
from fastapi import APIRouter, Depends, HTTPException

from auth_optimized import get_current_user_optimized
from plugins.mods import router as mods_router

router = APIRouter(prefix="/hermes-api/api", tags=["hermes-ui"])

BACKENDS = {"mods": mods_router}


@router.get("/plugins")
async def plugin_backends(user=Depends(get_current_user_optimized)):
    return {"backends": sorted(BACKENDS)}


@router.api_route("/plugins/{plugin_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@router.api_route("/plugins/{plugin_id}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def no_backend(plugin_id: str, path: str = "", user=Depends(get_current_user_optimized)):
    raise HTTPException(404, {"error": "plugin_backend_missing", "plugin": plugin_id,
                              "message": f"The {plugin_id!r} plugin has no backend in Harvis."})
