"""
Auth store - SQLite-backed storage for users, tenants, and API keys (v3.0.0).

Tables:
- tenants(id, name, created_at)
- users(id, tenant_id, email, password_hash, role, created_at, disabled)
- api_keys(id, tenant_id, label, key_hash, role, created_at, revoked_at)
"""

import hashlib
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import bcrypt

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
    """Hash an API key using SHA-256 with salt."""
    salted = f"{API_KEY_HASH_SECRET}:{api_key}"
    return hashlib.sha256(salted.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new API key (plaintext, shown once)."""
    return f"bess_{secrets.token_urlsafe(32)}"


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

            # API keys table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id)
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

    # -------------------------------------------------------------------------
    # API key operations
    # -------------------------------------------------------------------------

    def get_api_key_by_hash(self, key_hash: str) -> Optional[Dict[str, Any]]:
        """Get API key by hash (not revoked)."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, tenant_id, label, key_hash, role, created_at, revoked_at
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
            }
        finally:
            conn.close()

    def create_api_key(
        self,
        tenant_id: str,
        label: str,
        role: Role = Role.SERVICE,
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
                INSERT INTO api_keys (id, tenant_id, label, key_hash, role, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (key_id, tenant_id, label, key_hash, role.value, created_at))
            conn.commit()
            return {
                "id": key_id,
                "tenant_id": tenant_id,
                "label": label,
                "role": role.value,
                "created_at": created_at,
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
                SELECT id, tenant_id, label, role, created_at, revoked_at
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
            return cursor.rowcount > 0
        finally:
            conn.close()

    def authenticate_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Authenticate by API key. Returns key info if valid."""
        key_hash = hash_api_key(api_key)
        return self.get_api_key_by_hash(key_hash)


# Global instance (lazy initialization)
_auth_store: Optional[AuthStore] = None


def get_auth_store() -> AuthStore:
    """Get or create the global AuthStore instance."""
    global _auth_store
    if _auth_store is None:
        _auth_store = AuthStore()
    return _auth_store
