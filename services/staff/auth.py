"""Authentication: login, JWT decoding, user-context bootstrap.

`jwt_token` lives here (not in state.py) because it's reassigned with
`global jwt_token`. Any module that needs the bearer token should call
`get_auth_headers()` rather than importing `jwt_token` directly — that way
they always pick up the latest value.
"""
import base64
import json
import requests
import sys
from datetime import datetime

from config import API_BASE_URL
from state import user_context, apply_user_type_context
from agents_types import AuthResponse


def _fetch_and_apply_user_type(headers: dict | None = None) -> bool:
    """Fetch the authoritative user-type context from GET /auth/user-type and
    store it (canonical fields + derived legacy user_type).

    The API is the source of truth; on any failure we keep whatever was inferred
    earlier so auth never hard-fails over this lookup. Returns True on success.
    """
    try:
        headers = headers or get_auth_headers()
        resp = requests.get(f"{API_BASE_URL}/auth/user-type", headers=headers, timeout=10)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data") if isinstance(body, dict) else None
            if data:
                apply_user_type_context(data)
                print(f"  User-type (authoritative): {data}")
                return True
        else:
            print(f"  /auth/user-type returned {resp.status_code}")
    except Exception as e:
        print(f"  /auth/user-type fetch failed: {e}")
    return False


def _hydrate_user_timezone() -> None:
    """After successful auth, populate user_context['timezone'] from persistent
    storage if a non-expired entry exists. Non-fatal — if memory or DDB is
    unreachable, timezone stays None and the agent uses the Sydney fallback
    + asks the user to set it.
    """
    if not user_context.get("authenticated"):
        return
    try:
        # Lazy import — memory depends on AWS clients which may not be ready
        # in all callers (e.g. tests). Failures degrade gracefully.
        from memory import _load_user_timezone
        tz = _load_user_timezone()
        if tz:
            user_context["timezone"] = tz
            print(f"  Loaded timezone from memory: {tz}")
        else:
            print("  No timezone on file — will fall back to Sydney and ask the user.")
    except Exception as e:
        print(f"  Timezone hydrate skipped ({type(e).__name__}: {e})", file=sys.stderr)

# Will be replaced after successful login.
jwt_token: str = ""


def get_auth_headers() -> dict[str, str]:
    """Get authorization headers"""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://dev-api.isena.org",
        "Referer": "https://dev-api.isena.org/",
        "Authorization": f"Bearer {jwt_token}",
    }


def has_auth_token() -> bool:
    """True when this process has a bearer token loaded for backend API calls."""
    return bool((jwt_token or "").strip())


def decode_jwt(token: str | None) -> dict | None:
    """Decode JWT token to extract claims (without verification)"""
    if not token:
        return None
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None

        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding

        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception as e:
        print(f"JWT decode error: {e}")
        return None


def login_user(email: str, password: str) -> bool:
    """Login with email and password"""
    print(f"\n[LOGIN] Authenticating {email}...")

    try:
        login_payload = {
            "email": email,
            "password": password,
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://dev-api.isena.org",
            "Referer": "https://dev-api.isena.org/",
        }

        response = requests.post(
            f"{API_BASE_URL}/auth/ai/login",
            json=login_payload,
            headers=headers,
            timeout=10,
        )

        print("STATUS:", response.status_code)
        print("BODY:", response.text)

        if response.status_code == 200:
            login_data = response.json()

            # FIX 2: response shape is { "data": { "accessToken": "..." } }
            data = login_data.get("data", {}) or {}
            global jwt_token
            jwt_token = data.get("accessToken") or data.get("access_token") or data.get("token")

            if jwt_token:
                user = data.get("user") or {}
                default_ctx = data.get("defaultContext") or {}

                user_context["user_id"] = user.get("id") or default_ctx.get("userId")
                user_context["email"] = user.get("email") or email

                # Get org_id from defaultContext OR from organizationMembership OR from JWT claims
                org_id = default_ctx.get("organizationId")
                membership = user.get("organizationMembership") or []
                if not org_id and membership and isinstance(membership, list):
                    first_mem = membership[0]
                    if isinstance(first_mem, dict):
                        org_id = (first_mem.get("organization") or {}).get("id")
                        user_context["member_id"] = first_mem.get("id")
                        # staffType helps disambiguate (in_office=admin-ish, support_worker=field)
                        staff_type = first_mem.get("staffType")
                        if staff_type:
                            user_context["staff_type"] = staff_type

                # Fall back to JWT claims
                if not org_id:
                    claims = decode_jwt(jwt_token) or {}
                    org_id = claims.get("organizationId")
                    user_context["member_id"] = user_context.get("member_id") or claims.get("memberId")

                user_context["organization_id"] = org_id

                user_type_obj = user.get("userType") or {}
                if isinstance(user_type_obj, dict):
                    raw_type = user_type_obj.get("type", "")
                    user_context["user_type"] = raw_type.lower()

                print("Login successful!")
                return True
            else:
                print("No token found")
                return False
        else:
            print(f"Login failed: {response.status_code}")
            print(response.text)
            return False

    except Exception as e:
        print(f"Login error: {e}")
        return False


