"""
open-notebook compatibility facade.

Serves the open-notebook (github.com/lfnovo/open-notebook) frontend's HTTP API
contract under the `/onb-api` prefix, translating to Harvis's `notebooks` manager
in-process. Mirrors the `owui_compat` pattern (which does the same for OpenWebUI).

The vendored open-notebook Next.js app (front_end/open-notebook, served at /onb)
rewrites its `/api/*` calls to `/onb-api/*` on the Harvis backend — so this facade
never collides with Harvis's own `/api/*` (OWUI) routes.
"""

from .router import router as onb_router

__all__ = ["onb_router"]
