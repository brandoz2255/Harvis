"""Vibecoding Terminal WebSocket Handler

This module provides WebSocket-based terminal access to VibeCode containers,
enabling interactive shell sessions with bidirectional byte streaming.
"""

import asyncio
import logging
import os
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from jose import jwt, JWTError

from .containers import container_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vibecode-terminal"])

# JWT configuration (must match main.py)
SECRET_KEY = os.getenv("JWT_SECRET", "key")
ALGORITHM = "HS256"


async def authenticate_websocket(token: str = None, cookies: dict = None) -> dict:
    """Authenticate WebSocket connection using JWT token or cookie
    
    Args:
        token: JWT token from query parameter (optional)
        cookies: Cookie dict from request (optional)
        
    Returns:
        User dict with id, username, email
        
    Raises:
        HTTPException: If authentication fails
    """
    # Try token first, then cookie
    auth_token = token
    if not auth_token and cookies:
        auth_token = cookies.get("token")
    
    if not auth_token:
        raise HTTPException(status_code=401, detail="No authentication provided")
    
    try:
        payload = jwt.decode(auth_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str = payload.get("sub")
        
        if user_id_str is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Return minimal user info needed for authorization
        return {
            "id": int(user_id_str),
            "username": payload.get("username", ""),
            "email": payload.get("email", "")
        }
    except JWTError as e:
        logger.error(f"JWT decode error: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")
    except ValueError as e:
        logger.error(f"User ID conversion error: {e}")
        raise HTTPException(status_code=401, detail="Invalid token format")


@router.websocket("/ws/vibecoding/terminal")
async def terminal_websocket(
    websocket: WebSocket,
    session_id: str = Query(...),
    token: str = Query(None)
):
    """WebSocket endpoint for interactive terminal access to containers
    
    Provides a PTY-based terminal session with:
    - Bidirectional byte streaming (client ↔ container)
    - Full terminal features (colors, cursor movement, line editing)
    - Graceful disconnect handling
    - JWT authentication
    
    Query Parameters:
        session_id: VibeCode session identifier
        token: JWT authentication token
    """
    await websocket.accept()
    logger.info(f"🔌 Terminal WebSocket connection accepted for session: {session_id}")

    # Marathon P2: the Build Shell tab is gated by HARVIS_BUILD_SHELL (default OFF).
    # Enforced HERE (not just by hiding the tab) so the WS can't be driven directly
    # while the feature is disabled. Mirrors owui_compat/config.py's
    # enable_harvis_build_shell flag.
    if os.getenv("HARVIS_BUILD_SHELL", "").strip().lower() not in ("1", "true", "yes", "on"):
        await websocket.send_json(
            {"error": "Shell access is disabled (HARVIS_BUILD_SHELL is off, pending review)"}
        )
        await websocket.close(code=1008)
        return

    exec_instance = None
    
    try:
        # Authenticate user (try token first, then cookies)
        try:
            # Get cookies from the WebSocket request
            cookies = {}
            if hasattr(websocket, 'cookies'):
                cookies = websocket.cookies
            
            user = await authenticate_websocket(token=token, cookies=cookies)
            logger.info(f"✅ User authenticated: {user['id']}")
        except HTTPException as e:
            await websocket.send_json({"error": e.detail})
            await websocket.close(code=1008)  # Policy violation
            return
        
        # Get runner container for session (preferred), fallback to IDE container
        container = await container_manager.get_runner_container(session_id)
        if not container:
            container = await container_manager.get_container(session_id)
        if not container:
            logger.error(f"❌ Container not found for session: {session_id}")
            await websocket.send_json({"error": "Container not found"})
            await websocket.close(code=1008)
            return
        
        # Verify user owns this session
        user_id_label = container.labels.get("user_id")
        if user_id_label and str(user["id"]) != user_id_label:
            logger.error(f"❌ Unauthorized access attempt by user {user['id']} to session {session_id}")
            await websocket.send_json({"error": "Unauthorized"})
            await websocket.close(code=1008)
            return
        
        # Ensure container is running
        container.reload()
        if container.status != "running":
            logger.error(f"❌ Container not running: {container.status}")
            await websocket.send_json({"error": f"Container not running: {container.status}"})
            await websocket.close(code=1011)  # Internal error
            return
        
        logger.info(f"🐚 Creating PTY in container: {container.name}")
        
        # Create PTY exec instance
        exec_instance = container.client.api.exec_create(
            container.id,
            cmd="/bin/bash -l",
            stdin=True,
            tty=True,
            environment={
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                "HOME": "/workspace",
                "USER": "root"
            },
            workdir="/workspace"
        )
        
        # Start exec and get socket
        exec_socket = container.client.api.exec_start(
            exec_instance['Id'],
            socket=True,
            tty=True
        )
        
        logger.info(f"✅ PTY created successfully for session: {session_id}")
        
        # Set socket to non-blocking mode
        exec_socket._sock.setblocking(False)
        
        # Task for reading from container and sending to WebSocket
        async def read_from_container():
            """Read output from container PTY and send to WebSocket"""
            try:
                while True:
                    try:
                        # Read data from container socket
                        data = await asyncio.get_event_loop().run_in_executor(
                            None, 
                            exec_socket._sock.recv, 
                            4096
                        )
                        
                        if not data:
                            logger.info("📭 Container PTY closed (no data)")
                            break
                        
                        # Send raw bytes to WebSocket
                        await websocket.send_bytes(data)
                        
                    except BlockingIOError:
                        # No data available, wait a bit
                        await asyncio.sleep(0.01)
                    except Exception as e:
                        logger.error(f"❌ Error reading from container: {e}")
                        break
                        
            except asyncio.CancelledError:
                logger.info("🛑 Container read task cancelled")
            except Exception as e:
                logger.error(f"❌ Fatal error in read_from_container: {e}")
        
        # Task for reading from WebSocket and sending to container
        async def write_to_container():
            """Read input from WebSocket and send to container PTY"""
            try:
                while True:
                    # Receive data from WebSocket
                    data = await websocket.receive()
                    
                    if "bytes" in data:
                        # Send raw bytes to container
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            exec_socket._sock.send,
                            data["bytes"]
                        )
                    elif "text" in data:
                        # Convert text to bytes and send
                        text_bytes = data["text"].encode("utf-8")
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            exec_socket._sock.send,
                            text_bytes
                        )
                    else:
                        logger.warning(f"⚠️ Unknown WebSocket message type: {data}")
                        
            except WebSocketDisconnect:
                logger.info("🔌 WebSocket disconnected by client")
            except asyncio.CancelledError:
                logger.info("🛑 Container write task cancelled")
            except Exception as e:
                logger.error(f"❌ Error writing to container: {e}")
        
        # Run both tasks concurrently
        read_task = asyncio.create_task(read_from_container())
        write_task = asyncio.create_task(write_to_container())
        
        # Wait for either task to complete
        done, pending = await asyncio.wait(
            [read_task, write_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Cancel remaining tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        logger.info(f"✅ Terminal session ended for session: {session_id}")
        
    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket disconnected for session: {session_id}")
    except Exception as e:
        logger.error(f"❌ Terminal WebSocket error: {e}")
        try:
            await websocket.send_json({"error": str(e)})
        except:
            pass
    finally:
        # Clean up exec socket
        if exec_instance:
            try:
                exec_socket.close()
                logger.info("🧹 Exec socket closed")
            except:
                pass
        
        # Close WebSocket if still open
        try:
            await websocket.close()
        except:
            pass
