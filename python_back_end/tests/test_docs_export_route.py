"""The export route answers with the file, or a 400 with a reason."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from plugins.hermes_ui import docs_export  # noqa: E402
from test_docs_export import DECK, DOC  # noqa: E402


@pytest.fixture()
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth_optimized import get_current_user_optimized
    from plugins.hermes_ui.rest_docs import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_optimized] = lambda: {"id": 1}
    return TestClient(app)


def test_the_route_returns_the_file_with_type_and_attachment_name(client):
    r = client.post("/hermes-api/api/harvis/docs/export", json={"source": DECK, "format": "pptx"})
    assert r.status_code == 200
    assert r.headers["content-type"] == docs_export.MEDIA_TYPES["pptx"]
    assert r.headers["content-disposition"] == (
        "attachment; filename=\"q3-security-review.pptx\"; filename*=UTF-8''q3-security-review.pptx")
    assert r.content[:2] == b"PK"
    r = client.post("/hermes-api/api/harvis/docs/export", json={"source": DOC, "format": "pdf", "title": "Memo"})
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert 'filename="memo.pdf"' in r.headers["content-disposition"]


@pytest.mark.parametrize("body", [
    {"source": DECK, "format": "exe"}, {"source": "", "format": "pdf"}, {"format": "pdf"}, {"source": DECK},
    {"source": DECK, "format": "csv"}, {"source": "x" * (docs_export.MAX_SOURCE_BYTES + 1), "format": "pdf"},
    {"source": 5, "format": "pdf"}, ["not", "an", "object"],
])
def test_the_route_answers_400_with_a_detail(client, body):
    r = client.post("/hermes-api/api/harvis/docs/export", json=body)
    assert r.status_code == 400 and r.json()["detail"]


def test_the_route_rejects_a_body_that_is_not_json(client):
    r = client.post("/hermes-api/api/harvis/docs/export", content=b"nope", headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["detail"]


def test_the_route_needs_a_signed_in_user():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from plugins.hermes_ui.rest_docs import router

    app = FastAPI()
    app.include_router(router)
    r = TestClient(app).post("/hermes-api/api/harvis/docs/export", json={"source": DECK, "format": "pptx"})
    assert r.status_code in (401, 403, 500) and r.status_code != 200
