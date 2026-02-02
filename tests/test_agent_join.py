"""
Integration test for agent join reliability.
Tests that when a session starts, the agent joins within N seconds.
"""
import os
import sys
import asyncio
import httpx
import pytest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
AGENT_JOIN_TIMEOUT = 20  # seconds


@pytest.fixture
def api_client():
    """Create an async HTTP client."""
    return httpx.AsyncClient(base_url=API_BASE, timeout=30.0)


class TestAgentJoinReliability:
    """Test suite for agent join reliability."""

    @pytest.mark.asyncio
    async def test_api_health(self, api_client):
        """Test that API is healthy."""
        response = await api_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["livekit_configured"] == True, "LiveKit credentials not configured"

    @pytest.mark.asyncio
    async def test_agent_health(self, api_client):
        """Test that agent health endpoint works and LiveKit is reachable."""
        response = await api_client.get("/api/agent/health")
        assert response.status_code == 200
        data = response.json()
        
        if data["errors"]:
            pytest.skip(f"Agent health check failed: {data['errors']}")
        
        assert data["livekit_reachable"] == True, "Cannot reach LiveKit"

    @pytest.mark.asyncio
    async def test_session_creation_has_deterministic_room_name(self, api_client):
        """Test that session creation returns a deterministic room name."""
        response = await api_client.post("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        
        assert "id" in data
        assert "roomName" in data
        
        # Room name should follow pattern: focusgroup-<timestamp>-<id>
        room_name = data["roomName"]
        assert room_name.startswith("focusgroup-"), f"Room name should start with 'focusgroup-': {room_name}"
        
        parts = room_name.split("-")
        assert len(parts) >= 3, f"Room name should have at least 3 parts: {room_name}"

    @pytest.mark.asyncio
    async def test_join_returns_livekit_url(self, api_client):
        """Test that joining a session returns the LiveKit URL."""
        # Create session
        create_response = await api_client.post("/api/sessions")
        assert create_response.status_code == 200
        session = create_response.json()
        
        # Join session
        join_response = await api_client.post(
            f"/api/sessions/{session['id']}/join",
            json={
                "displayName": "Test User",
                "email": "test@example.com",
                "isOrganizer": True
            }
        )
        assert join_response.status_code == 200
        join_data = join_response.json()
        
        assert "token" in join_data
        assert "roomName" in join_data
        assert "livekitUrl" in join_data
        assert join_data["roomName"] == session["roomName"], "Room name mismatch"

    @pytest.mark.asyncio
    async def test_session_status_endpoint(self, api_client):
        """Test that session status endpoint returns agent presence info."""
        # Create and join session
        create_response = await api_client.post("/api/sessions")
        session = create_response.json()
        
        await api_client.post(
            f"/api/sessions/{session['id']}/join",
            json={"displayName": "Test", "isOrganizer": True}
        )
        
        # Get status
        status_response = await api_client.get(f"/api/sessions/{session['id']}/status")
        assert status_response.status_code == 200
        status = status_response.json()
        
        assert "agentJoined" in status
        assert "roomName" in status
        assert status["roomName"] == session["roomName"]

    @pytest.mark.asyncio
    async def test_debug_endpoint(self, api_client):
        """Test that debug endpoint works for room inspection."""
        # Create session
        create_response = await api_client.post("/api/sessions")
        session = create_response.json()
        
        # Call debug endpoint
        debug_response = await api_client.get(
            "/api/session/debug",
            params={"room": session["roomName"]}
        )
        assert debug_response.status_code == 200
        debug_data = debug_response.json()
        
        assert "room" in debug_data
        assert "livekit_participants" in debug_data
        assert "agent_present" in debug_data
        assert debug_data["room"] == session["roomName"]

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_agent_joins_within_timeout(self, api_client):
        """
        Integration test: When a session starts, the agent should join within N seconds.
        
        This test requires:
        1. API server running (make dev-api)
        2. Agent worker running (make dev-agent)
        
        Skip if agent worker is not running.
        """
        # First check if agent worker is available
        health_response = await api_client.get("/api/agent/health")
        if health_response.status_code != 200:
            pytest.skip("Agent health endpoint not available")
        
        health = health_response.json()
        if not health.get("livekit_reachable"):
            pytest.skip("LiveKit not reachable")

        # Create session
        create_response = await api_client.post("/api/sessions")
        assert create_response.status_code == 200
        session = create_response.json()
        session_id = session["id"]
        room_name = session["roomName"]
        
        print(f"\n[test] Created session: id={session_id} room={room_name}")

        # Join as organizer (this creates the room in LiveKit)
        join_response = await api_client.post(
            f"/api/sessions/{session_id}/join",
            json={
                "displayName": "Test Organizer",
                "email": "organizer@test.com",
                "isOrganizer": True
            }
        )
        assert join_response.status_code == 200
        join_data = join_response.json()
        print(f"[test] Joined as organizer: identity={join_data['identity']}")

        # Start session - this should trigger agent dispatch
        print(f"[test] Starting session (this will wait for agent)...")
        start_response = await api_client.post(f"/api/sessions/{session_id}/start")
        assert start_response.status_code == 200
        start_data = start_response.json()
        
        print(f"[test] Session started: agentConfirmed={start_data.get('agentConfirmed')}")

        # Check if agent was confirmed during start
        if start_data.get("agentConfirmed"):
            print(f"[test] ✅ Agent joined during session start!")
            assert start_data["agentJoined"] == True
            return

        # If not confirmed during start, poll for agent presence
        print(f"[test] Agent not confirmed during start, polling for up to {AGENT_JOIN_TIMEOUT}s...")
        
        agent_joined = False
        for i in range(AGENT_JOIN_TIMEOUT):
            status_response = await api_client.get(f"/api/sessions/{session_id}/status")
            if status_response.status_code == 200:
                status = status_response.json()
                if status.get("agentJoined"):
                    agent_joined = True
                    print(f"[test] ✅ Agent joined after {i+1} seconds: {status.get('agentIdentity')}")
                    break
            await asyncio.sleep(1)
            if i % 5 == 0:
                print(f"[test] Still waiting for agent... ({i}s)")

        if not agent_joined:
            # Get debug info
            debug_response = await api_client.get("/api/session/debug", params={"room": room_name})
            debug_info = debug_response.json() if debug_response.status_code == 200 else {}
            
            pytest.fail(
                f"Agent did not join within {AGENT_JOIN_TIMEOUT} seconds.\n"
                f"Room: {room_name}\n"
                f"Debug info: {debug_info}\n"
                f"Possible causes:\n"
                f"  - Agent worker not running (run: make dev-agent)\n"
                f"  - Room name mismatch\n"
                f"  - LiveKit dispatch not configured\n"
                f"  - Network/auth issues"
            )


if __name__ == "__main__":
    # Run with: python -m pytest tests/test_agent_join.py -v -s
    pytest.main([__file__, "-v", "-s"])
