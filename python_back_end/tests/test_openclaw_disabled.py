import asyncio
from unittest.mock import AsyncMock

import pytest

# Import these modules without importing workspace's unrelated application router.
import importlib.util
import sys
import types
from pathlib import Path

_saved = {key: value for key, value in sys.modules.items() if key == "workspace" or key.startswith("workspace.")}
package = types.ModuleType("workspace")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "workspace")]
sys.modules["workspace"] = package


def load_module(name):
    path = Path(package.__path__[0]) / f"{name}.py"
    fullname = f"workspace.{name}"
    spec = importlib.util.spec_from_file_location(fullname, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


openclaw_client = load_module("openclaw_client")
openclaw_resolver = load_module("openclaw_resolver")
for key in list(sys.modules):
    if key == "workspace" or key.startswith("workspace."):
        del sys.modules[key]
sys.modules.update(_saved)


def test_disabled_gateway_blocks_client_and_fallback(monkeypatch):
    monkeypatch.setenv("HARVIS_OPENCLAW_DISABLED", "true")
    connect = AsyncMock()
    monkeypatch.setattr(openclaw_client.websockets, "connect", connect)
    monkeypatch.setattr(openclaw_client, "OPENCLAW_FALLBACK_URL", "ws://fallback:18789")
    client = openclaw_client.OpenClawClient("test", gateway_url="ws://explicit:18789")
    with pytest.raises(RuntimeError, match="OpenClaw gateway is disabled"):
        asyncio.run(client._connect())
    connect.assert_not_called()


def test_disabled_gateway_rejects_resolver_before_database(monkeypatch):
    monkeypatch.setenv("HARVIS_OPENCLAW_DISABLED", "true")
    with pytest.raises(RuntimeError, match="OpenClaw gateway is disabled"):
        asyncio.run(openclaw_resolver.resolve_openclaw_config(None, 1))
