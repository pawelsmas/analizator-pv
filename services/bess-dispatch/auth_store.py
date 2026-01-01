"""
Auth store - SQLite-backed storage for users, tenants, API keys, invites, and shares (v3.1.0, v3.2.0 rotation).

Tables:
- tenants(id, name, created_at)
- users(id, tenant_id, email, password_hash, role, created_at, disabled)
- api_keys(id, tenant_id, label, key_hash, role, created_at, revoked_at, last_used_at, rotated_from)
- invites(id, tenant_id, email, role, token_hash, created_at, expires_at, accepted_at, revoked_at, created_by)
- shares(id, tenant_id, resource_type, resource_id, token_hash, created_at, expires_at, revoked_at, created_by, label)
"""

import hashlib
import hmac
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import bcrypt
from prometheus_client import Counter, Gauge

from auth_config import (
    API_KEY_HASH_SECRET,
    AUTH_DB_PATH,
    DEV_SEED_ADMIN,
    DEFAULT_TENANT_ID,
    Role,
    is_auth_enabled,
)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    # bcrypt requires bytes and has 72-byte limit
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


def hash_api_key(api_key: str) -> str:
    """Hash an API key using HMAC-SHA256 for stricter security (v3.2.0)."""
    return hmac.new(
        API_KEY_HASH_SECRET.encode(),
        api_key.encode(),
        hashlib.sha256
    ).hexdigest()


# Prometheus metrics for API keys (v3.2.0)
API_KEY_USES_TOTAL = Counter(
    "bess_api_key_uses_total",
    "Total API key authentication uses"
)
API_KEY_ROTATIONS_TOTAL = Counter(
    "bess_api_key_rotations_total",
    "Total API key rotations"
)
API_KEYS_ACTIVE = Gauge(
    "bess_api_keys_active",
    "Number of active (non-revoked) API keys"
)


def generate_api_key() -> str:
    """Generate a new API key (plaintext, shown once)."""
    return f"bess_{secrets.token_urlsafe(32)}"


# Invite token pepper (separate from API key secret for isolation)
INVITE_TOKEN_PEPPER = "bess_invite_v1"


def hash_invite_token(token: str) -> str:
    """Hash an invite token using SHA-256 with pepper."""
    salted = f"{INVITE_TOKEN_PEPPER}:{token}"
    return hashlib.sha256(salted.encode()).hexdigest()


def generate_invite_token() -> str:
    """Generate a new invite token (plaintext, shown once)."""
    return secrets.token_urlsafe(32)


# Share token pepper (separate from invite and API key for isolation)
SHARE_TOKEN_PEPPER = "bess_share_v1"


def hash_share_token(token: str) -> str:
    """Hash a share token using SHA-256 with pepper."""
    salted = f"{SHARE_TOKEN_PEPPER}:{token}"
    return hashlib.sha256(salted.encode()).hexdigest()


def generate_share_token() -> str:
    """Generate a new share token (plaintext, shown once)."""
    return secrets.token_urlsafe(32)


