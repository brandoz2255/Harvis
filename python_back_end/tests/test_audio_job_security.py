"""Security boundaries for legacy background audio job endpoints."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
import job_queue


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(main.app.dependency_overrides, main.get_current_user,
                        lambda: SimpleNamespace(id=1))
    return TestClient(main.app)


def test_job_status_requires_owner(client, monkeypatch):
    class Queue:
        async def get_job_status(self, job_id):
            return {"id": job_id, "data": {"user_id": 2, "text": "private"}}
    async def queue():
        return Queue()
    monkeypatch.setattr(job_queue, "get_job_queue", queue)
    response = client.get('/api/jobs/example')
    assert response.status_code == 404
    assert 'private' not in response.text


def test_whisper_rejects_server_path(client, monkeypatch):
    called = []
    async def enqueue(**kwargs):
        called.append(kwargs)
        return 'job'
    monkeypatch.setattr(job_queue, 'enqueue_whisper_job', enqueue)
    response = client.post('/api/jobs/whisper', json={'audio_path': '/etc/passwd'})
    assert response.status_code in (403, 404, 410)
    assert not called
