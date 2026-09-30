"""Maps calls need a signed-in user; memory pressure answers even with no GPU visible."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tools import maps


def _maps_app(signed_in: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(maps.router)
    if signed_in:
        app.dependency_overrides[maps._signed_in] = lambda: {"id": 1}
    return app


def test_maps_refuse_a_signed_out_caller():
    res = TestClient(_maps_app(False)).get("/api/tools/maps/places/autocomplete", params={"input": "x"})

    assert res.status_code == 401


def test_maps_say_not_configured_without_a_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    res = TestClient(_maps_app(True)).get("/api/tools/maps/places/autocomplete", params={"input": "x"})

    assert res.status_code == 503


def test_memory_pressure_without_a_gpu_is_a_full_answer(monkeypatch):
    import model_manager

    monkeypatch.setattr(model_manager, "get_gpu_memory_stats", lambda: {"available": False})
    pressure = model_manager.check_memory_pressure()

    assert pressure["pressure_level"] == "unknown"
    assert pressure["auto_cleanup_suggested"] is False