def authenticate_with_jwt(token: str | None) -> bool:
    """Authenticate using a JWT token directly"""
    global jwt_token
    print(f"\n[JWT AUTH] Authenticating with provided token...")

    if not token:
        print("  Error: No token provided")
        return False

    try:
        claims = decode_jwt(token)
        if not claims:
            print("  Error: Could not decode JWT token")
            return False

        jwt_token = token

        user_context["user_id"] = claims.get("userId")
        user_context["email"] = claims.get("email")
        user_context["organization_id"] = claims.get("organizationId")
        user_context["member_id"] = claims.get("memberId")

        exp = claims.get("exp")
        if exp:
            exp_time = datetime.fromtimestamp(exp)
            if datetime.now() > exp_time:
                print(f"  Error: JWT token expired at {exp_time}")
                return False
            else:
                print(f"  Token valid until: {exp_time}")

        # Fetch full role details from API
        print("  Fetching role information...")
        headers = get_auth_headers()

        roles = []
        roles_from_jwt = claims.get("roles", [])
        user_type = "unknown"

        if roles_from_jwt:
            for role_info in roles_from_jwt:
                role_id = role_info.get("id") if isinstance(role_info, dict) else role_info
                if role_id:
                    try:
                        role_response = requests.get(
                            f"{API_BASE_URL}/organization/role/{role_id}",
                            headers=headers,
                            timeout=10,
                        )
                        print(f"    Role lookup response: {role_response.status_code}")

                        if role_response.status_code == 200:
                            role_data = role_response.json()
                            if isinstance(role_data, dict) and "data" in role_data:
                                role_data = role_data["data"]
                            roles.append(role_data)
                            role_name = role_data.get('name', 'Unknown').lower()
                            print(f"    Role: {role_name}")

                            # Determine user_type from role name
                            if "admin" in role_name or "coordinator" in role_name:
                                user_type = "admin"
                            elif "staff" in role_name or "worker" in role_name or "isw" in role_name:
                                user_type = "staff"
                            elif "client" in role_name or "participant" in role_name:
                                user_type = "client"
                            elif "guardian" in role_name or "visitor" in role_name:
                                user_type = "guardian"
                        else:
                            print(f"    API error: {role_response.status_code} - {role_response.text[:200]}")
                    except Exception as e:
                        print(f"    Could not fetch role {role_id}: {e}")

        user_context["roles"] = roles if roles else roles_from_jwt
        user_context["user_type"] = user_type

        print("  JWT authentication successful!")
        print(f"  User: {user_context['email']}")
        print(f"  User ID: {user_context['user_id']}")
        print(f"  Organization: {user_context['organization_id']}")
        # Authoritative user-type from the API overrides the role-name inference above.
        _fetch_and_apply_user_type()
        user_context["authenticated"] = True
        _hydrate_user_timezone()
        return True

    except Exception as e:
        print(f"  JWT auth error: {e}")
        return False


