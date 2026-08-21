import secrets
import logging
from typing import Optional, Tuple
from fastapi import HTTPException, Security, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import settings
from app.rate_limiter import rate_limiter

logger = logging.getLogger("server.auth")
security_bearer = HTTPBearer(auto_error=False)

def mask_token(token: str) -> str:
    """Mask token for secure log display."""
    if not token or len(token) < 6:
        return "***"
    return f"{token[:3]}...{token[-3:]}"

def verify_device_credentials(device_id: str, token: str, client_ip: str) -> Tuple[bool, Optional[str]]:
    """
    Verify device credentials using constant-time string comparison.
    Returns (is_valid, role) where role is 'baby' or 'parent'.
    """
    if rate_limiter.is_ip_blocked(client_ip):
        logger.warning(f"Rejected auth attempt from blocked IP: {client_ip}")
        return False, None

    # Check Baby Device
    if secrets.compare_digest(device_id, settings.BABY_DEVICE_ID):
        if secrets.compare_digest(token, settings.BABY_DEVICE_TOKEN):
            rate_limiter.record_success(client_ip)
            logger.info(f"Baby Client authenticated successfully: {device_id} from {client_ip}")
            return True, "baby"
    
    # Check Parent Device
    if secrets.compare_digest(device_id, settings.PARENT_DEVICE_ID):
        if secrets.compare_digest(token, settings.PARENT_DEVICE_TOKEN):
            rate_limiter.record_success(client_ip)
            logger.info(f"Parent Client authenticated successfully: {device_id} from {client_ip}")
            return True, "parent"

    # Failed Auth
    rate_limiter.record_failure(client_ip)
    logger.warning(
        f"Unauthorized access attempt: device_id='{device_id}', token='{mask_token(token)}' from IP={client_ip}"
    )
    return False, None

def authenticate_rest_request(
    device_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
    client_ip: str = "0.0.0.0"
) -> str:
    """FastAPI REST dependency for authentication."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    is_valid, role = verify_device_credentials(device_id, credentials.credentials, client_ip)
    if not is_valid or not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device credentials or IP locked out",
        )
    return role
