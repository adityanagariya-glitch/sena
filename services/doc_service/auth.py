import jwt
from fastapi import HTTPException

from config import JWT_ENABLED, JWT_SECRET, JWT_ALGORITHM, ADMIN_ROLES


def decode_token(authorization: str) -> dict:
    if not JWT_ENABLED:
        return {"user_id": "dev", "org_id": "ndis", "role": "superadmin"}

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    token = authorization.split(" ", 1)[1]
    try:
        raw = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    user_id = raw.get("user_id") or raw.get("userId") or raw.get("sub", "")
    org_id  = raw.get("org_id")  or raw.get("organizationId", "")
    role    = raw.get("role", "")

    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing user identifier")
    if not org_id:
        raise HTTPException(status_code=401, detail="Token missing org identifier")

    return {**raw, "user_id": user_id, "org_id": org_id, "role": role}


def require_admin(claims: dict):
    if claims["role"] not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not authorised — admin role required")


def require_org_access(claims: dict, target_org_id: str):
    role   = claims["role"]
    org_id = claims["org_id"]
    if role == "coordinator" and org_id != target_org_id:
        raise HTTPException(
            status_code=403,
            detail=f"You can only manage documents for your own organisation ({org_id})",
        )
