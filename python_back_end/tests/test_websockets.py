"""
Tests for WebSocket terminal functionality.

Tests the interactive terminal WebSocket handler including:
- Connection establishment and authentication
- JSON message handling (stdin, resize)
- Raw text fallback
- Container lifecycle management
- Error handling and cleanup
"""

import asyncio
import json
import pytest
import pytest_asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
import docker

from vibecoding.websockets import TerminalWebSocketManager, manager, router
from vibecoding.models import get_current_user_websocket


class MockWebSocket:
    """Mock WebSocket for testing."""
    
    def __init__(self):
        self.messages_sent = []
        self.messages_to_receive = []
        self.closed = False
        
    async def accept(self):
        pass
        
    async def send_text(self, message: str):
        self.messages_sent.append(message)
        
    async def receive_text(self) -> str:
        if not self.messages_to_receive:
            raise WebSocketDisconnect(code=1000)
        return self.messages_to_receive.pop(0)
        
    async def close(self):
        self.closed = True
        
    def add_message(self, message: str):
        """Add a message to be received by the WebSocket."""
        self.messages_to_receive.append(message)


class MockDockerContainer:
    """Mock Docker container for testing."""
    
    def __init__(self, container_id="test-container", status="running"):
        self.id = container_id
        self.name = f"vibe-test-{container_id}"
        self.status = status
        
    def remove(self, force=False):
        pass


class MockDockerVolume:
    """Mock Docker volume for testing."""
    
    def __init__(self, name="test-volume"):
        self.name = name


