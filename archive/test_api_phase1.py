import requests
import pytest
import uuid

# Base URL for the local FastAPI server
BASE_URL = "http://localhost:8000/api/v1"

# Generate a unique session ID for this test run to avoid state collision
SESSION_ID = f"test_session_{uuid.uuid4().hex[:6]}"
TENANT_ID = "tnt_test_001"

def test_01_initial_connection():
    """
    Test Case 1: Initial Connection
    Verify the system handles empty states correctly and triggers the first item in the routing sequence.
    """
    payload = {
        "session_id": SESSION_ID,
        "tenant_id": TENANT_ID,
        "event_type": "STATE_CHANGE"
    }
    
    response = requests.post(f"{BASE_URL}/state/sync", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["updates"] == []
    assert data["agent_response"] == "Let's start with your personal details. What is your first name?"
    assert data["is_complete"] is False

def test_02_provide_single_field():
    """
    Test Case 2: Provide Single Field (Standard Turn)
    Verify the router acknowledges the input, saves it, and accurately moves to the second question.
    """
    payload = {
        "session_id": SESSION_ID,
        "tenant_id": TENANT_ID,
        "event_type": "STATE_CHANGE",
        "overrides": {
            "first_name": "Jane"
        }
    }
    
    response = requests.post(f"{BASE_URL}/state/sync", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert len(data["updates"]) == 1
    assert data["updates"][0]["field_id"] == "first_name"
    assert data["updates"][0]["value"] == "Jane"
    
    assert data["agent_response"] == "And your last name?"
    assert data["is_complete"] is False

def test_03_bulk_fulfillment():
    """
    Test Case 3: Bulk Fulfillment
    Verify the router skips fulfilled fields and jumps down the list accurately.
    """
    payload = {
        "session_id": SESSION_ID,
        "tenant_id": TENANT_ID,
        "event_type": "STATE_CHANGE",
        "overrides": {
            "last_name": "Doe",
            "email": "jane.doe@example.com",
            "phone": "0400 000 000",
            "date_of_birth": "12/04/1990",
            "gender": "Female",
            "bio": "I am looking for support workers to help me participate in community events."
        }
    }
    
    response = requests.post(f"{BASE_URL}/state/sync", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert len(data["updates"]) == 6
    
    # Should skip all personal details and jump to the first Requirements question
    assert data["agent_response"] == "Do you have any cultural background or considerations we should be aware of?"

def test_04_verify_nested_structures():
    """
    Test Case 4: Verify Complex Nested Structures
    Verify the Pydantic models cleanly accept lists and nested Objects natively.
    """
    payload = {
        "session_id": SESSION_ID,
        "tenant_id": TENANT_ID,
        "event_type": "STATE_CHANGE",
        "overrides": {
            "emergency_contact": {
                "name": "John Doe",
                "relation": "Husband",
                "phone": "0411 111 111"
            },
            "mode_of_communication": ["Verbal / Spoken English", "Assistive App"],
            "plan_management_type": "Self Managed"
        }
    }
    
    response = requests.post(f"{BASE_URL}/state/sync", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    extracted_fields = [u["field_id"] for u in data["updates"]]
    
    assert "emergency_contact" in extracted_fields
    assert "mode_of_communication" in extracted_fields
    assert "plan_management_type" in extracted_fields

def test_05_verify_redis_persistence():
    """
    Test Case 5: Verify Redis Persistence (State Retrieval)
    Prove that Redis holds the full form structure across all the previous turns.
    """
    response = requests.get(f"{BASE_URL}/state/{SESSION_ID}")
    assert response.status_code == 200
    
    state = response.json()
    
    # Check explicitly set fields
    assert state["first_name"] == "Jane"
    assert state["last_name"] == "Doe"
    assert state["email"] == "jane.doe@example.com"
    
    # Check nested fields
    assert state["emergency_contact"]["name"] == "John Doe"
    assert state["mode_of_communication"] == ["Verbal / Spoken English", "Assistive App"]
    assert state["plan_management_type"] == "Self Managed"
    
    # Check untouched fields are still null (or default)
    assert state["primary_diagnosis"] is None
    assert state["ndis_number"] is None

def test_06_webrtc_telemetry_auth_token():
    """
    Test Case 6: WebRTC Telemetry Auth Token
    Ensure the backend generates a valid LiveKit JWT signature.
    """
    payload = {
        "session_id": SESSION_ID,
        "participant_name": "Jane_Doe_Customer"
    }
    
    response = requests.post(f"{BASE_URL}/webrtc/token", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["room_name"] == SESSION_ID
    assert data["participant"] == "Jane_Doe_Customer"
    assert "token" in data
    assert data["token"].startswith("eyJ")  # JWT tokens start with eyJ
    assert "websocket_url" in data

if __name__ == "__main__":
    print("Run this file using pytest:")
    print("pytest -v test_api_phase1.py")
