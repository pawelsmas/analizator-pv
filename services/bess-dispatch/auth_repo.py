"""
SQLAlchemy-based Auth Repository (v3.3.0 PR3).

Provides database operations for users, tenants, API keys, invites, and shares.
Uses SQLAlchemy ORM for PostgreSQL support while maintaining SQLite compatibility.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import bcrypt
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from auth_config import (
    API_KEY_HASH_SECRET,
    DEV_SEED_ADMIN,
    DEFAULT_TENANT_ID,
    Role,
    is_auth_enabled,
)
from db_config import DB_QUERY_DURATION, DB_BACKEND, DBBackend
from db_models import Tenant, User, APIKey, Invite, Share
from db_session import get_db_session


# Password hashing
def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    password_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        password_bytes = plain_password.encode("utf-8")[:72]
        hashed_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        return False


# API key hashing
def hash_api_key(api_key: str) -> str:
    """Hash an API key using SHA-256 with salt."""
    salted = f"{API_KEY_HASH_SECRET}:{api_key}"
    return hashlib.sha256(salted.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new API key (plaintext, shown once)."""
    return f"bess_{secrets.token_urlsafe(32)}"


# Invite token handling
INVITE_TOKEN_PEPPER = "bess_invite_v1"


def hash_invite_token(token: str) -> str:
    """Hash an invite token using SHA-256 with pepper."""
    salted = f"{INVITE_TOKEN_PEPPER}:{token}"
    return hashlib.sha256(salted.encode()).hexdigest()


def generate_invite_token() -> str:
    """Generate a new invite token (plaintext, shown once)."""
    return secrets.token_urlsafe(32)


# Share token handling
SHARE_TOKEN_PEPPER = "bess_share_v1"


def hash_share_token(token: str) -> str:
    """Hash a share token using SHA-256 with pepper."""
    salted = f"{SHARE_TOKEN_PEPPER}:{token}"
    return hashlib.sha256(salted.encode()).hexdigest()


def generate_share_token() -> str:
    """Generate a new share token (plaintext, shown once)."""
    return secrets.token_urlsafe(32)