def authenticate_user() -> bool:
    """Authenticate user and fetch profile info based on role"""
    print("\n[AUTHENTICATION] Fetching user information...")

    try:
        headers = get_auth_headers()

        # Role list — best-effort. The /organization/role/my-roles endpoint may not
        # exist for all user types (returns 500 for serviceProvider/superAdmin tokens).
        # If it fails we just rely on user_type captured during login.
        roles = user_context.get("roles") or []
        try:
            role_response = requests.get(
                f"{API_BASE_URL}/organization/role/my-roles",
                headers=headers,
                timeout=10,
            )
            if role_response.status_code == 200:
                roles_data = role_response.json()
                if isinstance(roles_data, dict) and "data" in roles_data:
                    roles_data = roles_data["data"]
                roles = roles_data if isinstance(roles_data, list) else roles
                user_context["roles"] = roles
        except Exception:
            pass

        role_name = roles[0].get("name", "").lower() if roles else ""

        # If login already gave us a user_type, prefer that; otherwise infer from role
        existing_type = user_context.get("user_type")
        staff_type = (user_context.get("staff_type") or "").lower()
        if existing_type and isinstance(existing_type, str):
            rn = existing_type.lower()
            if "super" in rn or "superadmin" in rn:
                url = f"{API_BASE_URL}/super-admin/get-profile"
                user_context["user_type"] = "admin"
            elif "serviceprovider" in rn or "service_provider" in rn or "provider" in rn:
                # Service provider = organisation owner / registered NDIS provider entity
                url = f"{API_BASE_URL}/organization/view-profile"
                user_context["user_type"] = "admin"
            elif "organizationmember" in rn or "organization_member" in rn or "member" in rn:
                # An org member — could be in-office (admin) or field staff
                if "office" in staff_type or "admin" in staff_type:
                    url = f"{API_BASE_URL}/organization/view-profile"
                    user_context["user_type"] = "admin"
                else:
                    url = f"{API_BASE_URL}/mobile/organization-member/details"
                    user_context["user_type"] = "staff"
            elif "admin" in rn or "coordinator" in rn:
                url = f"{API_BASE_URL}/organization/view-profile"
                user_context["user_type"] = "admin"
            elif "staff" in rn or "worker" in rn or "isw" in rn:
                url = f"{API_BASE_URL}/mobile/organization-member/details"
                user_context["user_type"] = "staff"
            elif "client" in rn or "participant" in rn:
                url = f"{API_BASE_URL}/mobile/client/details"
                user_context["user_type"] = "client"
            elif "guardian" in rn or "visitor" in rn:
                url = f"{API_BASE_URL}/mobile/visitor/profile"
                user_context["user_type"] = "guardian"
            else:
                url = f"{API_BASE_URL}/organization/view-profile"
                user_context["user_type"] = "unknown"
        else:
            if "super" in role_name:
                url = f"{API_BASE_URL}/super-admin/get-profile"
                user_context["user_type"] = "admin"
            elif "admin" in role_name or "coordinator" in role_name:
                url = f"{API_BASE_URL}/organization/view-profile"
                user_context["user_type"] = "admin"
            elif "support worker" in role_name or "isw" in role_name or "staff" in role_name:
                url = f"{API_BASE_URL}/mobile/organization-member/details"
                user_context["user_type"] = "staff"
            elif "client" in role_name or "participant" in role_name:
                url = f"{API_BASE_URL}/mobile/client/details"
                user_context["user_type"] = "client"
            elif "guardian" in role_name or "visitor" in role_name:
                url = f"{API_BASE_URL}/mobile/visitor/profile"
                user_context["user_type"] = "guardian"
            else:
                url = f"{API_BASE_URL}/organization/view-profile"
                user_context["user_type"] = "unknown"

        print("Detected user type:", existing_type or role_name)
        print("Using profile URL:", url)

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

            # Authoritative user-type from the API overrides the role-name inference above.
            _fetch_and_apply_user_type(headers)

            print(f"  User Type: {user_context['user_type']}")
            print(f"  User ID: {user_context['user_id']}")
            print(f"  Organization ID: {user_context['organization_id']}")
            print(f"  Email: {user_context['email']}")
            user_context["authenticated"] = True
            _hydrate_user_timezone()
            return True
        else:
            print(f"  Profile fetch failed: {profile_response.status_code}")
            print(f"  Response: {profile_response.text[:200]}")
            # We at least have a token; allow the assistant to continue
            user_context["authenticated"] = True
            _hydrate_user_timezone()
            return True

    except Exception as e:
        print(f"  Authentication error: {e}")
        return False
