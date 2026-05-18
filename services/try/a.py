import boto3
import json
import re
from urllib.parse import urljoin
import requests

REGION = "ap-southeast-2"
MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)

# Will be replaced after successful login
jwt_token = ""

with open('services/try/formatted_apis.json', 'r') as f:
    AVAILABLE_APIS = json.load(f)

API_BASE_URL = "https://dev-api.isena.org/"

user_context = {
    "user_id": None,
    "organization_id": None,
    "roles": [],
    "user_type": None,
    "email": None,
    "authenticated": False
}

conversation_history = []

def get_auth_headers():
    """Get authorization headers"""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jwt_token}"
    }

def login_user(email, password):
    """Login with email and password"""
    print(f"\n[LOGIN] Authenticating {email}...")

    try:
        login_payload = {
            "email": email,
            "password": password
        }

        headers = {"Content-Type": "application/json"}

        # FIX 1: endpoint is /auth/login, not /api/auth/login
        response = requests.post(
            f"{API_BASE_URL}/api/auth/login",
            json=login_payload,
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            login_data = response.json()

            # FIX 2: response shape is { "data": { "accessToken": "..." } }
            data = login_data.get("data", {}) or {}
            global jwt_token
            jwt_token = data.get("accessToken") or data.get("access_token") or data.get("token")

            if jwt_token:
                # Opportunistically capture defaultContext / user info so we
                # don't have to refetch everything in authenticate_user()
                user = data.get("user") or {}
                default_ctx = data.get("defaultContext") or {}

                user_context["user_id"] = user.get("id") or default_ctx.get("userId")
                user_context["organization_id"] = default_ctx.get("organizationId")
                user_context["email"] = user.get("email") or email

                user_type_obj = user.get("userType") or {}
                if isinstance(user_type_obj, dict):
                    user_context["user_type"] = user_type_obj.get("type")

                print("  Login successful!")
                return True
            else:
                print("  Error: No accessToken in response")
                print(f"  Body: {login_data}")
                return False
        else:
            print(f"  Login failed: {response.status_code}")
            print(f"  Response: {response.text[:300]}")
            return False

    except Exception as e:
        print(f"  Login error: {e}")
        return False

def authenticate_user():
    """Authenticate user and fetch profile info based on role"""
    print("\n[AUTHENTICATION] Fetching user information...")

    try:
        headers = get_auth_headers()

        role_response = requests.get(
            f"{API_BASE_URL}organization/role/my-roles",
            headers=headers,
            timeout=10
        )

        roles = []
        if role_response.status_code == 200:
            roles_data = role_response.json()
            # Some endpoints wrap payloads in { "data": ... }; handle both
            if isinstance(roles_data, dict) and "data" in roles_data:
                roles_data = roles_data["data"]
            roles = roles_data if isinstance(roles_data, list) else []
            user_context["roles"] = roles
            print(f"  Roles: {roles}")
        else:
            print(f"  Role fetch returned {role_response.status_code}: {role_response.text[:200]}")

        role_name = roles[0].get("name", "").lower() if roles else ""

        # If login already gave us a user_type, prefer that; otherwise infer from role
        existing_type = user_context.get("user_type")
        if existing_type and isinstance(existing_type, str):
            rn = existing_type.lower()
            if "admin" in rn or "super" in rn or "coordinator" in rn:
                url = f"{API_BASE_URL}organization/view-profile"
                user_context["user_type"] = "admin"
            elif "staff" in rn or "worker" in rn or "isw" in rn:
                url = f"{API_BASE_URL}mobile/organization-member/details"
                user_context["user_type"] = "staff"
            elif "client" in rn or "participant" in rn:
                url = f"{API_BASE_URL}mobile/client/details"
                user_context["user_type"] = "client"
            elif "guardian" in rn or "visitor" in rn:
                url = f"{API_BASE_URL}mobile/visitor/profile"
                user_context["user_type"] = "guardian"
            else:
                url = f"{API_BASE_URL}organization/view-profile"
                user_context["user_type"] = "unknown"
        else:
            if "admin" in role_name or "coordinator" in role_name:
                url = f"{API_BASE_URL}organization/view-profile"
                user_context["user_type"] = "admin"
            elif "support worker" in role_name or "isw" in role_name or "staff" in role_name:
                url = f"{API_BASE_URL}mobile/organization-member/details"
                user_context["user_type"] = "staff"
            elif "client" in role_name or "participant" in role_name:
                url = f"{API_BASE_URL}mobile/client/details"
                user_context["user_type"] = "client"
            elif "guardian" in role_name or "visitor" in role_name:
                url = f"{API_BASE_URL}mobile/visitor/profile"
                user_context["user_type"] = "guardian"
            else:
                url = f"{API_BASE_URL}organization/view-profile"
                user_context["user_type"] = "unknown"

        profile_response = requests.get(url, headers=headers, timeout=10)

        if profile_response.status_code == 200:
            profile_data = profile_response.json()
            # Unwrap { data: ... } if present
            if isinstance(profile_data, dict) and "data" in profile_data and isinstance(profile_data["data"], dict):
                profile_data = profile_data["data"]

            user_context["user_id"] = (
                profile_data.get("id")
                or profile_data.get("userId")
                or profile_data.get("memberId")
                or user_context.get("user_id")
            )
            user_context["organization_id"] = (
                profile_data.get("organizationId")
                or user_context.get("organization_id")
            )
            user_context["email"] = profile_data.get("email") or user_context.get("email")

            print(f"  User Type: {user_context['user_type']}")
            print(f"  User ID: {user_context['user_id']}")
            print(f"  Organization ID: {user_context['organization_id']}")
            print(f"  Email: {user_context['email']}")
            user_context["authenticated"] = True
            return True
        else:
            print(f"  Profile fetch failed: {profile_response.status_code}")
            print(f"  Response: {profile_response.text[:200]}")
            # We at least have a token; allow the assistant to continue
            user_context["authenticated"] = True
            return True

    except Exception as e:
        print(f"  Authentication error: {e}")
        return False

def call_bedrock(messages, system_prompt=None):
    """Call Claude via Bedrock"""
    try:
        payload = {
            "modelId": MODEL_ID,
            "messages": messages,
            "inferenceConfig": {
                "maxTokens": 2048
            }
        }

        if system_prompt:
            payload["system"] = [{"text": system_prompt}]

        response = bedrock_runtime.converse(**payload)

        if response.get('output') and response['output'].get('message'):
            content = response['output']['message'].get('content', [])
            if content and isinstance(content, list):
                return content[0].get('text', '')

        return None

    except Exception as e:
        print(f"Bedrock error: {e}")
        return None

def get_api_description():
    """Create formatted description of available APIs"""
    api_text = "Available APIs:\n\n"
    for i, api in enumerate(AVAILABLE_APIS, 1):
        method = api.get('method', 'GET')
        path = api.get('path', '')
        description = api.get('description', '')
        api_text += f"{i}. {method} {path}\n"
        api_text += f"   {description}\n"

        if api.get('parameters'):
            params_str = ", ".join([f"{p.get('name', '')} ({p.get('type', '')})" for p in api['parameters']])
            api_text += f"   Parameters: {params_str}\n"
        api_text += "\n"
    return api_text

def detect_intent(user_question):
    """Detect if user wants API call or normal conversation"""
    system_prompt = f"""You are a SENA (NDIS service) assistant. Analyze user intent.

User Context:
- User ID: {user_context['user_id']}
- Organization: {user_context['organization_id']}
- Roles: {user_context['roles']}
- Type: {user_context['user_type']}

{get_api_description()}

Respond with JSON:
{{
    "intent": "<API|CHAT>",
    "reason": "<brief>",
    "api_path": "<path if API intent>",
    "method": "<method if API intent>"
}}

Intent=API if user asks about shifts, clients, allowances, staff, payroll, etc.
Intent=CHAT if user says hi, hello, thanks, questions about SENA, etc."""

    messages = [{"role": "user", "content": [{"text": user_question}]}]
    response = call_bedrock(messages, system_prompt)

    if not response:
        return {"intent": "CHAT", "reason": "No response"}

    try:
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except:
        pass

    return {"intent": "CHAT", "reason": "Parsing error"}

def find_best_api(user_question):
    """Use LLM to determine which API to call"""
    system_prompt = f"""Route API calls. User type: {user_context['user_type']}, Roles: {user_context['roles']}.
{get_api_description()}
Respond ONLY with JSON:
{{"api_path": "<path>", "method": "<GET|POST|PUT|DELETE>", "parameters": {{}}, "query_params": {{}}, "reasoning": "<why>"}}"""

    messages = [{"role": "user", "content": [{"text": user_question}]}]
    response = call_bedrock(messages, system_prompt)

    if not response:
        return None

    try:
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except:
        pass

    return None

def construct_api_url(api_path, path_params):
    """Replace path parameters with values"""
    url = api_path
    for param_name, param_value in path_params.items():
        url = url.replace(f"{{{param_name}}}", str(param_value))
    return urljoin(API_BASE_URL, url)

def call_target_api(method, url, query_params=None, body_params=None):
    """Call the target API"""
    try:
        headers = get_auth_headers()

        if method.upper() == 'GET':
            response = requests.get(url, params=query_params, headers=headers, timeout=10)
        elif method.upper() == 'POST':
            response = requests.post(url, json=body_params, params=query_params, headers=headers, timeout=10)
        elif method.upper() == 'PUT':
            response = requests.put(url, json=body_params, params=query_params, headers=headers, timeout=10)
        elif method.upper() == 'DELETE':
            response = requests.delete(url, params=query_params, headers=headers, timeout=10)
        else:
            return {"error": f"Unsupported HTTP method: {method}"}

        if response.status_code in [200, 201]:
            try:
                return response.json()
            except:
                return {"data": response.text}
        else:
            return {
                "error": f"API returned {response.status_code}",
                "details": response.text[:300]
            }
    except requests.exceptions.Timeout:
        return {"error": "API call timed out"}
    except requests.exceptions.ConnectionError:
        return {"error": f"Cannot reach {url}"}
    except Exception as e:
        return {"error": str(e)}

def process_normal_chat(user_question):
    """Handle normal conversation"""
    system_prompt = f"""You are a helpful SENA (NDIS service provider) assistant.
User: {user_context['user_type']} with roles: {user_context['roles']}
Organization: {user_context['organization_id']}

Answer questions about the SENA system, shifts, clients, allowances, etc.
Be friendly, concise, and helpful."""

    conversation_history.append({
        "role": "user",
        "content": [{"text": user_question}]
    })

    response = call_bedrock(conversation_history, system_prompt)

    if response:
        conversation_history.append({
            "role": "assistant",
            "content": [{"text": response}]
        })
        return response

    return "Sorry, could not process your request."

def check_access(api_path):
    """Check if user role can access this API"""
    user_type = user_context.get("user_type", "unknown")

    restricted = {
        "admin": ["/organization/", "/sena-admin"],
        "staff": ["/mobile/staff-shift", "/mobile/organization-member", "/organization-member/shift"],
        "client": ["/mobile/client", "/mobile/client-shift"],
        "guardian": ["/mobile/visitor"]
    }

    allowed_paths = restricted.get(user_type, [])

    if user_type == "admin":
        return True

    for path in allowed_paths:
        if path in api_path:
            return True

    return False

def process_api_call(user_question):
    """Handle API-based queries"""
    api_decision = find_best_api(user_question)

    if not api_decision or "error" in api_decision:
        return f"Could not find suitable API. Error: {api_decision.get('error', 'Unknown') if api_decision else 'No decision'}"

    if "api_path" not in api_decision or "method" not in api_decision:
        return f"API decision incomplete"

    if not check_access(api_decision['api_path']):
        return f"Access denied. Your role ({user_context['user_type']}) cannot access this API."

    print(f"  -> Selected: {api_decision['method']} {api_decision['api_path']}")

    api_url = construct_api_url(
        api_decision['api_path'],
        api_decision.get('parameters', {})
    )

    api_response = call_target_api(
        method=api_decision['method'],
        url=api_url,
        query_params=api_decision.get('query_params', {}),
        body_params=api_decision.get('parameters', {})
    )

    if "error" in api_response:
        return f"API Error: {api_response['error']}"

    system_prompt = """Translate technical API responses into clear, human-friendly language.
Be concise and highlight key information."""

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "text": f"""User asked: {user_question}

API response:
{json.dumps(api_response, indent=2)}

Give a natural, friendly answer."""
                }
            ]
        }
    ]

    result = call_bedrock(messages, system_prompt)
    if not result:
        return f"API Response: {json.dumps(api_response, indent=2)}"

    conversation_history.append({
        "role": "user",
        "content": [{"text": user_question}]
    })
    conversation_history.append({
        "role": "assistant",
        "content": [{"text": result}]
    })

    return result

