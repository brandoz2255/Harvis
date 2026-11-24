import asyncio
import importlib
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

wr = importlib.import_module("workspace.workspace_router")


@pytest.mark.parametrize("lane", ["agent-native", "orchestrated", "main"])
def test_native_launch_routes(lane, monkeypatch):
    monkeypatch.setattr(wr, "_db_enable_interactive", AsyncMock(return_value="token"))
    monkeypatch.setattr(wr, "_db_create_run", AsyncMock())
    monkeypatch.setattr(wr, "_run_workspace_bg", AsyncMock())
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
        wr._workspace_tasks.pop(workspace_id, None)
        wr._workspace_broadcasters.pop(workspace_id, None)
        wr._workspaces.pop(workspace_id, None)
    asyncio.run(run())


def test_cancel_without_a_running_task_is_clean(monkeypatch):
    workspace_id = "ws-cancel-no-client"
    wr._workspaces[workspace_id] = {"status": "running", "client": None}
    try:
        result = asyncio.run(wr.cancel_workspace_internal(workspace_id))
    finally:
        wr._workspaces.pop(workspace_id, None)
        wr._workspace_tasks.pop(workspace_id, None)
    assert result["status"] == "cancelled"
    assert result["wait_outcome"] == "no-task"
