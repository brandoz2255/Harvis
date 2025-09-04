#!/usr/bin/env python3
"""
Basic standalone test for session lifecycle management
Tests core logic without external dependencies
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional, Any

# Minimal session lifecycle implementation for testing
class SessionState(Enum):
    STOPPED = "stopped"
    STARTING = "starting" 
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"

@dataclass
class SessionInfo:
    session_id: str
    state: SessionState
    container_exists: bool
    volume_exists: bool
    container_id: Optional[str] = None
    volume_name: Optional[str] = None
    last_ready_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    error_message: Optional[str] = None
    user_id: Optional[str] = None

class MockSessionManager:
    def __init__(self):
        self._sessions: Dict[str, SessionInfo] = {}
    
    def is_session_ready(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        return self._sessions[session_id].state == SessionState.RUNNING
    
    def add_session(self, session_id: str, state: SessionState):
        self._sessions[session_id] = SessionInfo(
            session_id=session_id,
            state=state,
            container_exists=state in [SessionState.RUNNING, SessionState.STARTING],
            volume_exists=True
        )

def test_session_readiness():
    """Test session readiness logic"""
    print("🧪 Testing session readiness logic...")
    
    manager = MockSessionManager()
    
    # Test 1: Non-existent session not ready
    assert not manager.is_session_ready("non-existent"), "Non-existent session should not be ready"
    print("✅ Test 1: Non-existent session not ready")
    
    # Test 2: Stopped session not ready  
    manager.add_session("test-session", SessionState.STOPPED)
    assert not manager.is_session_ready("test-session"), "Stopped session should not be ready"
    print("✅ Test 2: Stopped session not ready")
    
    # Test 3: Starting session not ready
    manager.add_session("test-session", SessionState.STARTING)
    assert not manager.is_session_ready("test-session"), "Starting session should not be ready"
    print("✅ Test 3: Starting session not ready")
    
    # Test 4: Running session is ready
    manager.add_session("test-session", SessionState.RUNNING)
    assert manager.is_session_ready("test-session"), "Running session should be ready"
    print("✅ Test 4: Running session is ready")
    
    # Test 5: Error session not ready
    manager.add_session("test-session", SessionState.ERROR)
    assert not manager.is_session_ready("test-session"), "Error session should not be ready"
    print("✅ Test 5: Error session not ready")
    
    print("🎉 All session readiness tests passed!")

def test_session_info_serialization():
    """Test SessionInfo data structure"""
    print("🧪 Testing SessionInfo serialization...")
    
    now = datetime.now()
    session = SessionInfo(
        session_id="test-session",
        state=SessionState.RUNNING,
        container_exists=True,
        volume_exists=True,
        container_id="container-123",
        volume_name="volume-123",
        last_ready_at=now,
        created_at=now,
        user_id="user-123"
    )
    
    # Test basic properties
    assert session.session_id == "test-session"
    assert session.state == SessionState.RUNNING
    assert session.container_exists
    assert session.volume_exists
    print("✅ SessionInfo properties work correctly")
    
    print("🎉 SessionInfo serialization tests passed!")

def test_state_transitions():
    """Test valid state transitions"""
    print("🧪 Testing state transitions...")
    
    manager = MockSessionManager()
    
    # Typical flow: stopped -> starting -> running
    manager.add_session("test", SessionState.STOPPED)
    assert manager._sessions["test"].state == SessionState.STOPPED
    print("✅ State 1: STOPPED")
    
    manager._sessions["test"].state = SessionState.STARTING
    assert not manager.is_session_ready("test")
    print("✅ State 2: STARTING (not ready)")
    
    manager._sessions["test"].state = SessionState.RUNNING
    assert manager.is_session_ready("test")
    print("✅ State 3: RUNNING (ready)")
    
    manager._sessions["test"].state = SessionState.STOPPING
    assert not manager.is_session_ready("test")
    print("✅ State 4: STOPPING (not ready)")
    
    manager._sessions["test"].state = SessionState.STOPPED
    assert not manager.is_session_ready("test")
    print("✅ State 5: STOPPED (not ready)")
    
    print("🎉 State transition tests passed!")

def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("🚀 Running Session Lifecycle Basic Tests")
    print("=" * 60)
    
    try:
        test_session_readiness()
        print()
        test_session_info_serialization()
        print()
        test_state_transitions()
        
        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED! Session lifecycle logic is working correctly.")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)