"""Gateway methods the desktop calls that Harvis answers cleanly instead of with "method not found".

Mixed into ws.Connection. Three kinds:

* real: ``cron.manage`` runs on the same cron_jobs rows as /api/cron (the Bots "routines" pane).
* empty: ``projects.*``, ``pet.*``, ``wake.*``, ``browser.manage`` answer the protocol's empty
  shape, so a poll or a mount finds "nothing here" rather than an error. The controls that would
  create something are hidden by the capability flags on /api/status (``projects``, ``pets``,
  ``wake_word``, ``browser_control``), so the refusals below are a backstop, not a path.
* stale: ``clarify.respond``, ``sudo.respond``, ``secret.respond``, ``mcp.setup.respond`` and
  ``handoff.*`` answer prompts or hand-offs Harvis never raises, so any call is for a card left
  over from an older run. The messages say so in the words the UI already treats as "drop the card".
"""
from __future__ import annotations

from uuid import UUID

from plugins.cron.store import PgCronJobStore

from . import cron
from .cron_schedule import ScheduleError, parse_schedule
from .rpc import ERR_INVALID, ERR_PARAMS, err as _err, ok as _ok

ERR_UNAVAILABLE = 4010  # the feature is not part of this Harvis; the message says what to do instead

_NO_PROJECTS = "Projects are not available in Harvis yet. Chats are listed in the sidebar."
_NO_PETS = "Pets are not available in Harvis."
_NO_HANDOFF = "Handing a chat off to a messaging app is not available. Open the app and message the bot directly."


def _routine_view(job) -> dict:
    row = cron.job_view(job)
    return {**row, "job_id": row["id"], "prompt_preview": row["prompt"], "schedule": row["schedule_display"]}


class ExtraMethods:
    # ---- cron.manage: the Bots routines pane ---------------------------------------------

    async def m_cron_manage(self, rid, params):
        store = PgCronJobStore(self.pool)
        action = str(params.get("action") or "list").lower()
        if action == "list":
            jobs = await store.list_for_user(self.user_id)
            return _ok(rid, {"jobs": [_routine_view(j) for j in jobs]})
        if action == "add":
            return await self._cron_add(rid, store, params)
        job = await self._cron_job(store, str(params.get("name") or params.get("job_id") or ""))
        if job is None:
            return _err(rid, ERR_PARAMS, "That routine does not exist.")
        if action in ("pause", "resume"):
            await cron._apply_update(self.pool, job, {"enabled": action == "resume"})
            return _ok(rid, {"success": True, "action": action})
        if action in ("remove", "delete"):
            return _ok(rid, {"success": bool(await store.delete(job.id)), "action": "remove"})
        return _err(rid, ERR_PARAMS, f"unsupported routine action: {action}")

    async def _cron_job(self, store: PgCronJobStore, job_id: str):
        try:
            job = await store.get(UUID(job_id))
        except (TypeError, ValueError):
            return None
        return job if job is not None and job.user_id == self.user_id else None

    async def _cron_add(self, rid, store: PgCronJobStore, params: dict):
        prompt = str(params.get("prompt") or "").strip()
        if not prompt:
            return _err(rid, ERR_PARAMS, "A routine needs a prompt.")
        try:
            stype, expr, display = parse_schedule(str(params.get("schedule") or ""))
        except ScheduleError as exc:
            return _err(rid, ERR_PARAMS, str(exc))
        name = str(params.get("name") or "").strip() or prompt[:60]
        meta = {"context": "chat", "source": "hermes_ui", "schedule_display": display}
        job = await store.create(user_id=self.user_id, name=name, schedule_type=stype, schedule_expr=expr,
                                 prompt=prompt, delivery=None, metadata=meta)
        if job is None:
            return _err(rid, ERR_PARAMS, "The routine could not be saved.")
        return _ok(rid, {"success": True, "action": "add", "job": _routine_view(job)})

    # ---- projects.*: no project hierarchy yet -----------------------------------------------

    async def m_projects_list(self, rid, params):
        return _ok(rid, {"projects": [], "active_id": None})

    async def m_projects_project_sessions(self, rid, params):
        return _ok(rid, {"project": None})

    async def m_projects_discover_repos(self, rid, params):
        return _ok(rid, {"repos": [], "discovery_policy": None})

    async def m_projects_record_repos(self, rid, params):
        return _ok(rid, {"ok": True})

    async def m_projects_set_active(self, rid, params):
        return _ok(rid, {"active_id": None})

    async def _no_projects(self, rid, params):
        return _err(rid, ERR_UNAVAILABLE, _NO_PROJECTS)

    m_projects_create = m_projects_update = m_projects_delete = m_projects_add_folder = _no_projects

    # ---- pet.*: no mascot -------------------------------------------------------------------

    async def m_pet_info_meta(self, rid, params):
        return _ok(rid, {"enabled": False})

    async def m_pet_gallery(self, rid, params):
        return _ok(rid, {"enabled": False, "active": "", "pets": []})

    async def m_pet_thumb(self, rid, params):
        return _ok(rid, {"ok": False})

    async def m_pet_generate_status(self, rid, params):
        return _ok(rid, {"available": False, "providers": []})

    async def _no_pets(self, rid, params):
        return _err(rid, ERR_UNAVAILABLE, _NO_PETS)

    m_pet_select = m_pet_disable = m_pet_scale = m_pet_export = m_pet_rename = m_pet_remove = _no_pets

    # ---- wake.*: no wake-word engine (wake.status lives in ws.py) ------------------------------

    async def m_wake_start(self, rid, params):
        return _ok(rid, {"started": False, "reason": "unavailable"})

    async def m_wake_stop(self, rid, params):
        return _ok(rid, {"stopped": True, "reason": None})

    async def _wake_ack(self, rid, params):
        return _ok(rid, {"ok": True})

    m_wake_pause = m_wake_resume = m_wake_feed = _wake_ack

    # ---- browser.manage: no remote-debugging browser to attach to -------------------------------

    async def m_browser_manage(self, rid, params):
        return _ok(rid, {"connected": False, "messages": ["Browser attach is not available in Harvis."]})

    # ---- prompts and hand-offs Harvis never raises ------------------------------------------------

    async def m_clarify_respond(self, rid, params):
        return _ok(rid, {"ok": True})  # a leftover card is answered into the void and cleared

    async def m_mcp_setup_respond(self, rid, params):
        return _ok(rid, {"status": "ok"})

    async def m_sudo_respond(self, rid, params):
        return _err(rid, ERR_INVALID, "no pending password request")

    async def m_secret_respond(self, rid, params):
        return _err(rid, ERR_INVALID, "no pending value request")

    async def m_handoff_request(self, rid, params):
        return _err(rid, ERR_UNAVAILABLE, _NO_HANDOFF)

    async def m_handoff_state(self, rid, params):
        return _ok(rid, {"state": "failed", "error": _NO_HANDOFF})

    async def m_handoff_fail(self, rid, params):
        return _ok(rid, {"failed": True, "state": "failed"})