class AuthStore:
    """SQLite-backed auth store for users, tenants, and API keys."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize AuthStore."""
        self.db_path = db_path or AUTH_DB_PATH
        self._ensure_db()
        self._seed_if_needed()

    def _ensure_db(self) -> None:
        """Create database and tables if they don't exist."""
        db_dir = Path(self.db_path).parent
        if not db_dir.exists():
            db_dir.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Tenants table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id)
            """)

            # API keys table (v3.2.0: added last_used_at, rotated_from)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    last_used_at TEXT,
                    rotated_from TEXT,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id)
            """)

            # Migration: add new columns if they don't exist (v3.2.0)
            try:
                cursor.execute("ALTER TABLE api_keys ADD COLUMN last_used_at TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                cursor.execute("ALTER TABLE api_keys ADD COLUMN rotated_from TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Invites table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS invites (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    role TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    accepted_at TEXT,
                    revoked_at TEXT,
                    created_by TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                    FOREIGN KEY (created_by) REFERENCES users(id)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_invites_token_hash ON invites(token_hash)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_invites_tenant ON invites(tenant_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_invites_email ON invites(email)
            """)

            # Shares table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shares (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    revoked_at TEXT,
                    created_by TEXT NOT NULL,
                    label TEXT,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                    FOREIGN KEY (created_by) REFERENCES users(id)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_shares_token_hash ON shares(token_hash)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_shares_tenant ON shares(tenant_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_shares_resource ON shares(resource_type, resource_id)
            """)

            conn.commit()
        finally:
            conn.close()

    def _seed_if_needed(self) -> None:
        """Seed default tenant and admin user if needed."""
        if not is_auth_enabled():
            return

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Check if default tenant exists
            cursor.execute("SELECT id FROM tenants WHERE id = ?", (DEFAULT_TENANT_ID,))
            if cursor.fetchone() is None:
                # Create default tenant
                cursor.execute(
                    "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
                    (DEFAULT_TENANT_ID, "Default Tenant", datetime.now(timezone.utc).isoformat())
                )

            # Seed admin user if DEV_SEED_ADMIN is true and no users exist
            if DEV_SEED_ADMIN:
                cursor.execute("SELECT COUNT(*) FROM users")
                if cursor.fetchone()[0] == 0:
                    admin_id = str(uuid.uuid4())
                    cursor.execute("""
                        INSERT INTO users (id, tenant_id, email, password_hash, role, created_at, disabled)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        admin_id,
                        DEFAULT_TENANT_ID,
                        "admin@local",
                        hash_password("admin"),
                        Role.ADMIN.value,
                        datetime.now(timezone.utc).isoformat(),
                        0
                    ))

            conn.commit()
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Tenant operations
    # -------------------------------------------------------------------------

    def get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant by ID."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, created_at FROM tenants WHERE id = ?",
                (tenant_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {"id": row[0], "name": row[1], "created_at": row[2]}
        finally:
            conn.close()

    def create_tenant(self, tenant_id: str, name: str) -> Dict[str, Any]:
        """Create a new tenant."""
        created_at = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
                (tenant_id, name, created_at)
            )
            conn.commit()
            return {"id": tenant_id, "name": name, "created_at": created_at}
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # User operations
    # -------------------------------------------------------------------------

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, tenant_id, email, password_hash, role, created_at, disabled
                FROM users WHERE email = ?
            """, (email,))
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "tenant_id": row[1],
                "email": row[2],
                "password_hash": row[3],
                "role": row[4],
                "created_at": row[5],
                "disabled": bool(row[6]),
            }
        finally:
            conn.close()

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, tenant_id, email, password_hash, role, created_at, disabled
                FROM users WHERE id = ?
            """, (user_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "tenant_id": row[1],
                "email": row[2],
                "password_hash": row[3],
                "role": row[4],
                "created_at": row[5],
                "disabled": bool(row[6]),
            }
        finally:
            conn.close()

    def create_user(
        self,
        tenant_id: str,
        email: str,
        password: str,
        role: Role = Role.EDITOR,
    ) -> Dict[str, Any]:
        """Create a new user."""
        user_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        password_hash = hash_password(password)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (id, tenant_id, email, password_hash, role, created_at, disabled)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, tenant_id, email, password_hash, role.value, created_at, 0))
            conn.commit()
            return {
                "id": user_id,
                "tenant_id": tenant_id,
                "email": email,
                "role": role.value,
                "created_at": created_at,
                "disabled": False,
            }
        finally:
            conn.close()

    def authenticate_user(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate user by email and password."""
        user = self.get_user_by_email(email)
        if user is None:
            return None
        if user["disabled"]:
            return None
        if not verify_password(password, user["password_hash"]):
            return None
        return user

    def list_users(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List users for a tenant (without password_hash)."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, tenant_id, email, role, created_at, disabled
                FROM users WHERE tenant_id = ?
                ORDER BY created_at DESC
            """, (tenant_id,))
            return [
                {
                    "id": row[0],
                    "tenant_id": row[1],
                    "email": row[2],
                    "role": row[3],
                    "created_at": row[4],
                    "disabled": bool(row[5]),
                }
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def count_active_admins(self, tenant_id: str) -> int:
        """Count active (non-disabled) admin users in a tenant."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM users
                WHERE tenant_id = ? AND role = ? AND disabled = 0
            """, (tenant_id, Role.ADMIN.value))
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def update_user(
        self,
        user_id: str,
        tenant_id: str,
        role: Optional[str] = None,
        disabled: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update user role and/or disabled status. Returns updated user or None."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Build update parts
            updates = []
            params = []
            if role is not None:
                updates.append("role = ?")
                params.append(role)
            if disabled is not None:
                updates.append("disabled = ?")
                params.append(1 if disabled else 0)

            if not updates:
                # Nothing to update
                return self.get_user_by_id(user_id)

            params.extend([user_id, tenant_id])
            query = f"UPDATE users SET {', '.join(updates)} WHERE id = ? AND tenant_id = ?"
            cursor.execute(query, params)
            conn.commit()

            if cursor.rowcount == 0:
                return None

            return self.get_user_by_id(user_id)
        finally:
            conn.close()

    def set_user_password(self, user_id: str, tenant_id: str, new_password: str) -> bool:
        """Set a new password for a user. Returns True if user found and updated."""
        password_hash = hash_password(new_password)
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users SET password_hash = ?
                WHERE id = ? AND tenant_id = ?
            """, (password_hash, user_id, tenant_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def email_exists_in_tenant(self, email: str, tenant_id: str) -> bool:
        """Check if email already exists in tenant."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM users WHERE email = ? AND tenant_id = ?
            """, (email, tenant_id))
            return cursor.fetchone() is not None
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # API key operations
    # -------------------------------------------------------------------------

    def get_api_key_by_hash(self, key_hash: str) -> Optional[Dict[str, Any]]:
        """Get API key by hash (not revoked)."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, tenant_id, label, key_hash, role, created_at, revoked_at, last_used_at, rotated_from
                FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL
            """, (key_hash,))
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "tenant_id": row[1],
                "label": row[2],
                "key_hash": row[3],
                "role": row[4],
                "created_at": row[5],
                "revoked_at": row[6],
                "last_used_at": row[7],
                "rotated_from": row[8],
            }
        finally:
            conn.close()

    def get_api_key_by_id(self, key_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get API key by ID within tenant."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, tenant_id, label, key_hash, role, created_at, revoked_at, last_used_at, rotated_from
                FROM api_keys WHERE id = ? AND tenant_id = ?
            """, (key_id, tenant_id))
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "tenant_id": row[1],
                "label": row[2],
                "key_hash": row[3],
                "role": row[4],
                "created_at": row[5],
                "revoked_at": row[6],
                "last_used_at": row[7],
                "rotated_from": row[8],
            }
        finally:
            conn.close()

    def create_api_key(
        self,
        tenant_id: str,
        label: str,
        role: Role = Role.SERVICE,
        rotated_from: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new API key. Returns dict with plaintext key (shown once)."""
        key_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        plaintext_key = generate_api_key()
        key_hash = hash_api_key(plaintext_key)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO api_keys (id, tenant_id, label, key_hash, role, created_at, rotated_from)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (key_id, tenant_id, label, key_hash, role.value, created_at, rotated_from))
            conn.commit()
            API_KEYS_ACTIVE.inc()
            return {
                "id": key_id,
                "tenant_id": tenant_id,
                "label": label,
                "role": role.value,
                "created_at": created_at,
                "rotated_from": rotated_from,
                "api_key": plaintext_key,  # Shown once!
            }
        finally:
            conn.close()

    def list_api_keys(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List API keys for a tenant (without plaintext)."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, tenant_id, label, role, created_at, revoked_at, last_used_at, rotated_from
                FROM api_keys WHERE tenant_id = ?
                ORDER BY created_at DESC
            """, (tenant_id,))
            return [
                {
                    "id": row[0],
                    "tenant_id": row[1],
                    "label": row[2],
                    "role": row[3],
                    "created_at": row[4],
                    "revoked_at": row[5],
                    "last_used_at": row[6],
                    "rotated_from": row[7],
                }
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def revoke_api_key(self, key_id: str, tenant_id: str) -> bool:
        """Revoke an API key. Returns True if found and revoked."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE api_keys SET revoked_at = ?
                WHERE id = ? AND tenant_id = ? AND revoked_at IS NULL
            """, (datetime.now(timezone.utc).isoformat(), key_id, tenant_id))
            conn.commit()
            if cursor.rowcount > 0:
                API_KEYS_ACTIVE.dec()
                return True
            return False
        finally:
            conn.close()

    def update_api_key_last_used(self, key_id: str) -> None:
        """Update last_used_at timestamp for an API key."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE api_keys SET last_used_at = ?
                WHERE id = ?
            """, (datetime.now(timezone.utc).isoformat(), key_id))
            conn.commit()
        finally:
            conn.close()

    def authenticate_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Authenticate by API key. Returns key info if valid and updates last_used_at."""
        key_hash = hash_api_key(api_key)
        key_info = self.get_api_key_by_hash(key_hash)
        if key_info:
            self.update_api_key_last_used(key_info["id"])
            API_KEY_USES_TOTAL.inc()
        return key_info

    def rotate_api_key(self, key_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """
        Rotate an API key - revoke old key and create new one with same label/role.

        Returns new key info with plaintext, or None if original key not found.
        """
        # Get the old key
        old_key = self.get_api_key_by_id(key_id, tenant_id)
        if old_key is None or old_key.get("revoked_at") is not None:
            return None

        # Revoke the old key
        self.revoke_api_key(key_id, tenant_id)

        # Create new key with same label and role, linked to old key
        new_key = self.create_api_key(
            tenant_id=tenant_id,
            label=old_key["label"],
            role=Role(old_key["role"]),
            rotated_from=key_id,
        )

        API_KEY_ROTATIONS_TOTAL.inc()
        return new_key

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
        """Create a new invite. Returns dict with plaintext token (shown once)."""
        invite_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + timedelta(hours=expires_hours)
        plaintext_token = generate_invite_token()
        token_hash = hash_invite_token(plaintext_token)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO invites (id, tenant_id, email, role, token_hash, created_at, expires_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                invite_id,
                tenant_id,
                email,
                role.value,
                token_hash,
                created_at.isoformat(),
                expires_at.isoformat(),
                created_by,
            ))
            conn.commit()
            return {
                "id": invite_id,
                "tenant_id": tenant_id,
                "email": email,
                "role": role.value,
                "created_at": created_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "created_by": created_by,
                "token": plaintext_token,  # Shown once!
            }
        finally:
            conn.close()

    def list_invites(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List invites for a tenant (without token)."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, tenant_id, email, role, created_at, expires_at, accepted_at, revoked_at, created_by
                FROM invites WHERE tenant_id = ?
                ORDER BY created_at DESC
            """, (tenant_id,))
            return [
                {
                    "id": row[0],
                    "tenant_id": row[1],
                    "email": row[2],
                    "role": row[3],
                    "created_at": row[4],
                    "expires_at": row[5],
                    "accepted_at": row[6],
                    "revoked_at": row[7],
                    "created_by": row[8],
                }
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def get_invite_by_id(self, invite_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get invite by ID within tenant."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, tenant_id, email, role, created_at, expires_at, accepted_at, revoked_at, created_by
                FROM invites WHERE id = ? AND tenant_id = ?
            """, (invite_id, tenant_id))
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "tenant_id": row[1],
                "email": row[2],
                "role": row[3],
                "created_at": row[4],
                "expires_at": row[5],
                "accepted_at": row[6],
                "revoked_at": row[7],
                "created_by": row[8],
            }
        finally:
            conn.close()

    def get_invite_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Get invite by plaintext token. Returns invite if valid (not revoked, not accepted)."""
        token_hash = hash_invite_token(token)
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, tenant_id, email, role, created_at, expires_at, accepted_at, revoked_at, created_by
                FROM invites WHERE token_hash = ? AND revoked_at IS NULL AND accepted_at IS NULL
            """, (token_hash,))
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "tenant_id": row[1],
                "email": row[2],
                "role": row[3],
                "created_at": row[4],
                "expires_at": row[5],
                "accepted_at": row[6],
                "revoked_at": row[7],
                "created_by": row[8],
            }
        finally:
            conn.close()

    def revoke_invite(self, invite_id: str, tenant_id: str) -> bool:
        """Revoke an invite. Returns True if found and revoked."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE invites SET revoked_at = ?
                WHERE id = ? AND tenant_id = ? AND revoked_at IS NULL AND accepted_at IS NULL
            """, (datetime.now(timezone.utc).isoformat(), invite_id, tenant_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def accept_invite(self, invite_id: str) -> bool:
        """Mark an invite as accepted. Returns True if updated."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE invites SET accepted_at = ?
                WHERE id = ? AND accepted_at IS NULL AND revoked_at IS NULL
            """, (datetime.now(timezone.utc).isoformat(), invite_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def is_invite_expired(self, invite: Dict[str, Any]) -> bool:
        """Check if an invite is expired."""
        expires_at = datetime.fromisoformat(invite["expires_at"].replace("Z", "+00:00"))
        return datetime.now(timezone.utc) > expires_at

    def pending_invite_exists(self, email: str, tenant_id: str) -> bool:
        """Check if a pending (not accepted, not revoked, not expired) invite exists for email."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT expires_at FROM invites
                WHERE email = ? AND tenant_id = ? AND accepted_at IS NULL AND revoked_at IS NULL
            """, (email, tenant_id))
            for row in cursor.fetchall():
                expires_at = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < expires_at:
                    return True
            return False
        finally:
            conn.close()

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
        """Create a new share link. Returns dict with plaintext token (shown once)."""
        share_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        expires_at = None
        if expires_hours:
            expires_at = created_at + timedelta(hours=expires_hours)
        plaintext_token = generate_share_token()
        token_hash = hash_share_token(plaintext_token)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO shares (id, tenant_id, resource_type, resource_id, token_hash, created_at, expires_at, created_by, label)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                share_id,
                tenant_id,
                resource_type,
                resource_id,
                token_hash,
                created_at.isoformat(),
                expires_at.isoformat() if expires_at else None,
                created_by,
                label,
            ))
            conn.commit()
            return {
                "id": share_id,
                "tenant_id": tenant_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "created_at": created_at.isoformat(),
                "expires_at": expires_at.isoformat() if expires_at else None,
                "created_by": created_by,
                "label": label,
                "token": plaintext_token,  # Shown once!
            }
        finally:
            conn.close()

    def list_shares(self, tenant_id: str, resource_type: Optional[str] = None, resource_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List shares for a tenant, optionally filtered by resource."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            query = """
                SELECT id, tenant_id, resource_type, resource_id, created_at, expires_at, revoked_at, created_by, label
                FROM shares WHERE tenant_id = ?
            """
            params = [tenant_id]
            if resource_type:
                query += " AND resource_type = ?"
                params.append(resource_type)
            if resource_id:
                query += " AND resource_id = ?"
                params.append(resource_id)
            query += " ORDER BY created_at DESC"

            cursor.execute(query, params)
            return [
                {
                    "id": row[0],
                    "tenant_id": row[1],
                    "resource_type": row[2],
                    "resource_id": row[3],
                    "created_at": row[4],
                    "expires_at": row[5],
                    "revoked_at": row[6],
                    "created_by": row[7],
                    "label": row[8],
                }
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def get_share_by_id(self, share_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get share by ID within tenant."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, tenant_id, resource_type, resource_id, created_at, expires_at, revoked_at, created_by, label
                FROM shares WHERE id = ? AND tenant_id = ?
            """, (share_id, tenant_id))
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "tenant_id": row[1],
                "resource_type": row[2],
                "resource_id": row[3],
                "created_at": row[4],
                "expires_at": row[5],
                "revoked_at": row[6],
                "created_by": row[7],
                "label": row[8],
            }
        finally:
            conn.close()

    def get_share_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Get share by plaintext token. Returns share if valid (not revoked)."""
        token_hash = hash_share_token(token)
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, tenant_id, resource_type, resource_id, created_at, expires_at, revoked_at, created_by, label
                FROM shares WHERE token_hash = ? AND revoked_at IS NULL
            """, (token_hash,))
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "tenant_id": row[1],
                "resource_type": row[2],
                "resource_id": row[3],
                "created_at": row[4],
                "expires_at": row[5],
                "revoked_at": row[6],
                "created_by": row[7],
                "label": row[8],
            }
        finally:
            conn.close()

    def revoke_share(self, share_id: str, tenant_id: str) -> bool:
        """Revoke a share link. Returns True if found and revoked."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE shares SET revoked_at = ?
                WHERE id = ? AND tenant_id = ? AND revoked_at IS NULL
            """, (datetime.now(timezone.utc).isoformat(), share_id, tenant_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def is_share_expired(self, share: Dict[str, Any]) -> bool:
        """Check if a share is expired."""
        if share["expires_at"] is None:
            return False  # No expiry = never expires
        expires_at = datetime.fromisoformat(share["expires_at"].replace("Z", "+00:00"))
        return datetime.now(timezone.utc) > expires_at

    def validate_share_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate a share token. Returns share if valid (not revoked, not expired)."""
        share = self.get_share_by_token(token)
        if share is None:
            return None
        if self.is_share_expired(share):
            return None
        return share


# Global instance (lazy initialization)
_auth_store: Optional[AuthStore] = None


def get_auth_store() -> AuthStore:
    """Get or create the global AuthStore instance."""
    global _auth_store
    if _auth_store is None:
        _auth_store = AuthStore()
    return _auth_store
