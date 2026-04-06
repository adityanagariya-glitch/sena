from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import json
import redis.asyncio as redis
from langgraph.graph import StateGraph, END
from typing import TypedDict
import os
from livekit import api

app = FastAPI(title="Voice Onboarding Assistant API")

# --- CONTRACTS ---

class ContextPacket(BaseModel):
    session_id: str
    tenant_id: str
    event_type: str = Field(..., description="'STATE_CHANGE' or 'USER_AUDIO_PROCESSED'")
    overrides: Optional[Dict[str, Any]] = None
    message: Optional[str] = None

class FieldUpdateItem(BaseModel):
    field_id: str
    value: Any
    confidence: float
    source: str

class FieldUpdateResponse(BaseModel):
    updates: List[FieldUpdateItem]
    agent_response: str
    is_complete: bool

# Figma-aligned Pydantic Models for FormState

class EmergencyContact(BaseModel):
    name: Optional[str] = None
    relation: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

class Allergy(BaseModel):
    allergen: str
    description: Optional[str] = None

class Medication(BaseModel):
    name: str
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    purpose: Optional[str] = None
    instructions: Optional[str] = None

class SupportSchedule(BaseModel):
    category: str
    item_name: str
    funding_type: str
    duration_hours: Optional[float] = None
    starting_time: Optional[str] = None
    frequency: Optional[str] = None

class TokenRequest(BaseModel):
    session_id: str
    participant_name: str
    
class FormState(BaseModel):
    # 1. Personal Details
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    bio: Optional[str] = Field(None, description="A bit about me")
    preferred_language: Optional[str] = "English"
    interpreter_required: Optional[bool] = False
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    postcode: Optional[str] = None
    emergency_contact: Optional[EmergencyContact] = None

    # 2. Requirements
    cultural_considerations: Optional[str] = None
    important_to_me: Optional[str] = None
    routines_and_interests: Optional[str] = None
    mode_of_communication: Optional[List[str]] = Field(default_factory=list, description="e.g. Verbal/Spoken English, Devices")
    style_of_communication: Optional[List[str]] = Field(default_factory=list, description="e.g. Use clear language, give me extra time")

    # 3. NDIS Plan Details
    plan_management_type: Optional[str] = None
    ndis_number: Optional[str] = None
    plan_start_date: Optional[str] = None
    plan_end_date: Optional[str] = None
    plan_manager_entity: Optional[str] = None
    plan_manager_email: Optional[str] = None
    plan_manager_phone: Optional[str] = None
    ndis_goals: Optional[List[str]] = Field(default_factory=list)
    support_coordinator_name: Optional[str] = None
    support_coordinator_email: Optional[str] = None
    support_coordinator_phone: Optional[str] = None
    allocated_funding: Optional[Dict[str, float]] = Field(default_factory=dict, description="e.g. {'Daily Living': 24000.00}")
    schedule_of_supports: Optional[List[SupportSchedule]] = Field(default_factory=list)

    # 4. Documents (Tracked as booleans/status since actual files go to object storage)
    has_current_ndis_plan: Optional[bool] = False
    has_guardianship_order: Optional[bool] = False
    has_behaviour_support_plan: Optional[bool] = False
    has_restrictive_practices_auth: Optional[bool] = False
    has_hospital_discharge_summary: Optional[bool] = False
    has_other_assessments: Optional[bool] = False

    # 5. Medical & Information
    primary_diagnosis: Optional[str] = None
    secondary_diagnoses: Optional[str] = None
    blood_type: Optional[str] = None
    primary_doctor_name: Optional[str] = None
    primary_doctor_contact: Optional[str] = None
    date_of_last_checkup: Optional[str] = None
    allergies: Optional[List[Allergy]] = Field(default_factory=list)
    current_medication: Optional[List[Medication]] = Field(default_factory=list)
    mobility_status: Optional[str] = None
    support_requirements: Optional[str] = None
    
# --- MOCK LANGGRAPH ORCHESTRATOR ---

class AgentState(TypedDict):
    form_state: dict
    user_message: str
    agent_response: str

def mock_extraction_node(state: AgentState):
    """
    In Phase 2, this node will call Gemini Multimodal to extract fields
    from the user's audio transcript. For now, it passes through.
    """
    return state

