import asyncio
import importlib
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

wr = importlib.import_module("workspace.workspace_router")


@pytest.mark.parametrize("lane", ["agent-native", "orchestrated", "main"])
def test_disabled_gateway_native_launch_routes(lane, monkeypatch):
    monkeypatch.setenv("HARVIS_OPENCLAW_DISABLED", "true")
    monkeypatch.setattr(wr, "_db_enable_interactive", AsyncMock(return_value="token"))
    monkeypatch.setattr(wr, "_db_create_run", AsyncMock())
    monkeypatch.setattr(wr, "_run_workspace_bg", AsyncMock())
    monkeypatch.setattr(wr, "resolve_openclaw_config", AsyncMock(side_effect=AssertionError("gateway resolver called")))
    from plugins.people import controls
    monkeypatch.setattr(controls, "require_turn", AsyncMock(return_value="model"))
    app = FastAPI()
    app.include_router(wr.workspace_router)
    app.dependency_overrides[wr.get_current_user_optimized] = lambda: {"id": 1}

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/workspace/launch", json={"task_brief": "test", "chat_history": [], "agent_id": lane})
        assert response.status_code == 200, response.text
        workspace_id = response.json()["workspace_id"]
        await wr._workspace_tasks[workspace_id]
        assert wr._workspaces[workspace_id]["agent_id"] == lane
        wr.resolve_openclaw_config.assert_not_awaited()
        wr._workspace_tasks.pop(workspace_id, None)
        wr._workspace_broadcasters.pop(workspace_id, None)
        wr._workspaces.pop(workspace_id, None)
    asyncio.run(run())


def test_disabled_gateway_status_is_optional_not_an_error(monkeypatch):
    # The kill switch is about the retired bundled gateway. The status card is the user's own
    # OpenClaw link now, so with nothing linked it reads "available / optional", not a fault.
    monkeypatch.setenv("HARVIS_OPENCLAW_DISABLED", "true")
    from owui_compat.integrations_status import probe_services
    from types import SimpleNamespace
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    services, _ = asyncio.run(probe_services(request, {"id": 1}))
    assert services["openclaw"]["status"] == "available"
    assert services["openclaw"]["reason"] == "not_linked"
    assert "Optional" in services["openclaw"]["detail"]


def test_cancel_without_gateway_client_is_clean(monkeypatch):
    workspace_id = "ws-cancel-no-client"
    wr._workspaces[workspace_id] = {"status": "running", "client": None}
    try:
        result = asyncio.run(wr.cancel_workspace_internal(workspace_id))
    finally:
        wr._workspaces.pop(workspace_id, None)
        wr._workspace_tasks.pop(workspace_id, None)
    assert result["status"] == "cancelled"
    assert result["client_cancel_err"] is None