class MockDockerSocket:
    """Mock Docker socket for exec operations."""
    
    def __init__(self):
        self.data_to_send = []
        self.received_data = []
        self._sock = self
        
    def recv(self, size):
        if not self.data_to_send:
            return b""
        return self.data_to_send.pop(0)
        
    def send(self, data):
        self.received_data.append(data)
        
    def close(self):
        pass
        
    def add_output(self, data: bytes):
        """Add data that will be 'received' from the container."""
        self.data_to_send.append(data)


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket for testing."""
    return MockWebSocket()


@pytest.fixture
def mock_docker_client():
    """Create a mock Docker client for testing."""
    client = Mock()
    
    # Mock containers
    client.containers = Mock()
    client.containers.get = Mock()
    client.containers.run = Mock()
    client.containers.list = Mock(return_value=[])
    
    # Mock volumes
    client.volumes = Mock()
    client.volumes.get = Mock()
    client.volumes.create = Mock()
    
    # Mock API
    client.api = Mock()
    client.api.exec_create = Mock()
    client.api.exec_start = Mock()
    client.api.exec_resize = Mock()
    
    # Mock ping
    client.ping = Mock()
    
    return client


@pytest.fixture
def terminal_manager(mock_docker_client):
    """Create a terminal manager with mocked Docker client."""
    manager = TerminalWebSocketManager()
    manager.docker_client = mock_docker_client
    return manager


class TestTerminalWebSocketManager:
    """Test the terminal WebSocket manager."""

    @pytest_asyncio.async_test
    async def test_docker_initialization(self):
        """Test Docker client initialization."""
        with patch('docker.from_env') as mock_docker:
            mock_client = Mock()
            mock_client.ping.return_value = True
            mock_docker.return_value = mock_client
            
            manager = TerminalWebSocketManager()
            assert manager.docker_client is not None
            mock_docker.assert_called_once_with(timeout=30)
            mock_client.ping.assert_called_once()

    @pytest_asyncio.async_test
    async def test_docker_initialization_failure(self):
        """Test Docker client initialization failure."""
        with patch('docker.from_env', side_effect=Exception("Docker not available")):
            manager = TerminalWebSocketManager()
            assert manager.docker_client is None

    @pytest_asyncio.async_test
    async def test_websocket_connect(self, terminal_manager, mock_websocket):
        """Test WebSocket connection establishment."""
        # Mock container creation
        mock_container = MockDockerContainer()
        terminal_manager.docker_client.volumes.get.side_effect = docker.errors.NotFound("Volume not found")
        terminal_manager.docker_client.volumes.create.return_value = MockDockerVolume()
        terminal_manager.docker_client.containers.get.side_effect = docker.errors.NotFound("Container not found") 
        terminal_manager.docker_client.containers.run.return_value = mock_container
        
        # Mock exec operations
        exec_id = "exec-123"
        mock_socket = MockDockerSocket()
        terminal_manager.docker_client.api.exec_create.return_value = {"Id": exec_id}
        terminal_manager.docker_client.api.exec_start.return_value = mock_socket
        
        await terminal_manager.connect(mock_websocket, "test-session", "test-user")
        
        # Verify connection was accepted
        assert len(mock_websocket.messages_sent) > 0
        
        # Verify container was created
        terminal_manager.docker_client.containers.run.assert_called_once()
        
        # Verify exec was created
        terminal_manager.docker_client.api.exec_create.assert_called_once()

    @pytest_asyncio.async_test
    async def test_handle_json_stdin_message(self, terminal_manager, mock_websocket):
        """Test handling JSON stdin message."""
        # Setup session
        connection_key = "test-user:test-session"
        mock_socket = MockDockerSocket()
        terminal_manager.container_sessions[connection_key] = {
            "container_id": "test-container",
            "socket": mock_socket
        }
        
        # Handle stdin message
        stdin_message = json.dumps({
            "type": "stdin",
            "data": "echo hello\n"
        })
        
        await terminal_manager.handle_message(mock_websocket, stdin_message, "test-user", "test-session")
        
        # Verify data was sent to container
        assert len(mock_socket.received_data) == 1
        assert mock_socket.received_data[0] == b"echo hello\n"

    @pytest_asyncio.async_test
    async def test_handle_resize_message(self, terminal_manager, mock_websocket):
        """Test handling terminal resize message."""
        # Setup session
        connection_key = "test-user:test-session"
        exec_id = "exec-123"
        terminal_manager.container_sessions[connection_key] = {
            "container_id": "test-container",
            "exec_id": exec_id
        }
        
        # Handle resize message
        resize_message = json.dumps({
            "type": "resize",
            "cols": 120,
            "rows": 40
        })
        
        await terminal_manager.handle_message(mock_websocket, resize_message, "test-user", "test-session")
        
        # Verify resize was called
        terminal_manager.docker_client.api.exec_resize.assert_called_once_with(
            exec_id, height=40, width=120
        )

    @pytest_asyncio.async_test
    async def test_handle_raw_text_fallback(self, terminal_manager, mock_websocket):
        """Test handling raw text (non-JSON) as stdin fallback."""
        # Setup session
        connection_key = "test-user:test-session"
        mock_socket = MockDockerSocket()
        terminal_manager.container_sessions[connection_key] = {
            "container_id": "test-container",
            "socket": mock_socket
        }
        
        # Handle raw text
        raw_text = "pwd\n"
        
        await terminal_manager.handle_message(mock_websocket, raw_text, "test-user", "test-session")
        
        # Verify data was sent to container
        assert len(mock_socket.received_data) == 1
        assert mock_socket.received_data[0] == b"pwd\n"

    @pytest_asyncio.async_test
    async def test_container_output_reading(self, terminal_manager, mock_websocket):
        """Test reading output from container and sending to WebSocket."""
        # Setup socket with output data
        mock_socket = MockDockerSocket()
        mock_socket.add_output(b"Hello from container\n")
        mock_socket.add_output(b"")  # EOF
        
        # Start output reading
        read_task = asyncio.create_task(
            terminal_manager._read_container_output(mock_websocket, mock_socket, "test-user", "test-session")
        )
        
        # Let it process
        await asyncio.sleep(0.1)
        read_task.cancel()
        
        # Verify output was sent to WebSocket
        assert len(mock_websocket.messages_sent) >= 1
        message = json.loads(mock_websocket.messages_sent[0])
        assert message["type"] == "output"
        assert "Hello from container" in message["data"]

    @pytest_asyncio.async_test
    async def test_container_creation_with_existing_volume(self, terminal_manager, mock_websocket):
        """Test container creation when volume already exists."""
        # Mock existing volume
        existing_volume = MockDockerVolume("vibe-ws-test-user")
        terminal_manager.docker_client.volumes.get.return_value = existing_volume
        
        # Mock container creation
        mock_container = MockDockerContainer()
        terminal_manager.docker_client.containers.get.side_effect = docker.errors.NotFound("Container not found")
        terminal_manager.docker_client.containers.run.return_value = mock_container
        
        # Mock exec operations
        terminal_manager.docker_client.api.exec_create.return_value = {"Id": "exec-123"}
        terminal_manager.docker_client.api.exec_start.return_value = MockDockerSocket()
        
        container_info = await terminal_manager._ensure_container_session("test-user", "test-session")
        
        # Verify existing volume was used
        terminal_manager.docker_client.volumes.get.assert_called_once_with("vibe-ws-test-user")
        terminal_manager.docker_client.volumes.create.assert_not_called()
        
        # Verify container was still created
        assert container_info["container_id"] == mock_container.id

    @pytest_asyncio.async_test
    async def test_error_handling_invalid_message(self, terminal_manager, mock_websocket):
        """Test error handling for invalid messages."""
        # Setup session
        connection_key = "test-user:test-session"
        terminal_manager.container_sessions[connection_key] = {
            "container_id": "test-container"
        }
        
        # Handle invalid JSON
        invalid_json = '{"type": "invalid", "malformed": '
        
        await terminal_manager.handle_message(mock_websocket, invalid_json, "test-user", "test-session")
        
        # Should not crash and should attempt raw text fallback
        # (No specific assertion as fallback behavior depends on session state)

    @pytest_asyncio.async_test
    async def test_disconnect_cleanup(self, terminal_manager):
        """Test cleanup on WebSocket disconnect."""
        # Setup active session
        connection_key = "test-user:test-session"
        terminal_manager.container_sessions[connection_key] = {
            "container_id": "test-container",
            "exec_id": "exec-123"
        }
        
        await terminal_manager.disconnect("test-session", "test-user")
        
        # Session should still exist (containers persist)
        assert connection_key in terminal_manager.container_sessions

    def test_cleanup_user_resources(self, terminal_manager):
        """Test cleanup of user containers and resources."""
        # Mock containers to cleanup
        container1 = MockDockerContainer("container1")
        container2 = MockDockerContainer("container2")
        terminal_manager.docker_client.containers.list.return_value = [container1, container2]
        
        terminal_manager.cleanup_user_resources("test-user")
        
        # Verify containers were listed with correct filters
        terminal_manager.docker_client.containers.list.assert_called_once_with(
            all=True,
            filters={"label": ["app=harvis", "user=test-user"]}
        )


class TestWebSocketAuth:
    """Test WebSocket authentication."""

    @pytest_asyncio.async_test
    async def test_auth_with_valid_token(self):
        """Test WebSocket authentication with valid JWT token."""
        mock_websocket = Mock()
        
        # Mock JWT decode
        with patch('jose.jwt.decode') as mock_decode:
            mock_decode.return_value = {"sub": "user123"}
            
            user = await get_current_user_websocket(mock_websocket, "valid-token")
            
            assert user["user_id"] == "user123"
            assert user["id"] == "user123"

    @pytest_asyncio.async_test
    async def test_auth_with_invalid_token(self):
        """Test WebSocket authentication with invalid JWT token."""
        mock_websocket = Mock()
        
        # Mock JWT decode failure
        with patch('jose.jwt.decode', side_effect=Exception("Invalid token")):
            user = await get_current_user_websocket(mock_websocket, "invalid-token")
            
            # Should fall back to dev user
            assert user["user_id"] == "dev"

    @pytest_asyncio.async_test
    async def test_auth_without_token(self):
        """Test WebSocket authentication without token."""
        mock_websocket = Mock()
        
        user = await get_current_user_websocket(mock_websocket, None)
        
        # Should fall back to dev user
        assert user["user_id"] == "dev"
        assert user["username"] == "developer"


class TestWebSocketHealth:
    """Test WebSocket health endpoint."""

    @pytest_asyncio.async_test
    async def test_health_check_healthy(self, terminal_manager):
        """Test health check when Docker is available."""
        # Mock successful ping
        terminal_manager.docker_client.ping.return_value = True
        
        # Import the health function (would normally be done via FastAPI app)
        from vibecoding.websockets import router
        
        # The health endpoint should return healthy status
        # Note: This would normally be tested via TestClient with FastAPI app

    @pytest_asyncio.async_test  
    async def test_health_check_unhealthy(self):
        """Test health check when Docker is unavailable."""
        # Test would verify health endpoint returns unhealthy when Docker fails
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])