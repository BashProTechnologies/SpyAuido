import os
from typing import Dict

try:
    from pydantic_settings import BaseSettings
except ImportError:
    try:
        from pydantic import BaseSettings
    except ImportError:
        # Standard Dataclass Fallback if pydantic_settings is missing
        class BaseSettings:
            pass

class Settings(BaseSettings):
    APP_NAME: str = os.getenv("APP_NAME", "Bash Pro Tech & INTECHA Central Server")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # Security Secrets
    SECRET_KEY: str = os.getenv("SECRET_KEY", "DEFAULT_UNSECURE_SECRET_CHANGE_ME_IN_PRODUCTION_KEY_987654321")
    
    # Authorized Devices & Tokens
    # Default token for all baby/agent devices
    BABY_DEVICE_TOKEN: str = os.getenv("BABY_DEVICE_TOKEN", "secure_token_baby_room_98765")
    BABY_DEVICE_ID: str = os.getenv("BABY_DEVICE_ID", "baby_room_pc_01")
    
    PARENT_DEVICE_ID: str = os.getenv("PARENT_DEVICE_ID", "parent_room_pc_01")
    PARENT_DEVICE_TOKEN: str = os.getenv("PARENT_DEVICE_TOKEN", "secure_token_parent_room_43210")
    
    # Security & Rate Limiting
    MAX_AUTH_FAILURES: int = int(os.getenv("MAX_AUTH_FAILURES", "10"))
    LOCKOUT_DURATION_SECONDS: int = int(os.getenv("LOCKOUT_DURATION_SECONDS", "300"))
    
    # Network Heartbeat
    HEARTBEAT_INTERVAL: float = float(os.getenv("HEARTBEAT_INTERVAL", "5.0"))
    HEARTBEAT_TIMEOUT: float = float(os.getenv("HEARTBEAT_TIMEOUT", "10.0"))

settings = Settings()