def process_query(user_question):
    """Main query processor"""
    print(f"\nProcessing: {user_question}")

    intent_analysis = detect_intent(user_question)
    intent = intent_analysis.get('intent', 'CHAT')

    print(f"Intent: {intent} ({intent_analysis.get('reason', '')})")

    if intent == 'API':
        print("Mode: API Routing")
        return process_api_call(user_question)
    else:
        print("Mode: Normal Chat")
        return process_normal_chat(user_question)

if __name__ == "__main__":
    print("\n" + "="*70)
    print("SENA Assistant (Bedrock Model API)")
    print("="*70)
    print(f"Loaded {len(AVAILABLE_APIS)} APIs\n")

    email = input("Email: ").strip()
    password = input("Password: ").strip()

    if not login_user(email, password):
        print("Login failed. Exiting.")
        exit(1)

    if not authenticate_user():
        print("User info fetch failed. Exiting.")
        exit(1)

    print("\nAuthentication successful!")
    print(f"Welcome {user_context['email']}!")
    print("You can ask normal questions or API-based queries")
    print("Type 'quit' to exit\n")

    while True:
        try:
            user_input = input("\nYou: ").strip()

            if user_input.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break

            if not user_input:
                print("Please enter a question")
                continue

            result = process_query(user_input)
            print(f"\nAssistant: {result}")

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")
            continue