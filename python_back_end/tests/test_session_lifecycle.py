"""
Test suite for session lifecycle management

Tests for session status checking, starting, stopping, and state transitions
with Docker integration mocking.
"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from fastapi import WebSocket

from vibecoding.session_lifecycle import SessionManager, SessionState, SessionInfo
from routes.vibe_sessions import router

# Mock Docker classes
class MockContainer:
    def __init__(self, id="mock-container-id", status="running"):
        self.id = id
        self.status = status
        self.attrs = {"Created": datetime.now().isoformat()}
        
    def reload(self):
        pass
    
    def start(self):
        self.status = "running"
        
    def stop(self, timeout=10):
        self.status = "exited"
        
    def remove(self, force=False):
        pass

class MockVolume:
    def __init__(self, name="mock-volume"):
        self.name = name

class MockDockerClient:
    def __init__(self):
        self.containers = Mock()
        self.volumes = Mock()
        
    def create_mock_container(self, status="running"):
        return MockContainer(status=status)
        
    def create_mock_volume(self):
        return MockVolume()

@pytest.fixture
def mock_docker_client():
    """Mock Docker client for testing"""
    return MockDockerClient()

@pytest.fixture
def session_manager(mock_docker_client):
    """Session manager with mocked Docker client"""
    manager = SessionManager()
    manager.docker_client = mock_docker_client
    return manager

@pytest.fixture
def test_session_id():
    """Test session ID"""
    return "test-session-123"

class TestSessionManager:
    """Test SessionManager core functionality"""
    
    @pytest.mark.asyncio
    async def test_get_session_status_new_session(self, session_manager, test_session_id, mock_docker_client):
        """Test getting status for a new session discovers Docker state"""
        # Mock no existing container or volume
        mock_docker_client.containers.get = Mock(side_effect=Exception("NotFound"))
        mock_docker_client.volumes.get = Mock(side_effect=Exception("NotFound"))
        
        status = await session_manager.get_session_status(test_session_id)
        
        assert status.session_id == test_session_id
        assert status.state == SessionState.STOPPED
        assert not status.container_exists
        assert not status.volume_exists
        assert status.last_ready_at is None
    
    @pytest.mark.asyncio
    async def test_get_session_status_existing_running_container(self, session_manager, test_session_id, mock_docker_client):
        """Test discovery of existing running container"""
        # Mock existing running container and volume
        mock_container = MockContainer(status="running")
        mock_volume = MockVolume()
        
        mock_docker_client.containers.get = Mock(return_value=mock_container)
        mock_docker_client.volumes.get = Mock(return_value=mock_volume)
        
        status = await session_manager.get_session_status(test_session_id)
        
        assert status.state == SessionState.RUNNING
        assert status.container_exists
        assert status.volume_exists
        assert status.last_ready_at is not None
        assert status.container_id == mock_container.id
    
    @pytest.mark.asyncio
    async def test_start_session_idempotent_already_running(self, session_manager, test_session_id):
        """Test that starting an already running session is idempotent"""
        # Pre-populate with running session
        session_manager._sessions[test_session_id] = SessionInfo(
            session_id=test_session_id,
            state=SessionState.RUNNING,
            container_exists=True,
            volume_exists=True,
            last_ready_at=datetime.now()
        )
        
        result = await session_manager.start_session(test_session_id)
        
        assert result["status"] == "already_running"
        assert result["job_id"] is None
    
    @pytest.mark.asyncio
    async def test_start_session_already_starting(self, session_manager, test_session_id):
        """Test that starting a session already starting returns job info"""
        # Pre-populate with starting session
        session_manager._sessions[test_session_id] = SessionInfo(
            session_id=test_session_id,
            state=SessionState.STARTING,
            container_exists=False,
            volume_exists=False
        )
        
        result = await session_manager.start_session(test_session_id)
        
        assert result["status"] == "already_starting"
        assert "start_" in result["job_id"]
    
    @pytest.mark.asyncio
    async def test_start_session_creates_new_container(self, session_manager, test_session_id, mock_docker_client):
        """Test starting a session creates new container"""
        # Mock container creation
        mock_container = MockContainer(status="running")
        mock_volume = MockVolume()
        
        mock_docker_client.containers.get = Mock(side_effect=Exception("NotFound"))
        mock_docker_client.containers.run = Mock(return_value=mock_container)
        mock_docker_client.volumes.create = Mock(return_value=mock_volume)
        
        result = await session_manager.start_session(test_session_id, "test-user")
        
        assert result["status"] == "starting"
        assert result["job_id"] is not None
        assert "start_" in result["job_id"]
        
        # Wait a bit for background task to complete
        await asyncio.sleep(0.1)
        
        # Check session was updated
        session = session_manager._sessions[test_session_id]
        assert session.state == SessionState.RUNNING
        assert session.container_id == mock_container.id
    
    @pytest.mark.asyncio
    async def test_start_session_reuses_existing_container(self, session_manager, test_session_id, mock_docker_client):
        """Test starting reuses existing stopped container"""
        # Mock existing stopped container
        mock_container = MockContainer(status="exited")
        mock_volume = MockVolume()
        
        mock_docker_client.containers.get = Mock(return_value=mock_container)
        mock_docker_client.volumes.get = Mock(return_value=mock_volume)
        
        result = await session_manager.start_session(test_session_id)
        
        assert result["status"] == "starting"
        
        # Wait for background task
        await asyncio.sleep(0.1)
        
        # Verify container was started
        assert mock_container.status == "running"
        session = session_manager._sessions[test_session_id]
        assert session.state == SessionState.RUNNING
    
    @pytest.mark.asyncio
    async def test_stop_session_idempotent(self, session_manager, test_session_id, mock_docker_client):
        """Test stopping session is idempotent"""
        # Pre-populate with running session
        mock_container = MockContainer(status="running")
        session_manager._sessions[test_session_id] = SessionInfo(
            session_id=test_session_id,
            state=SessionState.RUNNING,
            container_exists=True,
            volume_exists=True,
            container_id=mock_container.id
        )
        
        mock_docker_client.containers.get = Mock(return_value=mock_container)
        
        result = await session_manager.stop_session(test_session_id)
        
        assert result["status"] == "stopped"
        
        # Stop again - should be idempotent
        result = await session_manager.stop_session(test_session_id)
        assert result["status"] == "already_stopped"
    
    @pytest.mark.asyncio
    async def test_stop_session_already_stopped(self, session_manager, test_session_id):
        """Test stopping already stopped session"""
        session_manager._sessions[test_session_id] = SessionInfo(
            session_id=test_session_id,
            state=SessionState.STOPPED,
            container_exists=False,
            volume_exists=True
        )
        
        result = await session_manager.stop_session(test_session_id)
        assert result["status"] == "already_stopped"
    
    @pytest.mark.asyncio
    async def test_is_session_ready(self, session_manager, test_session_id):
        """Test session readiness check"""
        # No session - not ready
        assert not session_manager.is_session_ready(test_session_id)
        
        # Stopped session - not ready
        session_manager._sessions[test_session_id] = SessionInfo(
            session_id=test_session_id,
            state=SessionState.STOPPED,
            container_exists=False,
            volume_exists=True
        )
        assert not session_manager.is_session_ready(test_session_id)
        
        # Running session - ready
        session_manager._sessions[test_session_id].state = SessionState.RUNNING
        assert session_manager.is_session_ready(test_session_id)
    
    @pytest.mark.asyncio
    async def test_websocket_registration(self, session_manager, test_session_id):
        """Test WebSocket registration and notification"""
        mock_websocket = Mock()
        mock_websocket.send_json = AsyncMock()
        
        # Register WebSocket
        await session_manager.register_websocket(test_session_id, mock_websocket)
        
        # Send notification
        await session_manager._notify_websocket_clients(test_session_id, {"type": "test"})
        
        mock_websocket.send_json.assert_called_once_with({"type": "test"})
        
        # Unregister
        await session_manager.unregister_websocket(test_session_id, mock_websocket)
        
        # Should not receive notifications after unregistering
        mock_websocket.send_json.reset_mock()
        await session_manager._notify_websocket_clients(test_session_id, {"type": "test2"})
        mock_websocket.send_json.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_cleanup_inactive_sessions(self, session_manager, mock_docker_client):
        """Test cleanup of inactive sessions"""
        old_time = datetime.now() - timedelta(hours=3)
        recent_time = datetime.now() - timedelta(minutes=30)
        
        # Create inactive session
        inactive_session = SessionInfo(
            session_id="inactive-session",
            state=SessionState.RUNNING,
            container_exists=True,
            volume_exists=True,
            container_id="inactive-container",
            last_ready_at=old_time
        )
        
        # Create active session
        active_session = SessionInfo(
            session_id="active-session", 
            state=SessionState.RUNNING,
            container_exists=True,
            volume_exists=True,
            container_id="active-container",
            last_ready_at=recent_time
        )
        
        session_manager._sessions["inactive-session"] = inactive_session
        session_manager._sessions["active-session"] = active_session
        
        # Mock containers
        mock_inactive_container = MockContainer(id="inactive-container", status="running")
        mock_active_container = MockContainer(id="active-container", status="running")
        
        def mock_get_container(container_id):
            if container_id == "inactive-container":
                return mock_inactive_container
            return mock_active_container
        
        mock_docker_client.containers.get = mock_get_container
        
        cleaned = await session_manager.cleanup_inactive_sessions(max_inactive_hours=2)
        
        assert cleaned == 1
        assert session_manager._sessions["inactive-session"].state == SessionState.STOPPED
        assert session_manager._sessions["active-session"].state == SessionState.RUNNING

class TestSessionAPI:
    """Test session lifecycle API endpoints"""
    
    @pytest.fixture
    def client(self):
        """FastAPI test client"""
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)
    
    @pytest.fixture
    def auth_headers(self):
        """Mock authentication headers"""
        return {"Authorization": "Bearer test-token"}
    
    def test_get_session_status_endpoint(self, client, auth_headers):
        """Test GET /api/vibe-sessions/{id}/status endpoint"""
        with patch('routes.vibe_sessions.get_current_user') as mock_auth, \
             patch('routes.vibe_sessions.session_manager') as mock_manager:
            
            mock_auth.return_value = {"id": "test-user"}
            mock_session = SessionInfo(
                session_id="test-session",
                state=SessionState.RUNNING,
                container_exists=True,
                volume_exists=True,
                last_ready_at=datetime.now()
            )
            mock_manager.get_session_status = AsyncMock(return_value=mock_session)
            
            response = client.get("/api/vibe-sessions/test-session/status", headers=auth_headers)
            
            assert response.status_code == 200
            data = response.json()
            assert data["state"] == "running"
            assert data["container_exists"] is True
            assert data["session_id"] == "test-session"
    
    def test_start_session_endpoint(self, client, auth_headers):
        """Test POST /api/vibe-sessions/{id}/start endpoint"""
        with patch('routes.vibe_sessions.get_current_user') as mock_auth, \
             patch('routes.vibe_sessions.session_manager') as mock_manager:
            
            mock_auth.return_value = {"id": "test-user"}
            mock_manager.start_session = AsyncMock(return_value={
                "status": "starting",
                "job_id": "start_test-session_abc123"
            })
            
            response = client.post("/api/vibe-sessions/test-session/start", headers=auth_headers)
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "starting"
            assert data["job_id"] == "start_test-session_abc123"
    
    def test_stop_session_endpoint(self, client, auth_headers):
        """Test POST /api/vibe-sessions/{id}/stop endpoint"""
        with patch('routes.vibe_sessions.get_current_user') as mock_auth, \
             patch('routes.vibe_sessions.session_manager') as mock_manager:
            
            mock_auth.return_value = {"id": "test-user"}
            mock_manager.stop_session = AsyncMock(return_value={
                "status": "stopped"
            })
            
            response = client.post("/api/vibe-sessions/test-session/stop", headers=auth_headers)
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "stopped"

class TestFileTreePreflight:
    """Test file tree route preflight checks"""
    
    @pytest.mark.asyncio
    async def test_file_tree_blocks_when_session_not_ready(self):
        """Test file tree returns 409 when session not ready"""
        from vibecoding.files import get_session_files_tree
        from fastapi import HTTPException
        
        with patch('vibecoding.files.session_manager') as mock_manager:
            mock_manager.is_session_ready.return_value = False
            
            with pytest.raises(HTTPException) as exc_info:
                await get_session_files_tree(sessionId="test-session", user={"id": "test-user"})
            
            assert exc_info.value.status_code == 409
            assert "Session not ready" in str(exc_info.value.detail)
    
    @pytest.mark.asyncio
    async def test_container_file_tree_blocks_when_session_not_ready(self):
        """Test container file tree returns 409 when session not ready"""
        from vibecoding.containers import get_file_tree, ListFilesRequest
        from fastapi import HTTPException
        
        with patch('vibecoding.containers.session_manager') as mock_manager:
            mock_manager.is_session_ready.return_value = False
            
            request = ListFilesRequest(session_id="test-session", path="/workspace")
            
            with pytest.raises(HTTPException) as exc_info:
                await get_file_tree(request)
            
            assert exc_info.value.status_code == 409
            assert "Session not ready" in str(exc_info.value.detail)

class TestFileSystemWatcher:
    """Test FS watcher WebSocket with session guards"""
    
    @pytest.mark.asyncio
    async def test_fs_watcher_rejects_non_running_session(self):
        """Test FS watcher closes connection if session not running"""
        mock_websocket = Mock()
        mock_websocket.accept = AsyncMock()
        mock_websocket.send_json = AsyncMock()
        mock_websocket.close = AsyncMock()
        
        with patch('vibecoding.websockets.session_manager') as mock_manager, \
             patch('vibecoding.websockets.get_current_user_websocket') as mock_auth:
            
            mock_auth.return_value = {"id": "test-user"}
            mock_manager.is_session_ready.return_value = False
            
            from vibecoding.websockets import websocket_fs_watcher
            
            await websocket_fs_watcher(mock_websocket, "test-session", {"id": "test-user"})
            
            mock_websocket.accept.assert_called_once()
            mock_websocket.send_json.assert_called_once()
            mock_websocket.close.assert_called_once_with(code=4100, reason="Session not running")
            
            # Check the error message sent
            error_call = mock_websocket.send_json.call_args[0][0]
            assert error_call["type"] == "error"
            assert "Session not ready" in error_call["message"]

if __name__ == "__main__":
    pytest.main([__file__, "-v"])