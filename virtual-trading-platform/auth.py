import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

load_dotenv()

# ---------------------------------------------------------------------------
# Config & Secrets
# ---------------------------------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", "super_secret_trading_jwt_key_2026")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "8"))

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Bearer token extractor
security = HTTPBearer(auto_error=True)


# ---------------------------------------------------------------------------
# Password Utilities
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# JWT Utilities
# ---------------------------------------------------------------------------
def create_access_token(
    user_id: str,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate a signed JWT token with user_id and role claims.
    
    Default expiry is 8 hours.
    """
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)

    to_encode: Dict[str, Any] = {
        "sub": str(user_id),
        "user_id": str(user_id),
        "role": str(role),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired access token: {str(exc)}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ---------------------------------------------------------------------------
# FastAPI Auth Dependencies
# ---------------------------------------------------------------------------
async def get_current_token_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict[str, Any]:
    """Extract and validate the JWT token payload from Authorization header."""
    token = credentials.credentials
    payload = decode_token(token)
    user_id: Optional[str] = payload.get("user_id") or payload.get("sub")
    role: Optional[str] = payload.get("role")

    if not user_id or not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing required user identity or role claims",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def get_current_admin(
    payload: Dict[str, Any] = Depends(get_current_token_payload),
) -> str:
    """FastAPI dependency to verify admin role and return the admin username/id.
    
    Raises:
        401 Unauthorized if token is invalid/expired.
        403 Forbidden if the authenticated subject does not have 'admin' role.
    """
    role = payload.get("role")
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin privileges required",
        )
    admin_id = str(payload.get("user_id") or payload.get("sub"))
    return admin_id


async def get_current_user(
    payload: Dict[str, Any] = Depends(get_current_token_payload),
) -> str:
    """FastAPI dependency to verify user role and extract user_id.
    
    CRITICAL: Returns ONLY the user_id extracted securely from the JWT claim.
    This serves as the single source of truth for user identification across
    all trading and data access routes. Never trust user_id from body/params.
    
    Raises:
        401 Unauthorized if token is invalid/expired.
        403 Forbidden if the authenticated subject is not a 'user'.
    """
    role = payload.get("role")
    if role != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: User access required",
        )
    user_id = str(payload.get("user_id") or payload.get("sub"))
    return user_id
