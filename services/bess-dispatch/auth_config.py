"""
Auth configuration for BESS API (v3.0.0).

Environment Variables:
- AUTH_MODE: 'disabled' or 'enabled' (default: 'disabled')
- JWT_SECRET: Required when AUTH_MODE=enabled
- JWT_EXPIRE_MINUTES: Token expiration (default: 720 = 12 hours)
- API_KEY_HASH_SECRET: Salt for API key hashing
- DEFAULT_TENANT_ID: Tenant ID when auth is disabled (default: 'default')
- DEV_SEED_ADMIN: If 'true' and DB empty, seed admin@local user
"""

import os
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AuthMode(str, Enum):
    """Auth mode enum."""
    DISABLED = "disabled"
    ENABLED = "enabled"


class Role(str, Enum):
    """User/API key roles for RBAC."""
    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"
    SERVICE = "service"  # For API keys

    @classmethod
    def get_level(cls, role: "Role") -> int:
        """Get role level for comparison (higher = more permissions)."""
        levels = {
            cls.VIEWER: 1,
            cls.EDITOR: 2,
            cls.SERVICE: 2,  # Same as editor
            cls.ADMIN: 3,
        }
        return levels.get(role, 0)

    def has_permission(self, required: "Role") -> bool:
        """Check if this role has at least the required permission level."""
        return Role.get_level(self) >= Role.get_level(required)


class AuthContext(BaseModel):
    """Authentication context for requests."""
    model_config = ConfigDict(use_enum_values=True)

    tenant_id: str
    user_id: Optional[str] = None
    email: Optional[str] = None
    role: Role
    auth_method: str  # 'jwt', 'api_key', or 'disabled'


# Configuration from environment
AUTH_MODE = AuthMode(os.getenv("AUTH_MODE", "disabled").lower())
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))
JWT_ALGORITHM = "HS256"
API_KEY_HASH_SECRET = os.getenv("API_KEY_HASH_SECRET", "bess-api-key-salt")
DEFAULT_TENANT_ID = os.getenv("DEFAULT_TENANT_ID", "default")
DEV_SEED_ADMIN = os.getenv("DEV_SEED_ADMIN", "false").lower() == "true"

# Auth database path
AUTH_DB_PATH = os.getenv("AUTH_DB_PATH", "/data/auth.db")


def is_auth_enabled() -> bool:
    """Check if authentication is enabled."""
    return AUTH_MODE == AuthMode.ENABLED


def validate_config() -> None:
    """Validate auth configuration on startup."""
    if is_auth_enabled() and not JWT_SECRET:
        raise ValueError("JWT_SECRET is required when AUTH_MODE=enabled")