class AuthRepo:
    """SQLAlchemy-based auth repository."""

    def __init__(self, session: Optional[Session] = None):
        """
        Initialize AuthRepo.

        Args:
            session: Optional SQLAlchemy session. If not provided, uses context manager.
        """
        self._session = session
        self._owns_session = session is None

    def _get_session(self):
        """Get session for operations."""
        if self._session is not None:
            return self._session
        raise RuntimeError("Session not provided and not in context manager")

    # -------------------------------------------------------------------------
    # Tenant operations
    # -------------------------------------------------------------------------

    def get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant by ID."""
        with DB_QUERY_DURATION.labels(repo="auth", op="get_tenant").time():
            with get_db_session() as db:
                tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
                return tenant.to_dict() if tenant else None

    def create_tenant(self, tenant_id: str, name: str) -> Dict[str, Any]:
        """Create a new tenant."""
        with DB_QUERY_DURATION.labels(repo="auth", op="create_tenant").time():
            with get_db_session() as db:
                tenant = Tenant(
                    id=tenant_id,
                    name=name,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(tenant)
                db.commit()
                db.refresh(tenant)
                return tenant.to_dict()

    def ensure_default_tenant(self) -> None:
        """Ensure default tenant exists."""
        if not is_auth_enabled():
            return

        with get_db_session() as db:
            existing = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
            if existing is None:
                tenant = Tenant(
                    id=DEFAULT_TENANT_ID,
                    name="Default Tenant",
                    created_at=datetime.now(timezone.utc),
                )
                db.add(tenant)
                db.commit()

    # -------------------------------------------------------------------------
    # User operations
    # -------------------------------------------------------------------------

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email."""
        with DB_QUERY_DURATION.labels(repo="auth", op="get_user_by_email").time():
            with get_db_session() as db:
                user = db.query(User).filter(User.email == email).first()
                return user.to_dict(include_hash=True) if user else None

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        with DB_QUERY_DURATION.labels(repo="auth", op="get_user_by_id").time():
            with get_db_session() as db:
                user = db.query(User).filter(User.id == user_id).first()
                return user.to_dict(include_hash=True) if user else None

    def create_user(
        self,
        tenant_id: str,
        email: str,
        password: str,
        role: Role = Role.EDITOR,
    ) -> Dict[str, Any]:
        """Create a new user."""
        with DB_QUERY_DURATION.labels(repo="auth", op="create_user").time():
            with get_db_session() as db:
                user = User(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    email=email,
                    password_hash=hash_password(password),
                    role=role.value,
                    created_at=datetime.now(timezone.utc),
                    disabled=False,
                    failed_attempts=0,
                )
                db.add(user)
                db.commit()
                db.refresh(user)
                return user.to_dict()

    def authenticate_user(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate user by email and password."""
        user = self.get_user_by_email(email)
        if user is None:
            return None
        if user.get("disabled"):
            return None
        if not verify_password(password, user.get("password_hash", "")):
            return None
        return user

    def list_users(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List users for a tenant (without password_hash)."""
        with DB_QUERY_DURATION.labels(repo="auth", op="list_users").time():
            with get_db_session() as db:
                users = db.query(User).filter(
                    User.tenant_id == tenant_id
                ).order_by(User.created_at.desc()).all()
                return [u.to_dict() for u in users]

    def count_active_admins(self, tenant_id: str) -> int:
        """Count active (non-disabled) admin users in a tenant."""
        with DB_QUERY_DURATION.labels(repo="auth", op="count_active_admins").time():
            with get_db_session() as db:
                return db.query(User).filter(
                    and_(
                        User.tenant_id == tenant_id,
                        User.role == Role.ADMIN.value,
                        User.disabled == False,
                    )
                ).count()

    def update_user(
        self,
        user_id: str,
        tenant_id: str,
        role: Optional[str] = None,
        disabled: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update user role and/or disabled status."""
        with DB_QUERY_DURATION.labels(repo="auth", op="update_user").time():
            with get_db_session() as db:
                user = db.query(User).filter(
                    and_(User.id == user_id, User.tenant_id == tenant_id)
                ).first()

                if user is None:
                    return None

                if role is not None:
                    user.role = role
                if disabled is not None:
                    user.disabled = disabled

                db.commit()
                db.refresh(user)
                return user.to_dict()

    def set_user_password(self, user_id: str, tenant_id: str, new_password: str) -> bool:
        """Set a new password for a user."""
        with DB_QUERY_DURATION.labels(repo="auth", op="set_user_password").time():
            with get_db_session() as db:
                user = db.query(User).filter(
                    and_(User.id == user_id, User.tenant_id == tenant_id)
                ).first()

                if user is None:
                    return False

                user.password_hash = hash_password(new_password)
                db.commit()
                return True

    def email_exists_in_tenant(self, email: str, tenant_id: str) -> bool:
        """Check if email already exists in tenant."""
        with DB_QUERY_DURATION.labels(repo="auth", op="email_exists").time():
            with get_db_session() as db:
                return db.query(User).filter(
                    and_(User.email == email, User.tenant_id == tenant_id)
                ).first() is not None

    def seed_admin_if_needed(self) -> None:
        """Seed admin user if DEV_SEED_ADMIN is enabled."""
        if not is_auth_enabled() or not DEV_SEED_ADMIN:
            return

        with get_db_session() as db:
            user_count = db.query(User).count()
            if user_count == 0:
                admin = User(
                    id=str(uuid.uuid4()),
                    tenant_id=DEFAULT_TENANT_ID,
                    email="admin@local",
                    password_hash=hash_password("admin"),
                    role=Role.ADMIN.value,
                    created_at=datetime.now(timezone.utc),
                    disabled=False,
                    failed_attempts=0,
                )
                db.add(admin)
                db.commit()

    # -------------------------------------------------------------------------
    # API key operations
    # -------------------------------------------------------------------------

    def get_api_key_by_hash(self, key_hash: str) -> Optional[Dict[str, Any]]:
        """Get API key by hash (not revoked)."""
        with DB_QUERY_DURATION.labels(repo="auth", op="get_api_key_by_hash").time():
            with get_db_session() as db:
                key = db.query(APIKey).filter(
                    and_(APIKey.key_hash == key_hash, APIKey.revoked_at == None)
                ).first()
                return key.to_dict() if key else None

    def create_api_key(
        self,
        tenant_id: str,
        label: str,
        role: Role = Role.SERVICE,
    ) -> Dict[str, Any]:
        """Create a new API key. Returns dict with plaintext key (shown once)."""
        with DB_QUERY_DURATION.labels(repo="auth", op="create_api_key").time():
            plaintext_key = generate_api_key()
            key_hash = hash_api_key(plaintext_key)

            with get_db_session() as db:
                api_key = APIKey(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    label=label,
                    key_hash=key_hash,
                    role=role.value,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(api_key)
                db.commit()
                db.refresh(api_key)

                result = api_key.to_dict()
                result["api_key"] = plaintext_key  # Shown once!
                return result

    def list_api_keys(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List API keys for a tenant (without plaintext)."""
        with DB_QUERY_DURATION.labels(repo="auth", op="list_api_keys").time():
            with get_db_session() as db:
                keys = db.query(APIKey).filter(
                    APIKey.tenant_id == tenant_id
                ).order_by(APIKey.created_at.desc()).all()
                return [k.to_dict() for k in keys]

    def revoke_api_key(self, key_id: str, tenant_id: str) -> bool:
        """Revoke an API key."""
        with DB_QUERY_DURATION.labels(repo="auth", op="revoke_api_key").time():
            with get_db_session() as db:
                key = db.query(APIKey).filter(
                    and_(
                        APIKey.id == key_id,
                        APIKey.tenant_id == tenant_id,
                        APIKey.revoked_at == None,
                    )
                ).first()

                if key is None:
                    return False

                key.revoked_at = datetime.now(timezone.utc)
                db.commit()
                return True

    def authenticate_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Authenticate by API key."""
        key_hash = hash_api_key(api_key)
        return self.get_api_key_by_hash(key_hash)

    def update_api_key_last_used(self, key_id: str) -> None:
        """Update last_used_at for an API key."""
        with DB_QUERY_DURATION.labels(repo="auth", op="update_api_key_last_used").time():
            with get_db_session() as db:
                key = db.query(APIKey).filter(APIKey.id == key_id).first()
                if key:
                    key.last_used_at = datetime.now(timezone.utc)
                    db.commit()

    # -------------------------------------------------------------------------
    # Invite operations
    # -------------------------------------------------------------------------

    def create_invite(
        self,
        tenant_id: str,
        email: str,
        role: Role,
        created_by: str,
        expires_hours: int = 72,
    ) -> Dict[str, Any]:
        """Create a new invite."""
        with DB_QUERY_DURATION.labels(repo="auth", op="create_invite").time():
            created_at = datetime.now(timezone.utc)
            expires_at = created_at + timedelta(hours=expires_hours)
            plaintext_token = generate_invite_token()
            token_hash = hash_invite_token(plaintext_token)

            with get_db_session() as db:
                invite = Invite(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    email=email,
                    role=role.value,
                    token_hash=token_hash,
                    created_at=created_at,
                    expires_at=expires_at,
                    created_by=created_by,
                )
                db.add(invite)
                db.commit()
                db.refresh(invite)

                result = invite.to_dict()
                result["token"] = plaintext_token  # Shown once!
                return result

    def list_invites(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List invites for a tenant."""
        with DB_QUERY_DURATION.labels(repo="auth", op="list_invites").time():
            with get_db_session() as db:
                invites = db.query(Invite).filter(
                    Invite.tenant_id == tenant_id
                ).order_by(Invite.created_at.desc()).all()
                return [i.to_dict() for i in invites]

    def get_invite_by_id(self, invite_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get invite by ID within tenant."""
        with DB_QUERY_DURATION.labels(repo="auth", op="get_invite_by_id").time():
            with get_db_session() as db:
                invite = db.query(Invite).filter(
                    and_(Invite.id == invite_id, Invite.tenant_id == tenant_id)
                ).first()
                return invite.to_dict() if invite else None

    def get_invite_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Get invite by plaintext token (not revoked, not accepted)."""
        with DB_QUERY_DURATION.labels(repo="auth", op="get_invite_by_token").time():
            token_hash = hash_invite_token(token)
            with get_db_session() as db:
                invite = db.query(Invite).filter(
                    and_(
                        Invite.token_hash == token_hash,
                        Invite.revoked_at == None,
                        Invite.accepted_at == None,
                    )
                ).first()
                return invite.to_dict() if invite else None

    def revoke_invite(self, invite_id: str, tenant_id: str) -> bool:
        """Revoke an invite."""
        with DB_QUERY_DURATION.labels(repo="auth", op="revoke_invite").time():
            with get_db_session() as db:
                invite = db.query(Invite).filter(
                    and_(
                        Invite.id == invite_id,
                        Invite.tenant_id == tenant_id,
                        Invite.revoked_at == None,
                        Invite.accepted_at == None,
                    )
                ).first()

                if invite is None:
                    return False

                invite.revoked_at = datetime.now(timezone.utc)
                db.commit()
                return True

    def accept_invite(self, invite_id: str) -> bool:
        """Mark an invite as accepted."""
        with DB_QUERY_DURATION.labels(repo="auth", op="accept_invite").time():
            with get_db_session() as db:
                invite = db.query(Invite).filter(
                    and_(
                        Invite.id == invite_id,
                        Invite.accepted_at == None,
                        Invite.revoked_at == None,
                    )
                ).first()

                if invite is None:
                    return False

                invite.accepted_at = datetime.now(timezone.utc)
                db.commit()
                return True

    def is_invite_expired(self, invite: Dict[str, Any]) -> bool:
        """Check if an invite is expired."""
        expires_at_str = invite.get("expires_at")
        if not expires_at_str:
            return True
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) > expires_at

    def pending_invite_exists(self, email: str, tenant_id: str) -> bool:
        """Check if a pending invite exists for email."""
        with DB_QUERY_DURATION.labels(repo="auth", op="pending_invite_exists").time():
            with get_db_session() as db:
                now = datetime.now(timezone.utc)
                invite = db.query(Invite).filter(
                    and_(
                        Invite.email == email,
                        Invite.tenant_id == tenant_id,
                        Invite.accepted_at == None,
                        Invite.revoked_at == None,
                        Invite.expires_at > now,
                    )
                ).first()
                return invite is not None

    # -------------------------------------------------------------------------
    # Share operations
    # -------------------------------------------------------------------------

    def create_share(
        self,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        created_by: str,
        label: Optional[str] = None,
        expires_hours: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create a new share link."""
        with DB_QUERY_DURATION.labels(repo="auth", op="create_share").time():
            created_at = datetime.now(timezone.utc)
            expires_at = None
            if expires_hours:
                expires_at = created_at + timedelta(hours=expires_hours)
            plaintext_token = generate_share_token()
            token_hash = hash_share_token(plaintext_token)

            with get_db_session() as db:
                share = Share(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    token_hash=token_hash,
                    created_at=created_at,
                    expires_at=expires_at,
                    created_by=created_by,
                    label=label,
                )
                db.add(share)
                db.commit()
                db.refresh(share)

                result = share.to_dict()
                result["token"] = plaintext_token  # Shown once!
                return result

    def list_shares(
        self,
        tenant_id: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List shares for a tenant."""
        with DB_QUERY_DURATION.labels(repo="auth", op="list_shares").time():
            with get_db_session() as db:
                query = db.query(Share).filter(Share.tenant_id == tenant_id)

                if resource_type:
                    query = query.filter(Share.resource_type == resource_type)
                if resource_id:
                    query = query.filter(Share.resource_id == resource_id)

                shares = query.order_by(Share.created_at.desc()).all()
                return [s.to_dict() for s in shares]

    def get_share_by_id(self, share_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get share by ID within tenant."""
        with DB_QUERY_DURATION.labels(repo="auth", op="get_share_by_id").time():
            with get_db_session() as db:
                share = db.query(Share).filter(
                    and_(Share.id == share_id, Share.tenant_id == tenant_id)
                ).first()
                return share.to_dict() if share else None

    def get_share_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Get share by plaintext token (not revoked)."""
        with DB_QUERY_DURATION.labels(repo="auth", op="get_share_by_token").time():
            token_hash = hash_share_token(token)
            with get_db_session() as db:
                share = db.query(Share).filter(
                    and_(Share.token_hash == token_hash, Share.revoked_at == None)
                ).first()
                return share.to_dict() if share else None

    def revoke_share(self, share_id: str, tenant_id: str) -> bool:
        """Revoke a share link."""
        with DB_QUERY_DURATION.labels(repo="auth", op="revoke_share").time():
            with get_db_session() as db:
                share = db.query(Share).filter(
                    and_(
                        Share.id == share_id,
                        Share.tenant_id == tenant_id,
                        Share.revoked_at == None,
                    )
                ).first()

                if share is None:
                    return False

                share.revoked_at = datetime.now(timezone.utc)
                db.commit()
                return True

    def is_share_expired(self, share: Dict[str, Any]) -> bool:
        """Check if a share is expired."""
        expires_at_str = share.get("expires_at")
        if not expires_at_str:
            return False  # No expiry = never expires
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) > expires_at

    def validate_share_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate a share token (not revoked, not expired)."""
        share = self.get_share_by_token(token)
        if share is None:
            return None
        if self.is_share_expired(share):
            return None
        return share


# Global instance (lazy initialization)
_auth_repo: Optional[AuthRepo] = None


def get_auth_repo() -> AuthRepo:
    """Get or create the global AuthRepo instance."""
    global _auth_repo
    if _auth_repo is None:
        _auth_repo = AuthRepo()
    return _auth_repo


def init_auth_repo() -> None:
    """Initialize auth repository (create default tenant, seed admin)."""
    repo = get_auth_repo()
    repo.ensure_default_tenant()
    repo.seed_admin_if_needed()
