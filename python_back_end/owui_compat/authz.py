"""Server-side authorization for admin-only routes.

Why this exists
---------------
Until now the *only* thing standing between a normal signed-in user and the
admin surfaces was a client-side route guard in the SvelteKit frontend
(``routes/(app)/admin/+layout.svelte`` and the ``/workspace`` equivalent). That
guard decides what the browser renders — it cannot stop anyone from calling the
API directly with a valid token.

That was survivable only by accident: most admin routes are not implemented in
the facade, so they 404 for everybody, and a 404 is passable access control. The
moment anyone implements an admin route without a real check, it ships to every
signed-in user. ``POST /api/v1/audio/config/update`` was already exactly that —
reachable by any authenticated user, harmless only because it is a no-op echo.

So: this is the server-side line of defence. New admin-shaped routes should take
``Depends(require_admin)`` and nothing else.

Admin identity
--------------
Harvis has no ``role`` column. Admin is derived the same way the OWUI facade
already derives it for the UI (``translate.py``): the first registrant (id 1) is
admin, overridable via ``HARVIS_OWUI_ADMIN_USER_IDS``. Deriving it from the same
single source keeps the API and the UI from disagreeing about who is an admin —
a split-brain there would be its own bug.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, HTTPException

from .translate import _admin_user_ids


def user_id_of(user: Any) -> int | None:
    """Pull the numeric id off whichever user shape a caller has.

    The codebase carries users as a Pydantic ``UserResponse`` in ``main.py`` and
    as a plain dict in the compat layer, so accept both rather than forcing one.
    """
    if user is None:
        return None
    raw = None
    if isinstance(user, dict):
        raw = user.get("id")
    else:
        raw = getattr(user, "id", None)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def is_admin(user: Any) -> bool:
    """True when this user is an administrator. Fail-closed on an unknown id."""
    uid = user_id_of(user)
    if uid is None:
        return False
    return uid in _admin_user_ids()


def make_require_admin(get_current_user: Callable) -> Callable:
    """Build an admin-only dependency on top of an existing auth dependency.

    Taken as a factory because the compat routers are handed ``get_current_user``
    as a parameter (see ``register_*_routes``) — importing it directly here would
    create a circular import with ``main``.

    Ordering note: authentication runs first via the injected dependency, so an
    anonymous caller gets 401 from that, and only an authenticated non-admin
    reaches the 403 below. That distinction is deliberate — 403 tells an honest
    client "you are known but not permitted", which is the truthful answer.
    """

    async def require_admin(user=Depends(get_current_user)):
        if not is_admin(user):
            raise HTTPException(
                status_code=403,
                detail="Administrator privileges are required for this operation.",
            )
        return user

    return require_admin
