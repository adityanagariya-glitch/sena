import json
import logging
import os
import requests
import boto3
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel

# Initialize standard logging configurations
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Core Infrastructure Environment Variables
BASE_API_URL = os.environ.get("BASE_API_URL", "https://your-company-api-domain.com")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
AGENT_ID = os.environ.get("BEDROCK_AGENT_ID", "ABC123XYZ")
AGENT_ALIAS_ID = os.environ.get("BEDROCK_AGENT_ALIAS_ID", "TSTALIAS")

# Initialize FastAPI instance
app = FastAPI(title="Bedrock Multi-Tenant API Router Gate")


# --- CORE SHARED BUSINESS LOGIC ENGINE ---

def universal_api_executor(bedrock_payload: dict, cognito_token: str, user_id: str, tenant_id: str) -> dict:
    """
    Step 2 Core Logic: Resolves structural paths (like {id}), appends 
    access-control header metadata, and safely triggers internal target APIs.
    """
    try:
        api_path = bedrock_payload.get("api_path")
        http_method = bedrock_payload.get("http_method", "GET").upper()
        path_params = bedrock_payload.get("path_parameters", {})
        payload_args = bedrock_payload.get("query_or_body_parameters", {})
        
        if not api_path:
            return {"error": "Critical structural error: 'api_path' parameter was missing from Bedrock package selection."}
            
        # Dynamically map path parameter variables (e.g. /details/{id} -> /details/4021)
        if "{id}" in api_path:
            target_id = path_params.get("id") or payload_args.get("id")
            if target_id:
                api_path = api_path.replace("{id}", str(target_id))
                payload_args.pop("id", None)  # Scrub duplicates out of the dictionary map
            else:
                return {"error": f"Target endpoint path configuration requires an active 'id' argument: {api_path}"}

        full_url = f"{BASE_API_URL.rstrip('/')}/{api_path.lstrip('/')}"
        
        # Enforce Multi-Tenant Isolation via Security Headers Injection
        headers = {
            "Authorization": f"Bearer {cognito_token}",
            "X-User-ID": str(user_id),
            "X-Tenant-ID": str(tenant_id),
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        logger.info(f"Routing transaction directly to target server: [{http_method}] -> {full_url}")

        if http_method == "GET":
            response = requests.get(full_url, params=payload_args, headers=headers, timeout=12)
        elif http_method in ["POST", "PUT", "PATCH"]:
            response = requests.post(full_url, json=payload_args, headers=headers, timeout=12)
        elif http_method == "DELETE":
            response = requests.delete(full_url, headers=headers, timeout=12)
        else:
            return {"error": f"The requested HTTP transaction type '{http_method}' is unsupported."}

        response.raise_for_status()
        return response.json()

    except requests.exceptions.HTTPError as err:
        logger.error(f"Target system connection returned an error status configuration: {err}")
        return {"error": f"API server returned status code {response.status_code}", "details": response.text}
    except Exception as e:
        return {"error": "Internal infrastructure routing failure", "details": str(e)}


def execute_conversational_turn(session_id: str, user_prompt: str, cognito_token: str, user_id: str, tenant_id: str, user_role: str) -> str:
    """
    Binds the orchestration loops together. Transmits strings to Bedrock Agent, 
    manages dynamic loops via Return of Control, and returns human language data.
    """
    bedrock_client = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
    
    # Securely inject Role-Based context attributes parameters 
    session_state = {
        "sessionAttributes": {
            "current_user_role": str(user_role),
            "current_tenant_id": str(tenant_id)
        }
    }
    
    # ✅ FIXED: Changed agent_alias_id to AGENT_ALIAS_ID (uppercase)
    response = bedrock_client.invoke_agent(
        agentId=AGENT_ID,
        agentAliasId=AGENT_ALIAS_ID,
        sessionId=session_id,
        inputText=user_prompt,
        sessionState=session_state
    )
    
    for event in response.get("completion", []):
        if "returnControl" in event:
            invocation_id = event["returnControl"]["invocationId"]
            invocation_input = event["returnControl"]["invocationInputs"]["functionInvocationInput"]
            bedrock_payload = invocation_input.get("parameters", {})
            
            # Step 2: Call your internal APIs with security wrappers attached 
            raw_api_data = universal_api_executor(
                bedrock_payload=bedrock_payload,
                cognito_token=cognito_token,
                user_id=user_id,
                tenant_id=tenant_id
            )
            
            # Re-engage Bedrock interface stream chain (Passing data up to trigger Step 3 Translation)
            # ✅ FIXED: Changed agent_alias_id to AGENT_ALIAS_ID (uppercase)
            follow_up_response = bedrock_client.invoke_agent(
                agentId=AGENT_ID,
                agentAliasId=AGENT_ALIAS_ID,
                sessionId=session_id,
                invocationId=invocation_id,
                sessionState=session_state,
                actionGroupInvocationResults=[
                    {
                        "functionResult": {
                            "actionGroup": invocation_input["actionGroup"],
                            "function": invocation_input["function"],
                            "responseBody": {
                                "TEXT": {"body": json.dumps(raw_api_data)}
                            },
                            "responseState": "FAILURE" if "error" in raw_api_data else "SUCCESS"
                        }
                    }
                ]
            )
            
            for sub_event in follow_up_response.get("completion", []):
                if "chunk" in sub_event:
                    return sub_event["chunk"]["bytes"].decode("utf-8")

        elif "chunk" in event:
            return event["chunk"]["bytes"].decode("utf-8")
            
    return "Operational runtime exception encountered tracking system transaction metrics."


# --- DEPLOYMENT ENVIRONMENT A: FASTAPI ROUTER INTERFACE ---

class ChatRequest(BaseModel):
    session_id: str
    user_prompt: str


@app.post("/api/v1/chat")
async def fastapi_chat_endpoint(
    request_data: ChatRequest,
    authorization: str = Header(..., description="Cognito JWT Token passed as 'Bearer <token>'"),
    x_user_id: str = Header(..., description="Unique User Identifier tracking string"),
    x_tenant_id: str = Header(..., description="Target Multi-Tenant operational environment key"),
    x_user_role: str = Header(..., description="System RBAC access profile configuration role string")
):
    """
    Standard REST endpoint wrapper for cloud servers, Docker containers, or local execution environments.
    """
    # Clean standard bearer prefix token strings if present
    cognito_token = authorization.replace("Bearer ", "") if "Bearer " in authorization else authorization
    
    try:
        final_translated_answer = execute_conversational_turn(
            session_id=request_data.session_id,
            user_prompt=request_data.user_prompt,
            cognito_token=cognito_token,
            user_id=x_user_id,
            tenant_id=x_tenant_id,
            user_role=x_user_role
        )
        return {"response": final_translated_answer}
    except Exception as exc:
        logger.error(f"FastAPI Runtime Failure Exception thrown: {str(exc)}")
        raise HTTPException(status_code=500, detail=str(exc))


# --- DEPLOYMENT ENVIRONMENT B: AWS LAMBDA HANDLER INTERFACE ---

def lambda_handler(event, context):
    """
    Standard entry-point function invoked directly by AWS Lambda when mapped behind an API Gateway proxy.
    """
    logger.info("AWS Lambda Proxy trigger received an interaction event context mapping.")
    
    try:
        # Extract metadata directly from the incoming API Gateway request context maps
        headers = event.get("headers", {})
        body = json.loads(event.get("body", "{}"))
        
        # Pull request values
        user_prompt = body.get("user_prompt")
        session_id = body.get("session_id")
        
        # Pull authorization context strings (with standard variations fallback safety checks)
        authorization = headers.get("Authorization") or headers.get("authorization")
        user_id = headers.get("X-User-ID") or headers.get("x-user-id")
        tenant_id = headers.get("X-Tenant-ID") or headers.get("x-tenant-id")
        user_role = headers.get("X-User-Role") or headers.get("x-user-role")
        
        if not all([user_prompt, session_id, authorization, user_id, tenant_id, user_role]):
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Missing required data parameter. Enforce headers: Authorization, X-User-ID, X-Tenant-ID, X-User-Role and fields: user_prompt, session_id"})
            }
            
        cognito_token = authorization.replace("Bearer ", "") if "Bearer " in authorization else authorization

        # Execute business flow
        final_translated_answer = execute_conversational_turn(
            session_id=session_id,
            user_prompt=user_prompt,
            cognito_token=cognito_token,
            user_id=user_id,
            tenant_id=tenant_id,
            user_role=user_role
        )

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"  # Global CORS mapping safety handler rule configuration 
            },
            "body": json.dumps({"response": final_translated_answer})
        }

    except Exception as lambda_err:
        logger.error(f"AWS Lambda execution routine exception crashed: {str(lambda_err)}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Internal AWS Lambda orchestration runtime error instance", "details": str(lambda_err)})
        }