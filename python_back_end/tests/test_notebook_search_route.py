"""Notebook search takes its request from the body, and the API schema builds."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from notebooks import router as nb


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(nb.router)
    app.dependency_overrides[nb.get_current_user_from_request] = lambda: {"id": 1}
    app.dependency_overrides[nb.get_notebook_manager] = lambda: object()
    return app


def test_an_empty_search_is_read_from_the_body():
    res = TestClient(_app()).post("/api/notebooks/search", json={"query": "  ", "type": "text"})

    assert res.status_code == 200
    assert res.json()["results"] == []


def test_the_notebook_routes_have_a_schema():
    schema = _app().openapi()

    assert "/api/notebooks/search" in schema["paths"]