def routing_node(state: AgentState):
    """
    Deterministic routing: checks FormState against required fields.
    If missing, prompts for the first missing field.
    """
    form = state["form_state"]
    
    # Define an ordered sequence of required fields mapping exactly to the Figma flow
    required_sequence = [
        # 1. Personal Details
        ("first_name", "Let's start with your personal details. What is your first name?"),
        ("last_name", "And your last name?"),
        ("email", "What is your email address?"),
        ("phone", "Could you provide your phone number?"),
        ("date_of_birth", "What is your date of birth?"),
        ("gender", "What is your gender?"),
        ("bio", "Could you tell me a little bit about yourself?"),
        
        # 2. Requirements
        ("cultural_considerations", "Do you have any cultural background or considerations we should be aware of?"),
        ("important_to_me", "What is most important to you when it comes to your support?"),
        ("routines_and_interests", "Do you have any specific routines or interests you'd like to share?"),
        ("mode_of_communication", "What is your preferred mode of communication? (e.g., Verbal, Devices)"),
        ("style_of_communication", "And what is your preferred style of communication? (e.g., Use clear simple language)"),

        # 3. NDIS Plan Details
        ("plan_management_type", "Moving on to your NDIS plan. How is your plan managed? (e.g., Agency Managed, Plan Managed, Self Managed)"),
        ("ndis_number", "What is your NDIS number?"),
        ("plan_start_date", "When does your NDIS plan start?"),
        ("plan_end_date", "And when does it end?"),

        # 4. Medical & Information
        ("primary_diagnosis", "What is your primary medical diagnosis?"),
        ("mobility_status", "What is your mobility status? (e.g., Independent, Requires assistance)"),
        ("support_requirements", "Can you describe your daily support requirements?")
    ]
    
    for field, prompt in required_sequence:
        if not form.get(field):
            return {"agent_response": prompt}
            
    return {"agent_response": "Thank you, you have completed all required onboarding fields! We will review your profile."}

# Build the dummy DAG
workflow = StateGraph(AgentState)
workflow.add_node("extraction", mock_extraction_node)
workflow.add_node("routing", routing_node)

workflow.set_entry_point("extraction")
workflow.add_edge("extraction", "routing")
workflow.add_edge("routing", END)

mock_agent_app = workflow.compile()
# --- REDIS CONFIG & ENDPOINTS ---

# Initialize async Redis client
redis_client = redis.from_url("redis://localhost:6379", decode_responses=True)

@app.post("/api/v1/state/sync", response_model=FieldUpdateResponse)
async def sync_state(packet: ContextPacket):
    """
    Fetches the current session state, applies frontend overrides,
    invokes the Agent to determine the next question, and saves state to Redis.
    """
    redis_key = f"session:{packet.session_id}:form"
    
    # 1. Fetch current state from Redis
    existing_data = await redis_client.get(redis_key)
    if existing_data:
        current_state = FormState(**json.loads(existing_data))
    else:
        current_state = FormState()

    updates = []
    
    # 2. Apply explicit overrides to the state
    if packet.event_type == "STATE_CHANGE" and packet.overrides:
        for key, val in packet.overrides.items():
            if hasattr(current_state, key):
                setattr(current_state, key, val)
                updates.append(
                    FieldUpdateItem(
                        field_id=key,
                        value=val,
                        confidence=1.0,
                        source="user_correction"
                    )
                )

    # 3. Invoke the Mock LangGraph Agent to determine the next step
    state_dict = current_state.model_dump() if hasattr(current_state, 'model_dump') else current_state.dict()
    
    agent_input = {
        "form_state": state_dict,
        "user_message": packet.message or "",
        "agent_response": ""
    }
    
    # Run the graph
    graph_result = mock_agent_app.invoke(agent_input)
    next_response = graph_result["agent_response"]
    is_done = "completed all" in next_response.lower()

    # 4. Save the merged state back to Redis (1 hour TTL)
    state_json = current_state.model_dump_json() if hasattr(current_state, 'model_dump_json') else current_state.json()
    await redis_client.setex(redis_key, 3600, state_json)
            
    return FieldUpdateResponse(
        updates=updates,
        agent_response=next_response,
        is_complete=is_done
    )

@app.get("/api/v1/state/{session_id}", response_model=FormState)
async def get_state(session_id: str):
    """
    Helper endpoint to verify the full FormState directly out of Redis.
    """
    redis_key = f"session:{session_id}:form"
    data = await redis_client.get(redis_key)
    if data:
        return FormState(**json.loads(data))
    return FormState()

@app.post("/api/v1/webrtc/token")
async def generate_webrtc_token(req: TokenRequest):
    """
    Generates a secure LiveKit JWT so the frontend can connect to the voice room.
    """
    # Use environment vars in prod, default to local dev keys for testing
    api_key = os.getenv("LIVEKIT_API_KEY", "devkey")
    api_secret = os.getenv("LIVEKIT_API_SECRET", "secret")
    ws_url = os.getenv("LIVEKIT_URL", "ws://localhost:7880")
    
    # Define what the user is allowed to do (join a specific room)
    grant = api.VideoGrants(room_join=True, room=req.session_id)
    
    # Generate the signed JWT token using method chaining
    access_token = (
        api.AccessToken(api_key, api_secret)
        .with_identity(req.participant_name)
        .with_name(req.participant_name)
        .with_grants(grant)
    )
    
    return {
        "room_name": req.session_id,
        "participant": req.participant_name,
        "token": access_token.to_jwt(),
        "websocket_url": ws_url
    }
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_contracts:app", host="0.0.0.0", port=8000, reload=True)