"""
SCIM store - SQLite-backed storage for SCIM provisioning (v4.4.0).

Tables:
- scim_tokens(id, tenant_id, name, token_hash, created_at, revoked_at, last_used_at)
- scim_users(id, tenant_id, user_id, external_id, user_name, created_at, updated_at)
- scim_groups(id, tenant_id, display_name, external_id, created_at, updated_at)
- scim_group_members(id, scim_group_id, scim_user_id, created_at)
- scim_group_project_mappings(id, tenant_id, scim_group_id, project_id, role, enabled, created_at)

Membership source tracking in auth_store.project_memberships:
- source: 'manual' | 'scim'
- scim_group_id: nullable FK to scim_groups
"""

import hashlib
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from auth_config import AUTH_DB_PATH


# SCIM token pepper (separate from other tokens for isolation)
SCIM_TOKEN_PEPPER = "bess_scim_v1"


class MembershipSource(Enum):
    """Source of project membership."""
    MANUAL = "manual"
    SCIM = "scim"


def hash_scim_token(token: str) -> str:
    """Hash a SCIM token using SHA-256 with pepper."""
    salted = f"{SCIM_TOKEN_PEPPER}:{token}"
    return hashlib.sha256(salted.encode()).hexdigest()


def generate_scim_token() -> str:
    """Generate a new SCIM token (plaintext, shown once)."""
    return f"scim_{secrets.token_urlsafe(32)}"


class ScimStore:
    """SQLite-backed store for SCIM provisioning data."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize ScimStore."""
        self.db_path = db_path or AUTH_DB_PATH
        self._ensure_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_db(self) -> None:
        """Create SCIM tables if they don't exist."""
        db_dir = Path(self.db_path).parent
        if not db_dir.exists():
            db_dir.mkdir(parents=True, exist_ok=True)

        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # SCIM tokens table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scim_tokens (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    last_used_at TEXT,
                    UNIQUE(tenant_id, name)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scim_tokens_tenant ON scim_tokens(tenant_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scim_tokens_hash ON scim_tokens(token_hash)
            """)

            # SCIM users table (full SCIM user representation)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scim_users (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    external_id TEXT,
                    user_name TEXT NOT NULL,
                    email TEXT,
                    display_name TEXT,
                    given_name TEXT,
                    family_name TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(tenant_id, user_name)
                )
            """)
            # Unique index on external_id that allows NULLs
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_scim_users_external_id
                ON scim_users(tenant_id, external_id) WHERE external_id IS NOT NULL
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scim_users_tenant ON scim_users(tenant_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scim_users_user_name ON scim_users(tenant_id, user_name)
            """)

            # SCIM groups table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scim_groups (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    external_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(tenant_id, display_name)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scim_groups_tenant ON scim_groups(tenant_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scim_groups_display_name ON scim_groups(tenant_id, display_name)
            """)

            # SCIM group members table (many-to-many: groups <-> users)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scim_group_members (
                    id TEXT PRIMARY KEY,
                    scim_group_id TEXT NOT NULL,
                    scim_user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(scim_group_id, scim_user_id),
                    FOREIGN KEY (scim_group_id) REFERENCES scim_groups(id) ON DELETE CASCADE,
                    FOREIGN KEY (scim_user_id) REFERENCES scim_users(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scim_group_members_group ON scim_group_members(scim_group_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scim_group_members_user ON scim_group_members(scim_user_id)
            """)

            # SCIM group -> project mappings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scim_group_project_mappings (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    scim_group_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(tenant_id, scim_group_id, project_id),
                    FOREIGN KEY (scim_group_id) REFERENCES scim_groups(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scim_mappings_tenant ON scim_group_project_mappings(tenant_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scim_mappings_group ON scim_group_project_mappings(scim_group_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scim_mappings_project ON scim_group_project_mappings(project_id)
            """)

            conn.commit()
        finally:
            conn.close()

        # Run migrations for project_memberships
        self._migrate_membership_source()

    def _migrate_membership_source(self) -> None:
        """Add source and scim_group_id columns to project_memberships if not exists."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(project_memberships)")
            existing_columns = {row[1] for row in cursor.fetchall()}

            if "source" not in existing_columns:
                cursor.execute(
                    "ALTER TABLE project_memberships ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'"
                )

            if "scim_group_id" not in existing_columns:
                cursor.execute(
                    "ALTER TABLE project_memberships ADD COLUMN scim_group_id TEXT"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memberships_scim_group ON project_memberships(scim_group_id)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memberships_source ON project_memberships(source)"
                )

            conn.commit()
        finally:
            conn.close()

    # ========== SCIM Token Methods ==========

    def create_scim_token(
        self,
        tenant_id: str,
        name: str,
    ) -> tuple[str, Dict[str, Any]]:
        """
        Create a new SCIM token.

        Returns:
            Tuple of (plaintext_token, token_record)
        """
        token_id = str(uuid.uuid4())
        plaintext_token = generate_scim_token()
        token_hash = hash_scim_token(plaintext_token)
        now = datetime.now(timezone.utc).isoformat()

        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO scim_tokens (id, tenant_id, name, token_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token_id, tenant_id, name, token_hash, now),
            )
            conn.commit()

            return plaintext_token, {
                "id": token_id,
                "tenant_id": tenant_id,
                "name": name,
                "created_at": now,
                "revoked_at": None,
                "last_used_at": None,
            }
        finally:
            conn.close()

    def rotate_scim_token(self, token_id: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """
        Rotate a SCIM token (delete old, create new with same name).

        Returns:
            Tuple of (new_plaintext_token, token_record) or None if not found
        """
        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # Get existing token
            cursor.execute(
                "SELECT * FROM scim_tokens WHERE id = ? AND revoked_at IS NULL",
                (token_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            now = datetime.now(timezone.utc).isoformat()
            tenant_id = row["tenant_id"]
            token_name = row["name"]

            # Delete old token (to allow reuse of name due to UNIQUE constraint)
            cursor.execute(
                "DELETE FROM scim_tokens WHERE id = ?",
                (token_id,),
            )

            # Create new token with same name
            new_token_id = str(uuid.uuid4())
            plaintext_token = generate_scim_token()
            token_hash = hash_scim_token(plaintext_token)

            cursor.execute(
                """
                INSERT INTO scim_tokens (id, tenant_id, name, token_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (new_token_id, tenant_id, token_name, token_hash, now),
            )
            conn.commit()

            return plaintext_token, {
                "id": new_token_id,
                "tenant_id": tenant_id,
                "name": token_name,
                "created_at": now,
                "revoked_at": None,
                "last_used_at": None,
            }
        finally:
            conn.close()

    def revoke_scim_token(self, token_id: str) -> bool:
        """Revoke a SCIM token."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "UPDATE scim_tokens SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (now, token_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_scim_token(self, token_id: str) -> Optional[Dict[str, Any]]:
        """Get a SCIM token by ID."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scim_tokens WHERE id = ?", (token_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_scim_token_by_hash(self, token_hash: str) -> Optional[Dict[str, Any]]:
        """Get a SCIM token by hash (for auth)."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM scim_tokens WHERE token_hash = ? AND revoked_at IS NULL",
                (token_hash,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_scim_token_last_used(self, token_id: str) -> None:
        """Update last_used_at for a SCIM token."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "UPDATE scim_tokens SET last_used_at = ? WHERE id = ?",
                (now, token_id),
            )
            conn.commit()
        finally:
            conn.close()

    def list_scim_tokens(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List all SCIM tokens for a tenant."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, tenant_id, name, created_at, revoked_at, last_used_at
                FROM scim_tokens
                WHERE tenant_id = ?
                ORDER BY created_at DESC
                """,
                (tenant_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # ========== SCIM User Methods ==========

    def create_scim_user(
        self,
        tenant_id: str,
        user_name: str,
        external_id: Optional[str] = None,
        email: Optional[str] = None,
        display_name: Optional[str] = None,
        given_name: Optional[str] = None,
        family_name: Optional[str] = None,
        active: bool = True,
    ) -> Dict[str, Any]:
        """Create a SCIM user record."""
        scim_user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO scim_users (id, tenant_id, external_id, user_name, email,
                    display_name, given_name, family_name, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (scim_user_id, tenant_id, external_id, user_name.lower(), email,
                 display_name, given_name, family_name, 1 if active else 0, now, now),
            )
            conn.commit()

            return {
                "id": scim_user_id,
                "tenant_id": tenant_id,
                "external_id": external_id,
                "user_name": user_name.lower(),
                "email": email,
                "display_name": display_name,
                "given_name": given_name,
                "family_name": family_name,
                "active": active,
                "created_at": now,
                "updated_at": now,
            }
        finally:
            conn.close()

    def get_scim_user(self, scim_user_id: str) -> Optional[Dict[str, Any]]:
        """Get a SCIM user by ID."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scim_users WHERE id = ?", (scim_user_id,))
            row = cursor.fetchone()
            return self._format_user_row(row) if row else None
        finally:
            conn.close()

    def get_scim_user_by_user_name(
        self, tenant_id: str, user_name: str
    ) -> Optional[Dict[str, Any]]:
        """Get a SCIM user by userName."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM scim_users WHERE tenant_id = ? AND user_name = ?",
                (tenant_id, user_name.lower()),
            )
            row = cursor.fetchone()
            return self._format_user_row(row) if row else None
        finally:
            conn.close()

    def get_scim_user_by_external_id(
        self, tenant_id: str, external_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get a SCIM user by externalId."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM scim_users WHERE tenant_id = ? AND external_id = ?",
                (tenant_id, external_id),
            )
            row = cursor.fetchone()
            return self._format_user_row(row) if row else None
        finally:
            conn.close()

    def update_scim_user(
        self,
        scim_user_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """Update a SCIM user record with given fields."""
        if not updates:
            return True

        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()

            # Build dynamic update query
            set_clauses = []
            params = []

            allowed_fields = {
                "external_id", "user_name", "email", "display_name",
                "given_name", "family_name", "active"
            }

            for field, value in updates.items():
                if field in allowed_fields:
                    set_clauses.append(f"{field} = ?")
                    if field == "active":
                        params.append(1 if value else 0)
                    elif field == "user_name":
                        params.append(value.lower() if value else value)
                    else:
                        params.append(value)

            if not set_clauses:
                return True

            set_clauses.append("updated_at = ?")
            params.append(now)
            params.append(scim_user_id)

            sql = f"UPDATE scim_users SET {', '.join(set_clauses)} WHERE id = ?"
            cursor.execute(sql, params)
            conn.commit()

            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_scim_user(self, scim_user_id: str) -> bool:
        """Delete a SCIM user record."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM scim_users WHERE id = ?", (scim_user_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def list_scim_users(
        self,
        tenant_id: str,
        offset: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List SCIM users with pagination."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM scim_users
                WHERE tenant_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (tenant_id, limit, offset),
            )
            return [self._format_user_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def find_scim_users(
        self,
        tenant_id: str,
        field: str,
        value: str,
    ) -> List[Dict[str, Any]]:
        """Find SCIM users by a specific field value."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # Validate field to prevent SQL injection
            allowed_fields = {"user_name", "external_id", "email"}
            if field not in allowed_fields:
                return []

            # Case-insensitive for user_name
            if field == "user_name":
                value = value.lower()

            cursor.execute(
                f"""
                SELECT * FROM scim_users
                WHERE tenant_id = ? AND {field} = ?
                ORDER BY created_at DESC
                """,
                (tenant_id, value),
            )
            return [self._format_user_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def count_scim_users(self, tenant_id: str) -> int:
        """Count all SCIM users for a tenant."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM scim_users WHERE tenant_id = ?",
                (tenant_id,),
            )
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def _format_user_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Format a user row, converting active to boolean."""
        result = dict(row)
        result["active"] = bool(result.get("active", 1))
        return result

    # ========== SCIM Group Methods ==========

    def create_scim_group(
        self,
        tenant_id: str,
        display_name: str,
        external_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a SCIM group record."""
        scim_group_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO scim_groups (id, tenant_id, display_name, external_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (scim_group_id, tenant_id, display_name, external_id, now, now),
            )
            conn.commit()

            return {
                "id": scim_group_id,
                "tenant_id": tenant_id,
                "display_name": display_name,
                "external_id": external_id,
                "created_at": now,
                "updated_at": now,
            }
        finally:
            conn.close()

    def get_scim_group(self, scim_group_id: str) -> Optional[Dict[str, Any]]:
        """Get a SCIM group by ID."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scim_groups WHERE id = ?", (scim_group_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_scim_group_by_display_name(
        self, tenant_id: str, display_name: str
    ) -> Optional[Dict[str, Any]]:
        """Get a SCIM group by displayName."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM scim_groups WHERE tenant_id = ? AND display_name = ?",
                (tenant_id, display_name),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_scim_group(
        self,
        scim_group_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """Update a SCIM group record."""
        if not updates:
            return True

        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()

            # Build dynamic update query
            set_clauses = []
            params = []

            allowed_fields = {"display_name", "external_id"}

            for field, value in updates.items():
                if field in allowed_fields:
                    set_clauses.append(f"{field} = ?")
                    params.append(value)

            if not set_clauses:
                return True

            set_clauses.append("updated_at = ?")
            params.append(now)
            params.append(scim_group_id)

            sql = f"UPDATE scim_groups SET {', '.join(set_clauses)} WHERE id = ?"
            cursor.execute(sql, params)
            conn.commit()

            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_scim_group(self, scim_group_id: str) -> bool:
        """Delete a SCIM group record."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM scim_groups WHERE id = ?", (scim_group_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def list_scim_groups(
        self,
        tenant_id: str,
        offset: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List SCIM groups with pagination."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM scim_groups
                WHERE tenant_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (tenant_id, limit, offset),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def find_scim_groups(
        self,
        tenant_id: str,
        field: str,
        value: str,
    ) -> List[Dict[str, Any]]:
        """Find SCIM groups by a specific field value."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # Validate field to prevent SQL injection
            allowed_fields = {"display_name", "external_id"}
            if field not in allowed_fields:
                return []

            cursor.execute(
                f"""
                SELECT * FROM scim_groups
                WHERE tenant_id = ? AND {field} = ?
                ORDER BY created_at DESC
                """,
                (tenant_id, value),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def count_scim_groups(self, tenant_id: str) -> int:
        """Count all SCIM groups for a tenant."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM scim_groups WHERE tenant_id = ?",
                (tenant_id,),
            )
            return cursor.fetchone()[0]
        finally:
            conn.close()

    # ========== SCIM Group Members Methods ==========

    def add_group_member(self, scim_group_id: str, scim_user_id: str) -> bool:
        """Add a member to a SCIM group."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            member_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()

            cursor.execute(
                """
                INSERT OR IGNORE INTO scim_group_members (id, scim_group_id, scim_user_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (member_id, scim_group_id, scim_user_id, now),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def remove_group_member(self, scim_group_id: str, scim_user_id: str) -> bool:
        """Remove a member from a SCIM group."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM scim_group_members WHERE scim_group_id = ? AND scim_user_id = ?",
                (scim_group_id, scim_user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_group_members(self, scim_group_id: str) -> List[Dict[str, Any]]:
        """Get all members of a SCIM group."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT su.* FROM scim_users su
                JOIN scim_group_members sgm ON su.id = sgm.scim_user_id
                WHERE sgm.scim_group_id = ?
                ORDER BY su.user_name
                """,
                (scim_group_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_user_groups(self, scim_user_id: str) -> List[Dict[str, Any]]:
        """Get all groups a SCIM user belongs to."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT sg.* FROM scim_groups sg
                JOIN scim_group_members sgm ON sg.id = sgm.scim_group_id
                WHERE sgm.scim_user_id = ?
                ORDER BY sg.display_name
                """,
                (scim_user_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def set_group_members(
        self, scim_group_id: str, scim_user_ids: List[str]
    ) -> tuple[int, int]:
        """
        Set the complete member list for a group.

        Returns:
            Tuple of (members_added, members_removed)
        """
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()

            # Get current members
            cursor.execute(
                "SELECT scim_user_id FROM scim_group_members WHERE scim_group_id = ?",
                (scim_group_id,),
            )
            current_members = {row[0] for row in cursor.fetchall()}
            new_members = set(scim_user_ids)

            # Calculate diff
            to_add = new_members - current_members
            to_remove = current_members - new_members

            # Remove old members
            if to_remove:
                cursor.executemany(
                    "DELETE FROM scim_group_members WHERE scim_group_id = ? AND scim_user_id = ?",
                    [(scim_group_id, uid) for uid in to_remove],
                )

            # Add new members
            for uid in to_add:
                member_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO scim_group_members (id, scim_group_id, scim_user_id, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (member_id, scim_group_id, uid, now),
                )

            conn.commit()
            return len(to_add), len(to_remove)
        finally:
            conn.close()

    # ========== SCIM Group Project Mappings Methods ==========

    def create_group_project_mapping(
        self,
        tenant_id: str,
        scim_group_id: str,
        project_id: str,
        role: str,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        """Create a SCIM group to project mapping."""
        mapping_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO scim_group_project_mappings
                (id, tenant_id, scim_group_id, project_id, role, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (mapping_id, tenant_id, scim_group_id, project_id, role, 1 if enabled else 0, now),
            )
            conn.commit()

            return {
                "id": mapping_id,
                "tenant_id": tenant_id,
                "scim_group_id": scim_group_id,
                "project_id": project_id,
                "role": role,
                "enabled": enabled,
                "created_at": now,
            }
        finally:
            conn.close()

    def get_group_project_mapping(self, mapping_id: str) -> Optional[Dict[str, Any]]:
        """Get a group project mapping by ID."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM scim_group_project_mappings WHERE id = ?",
                (mapping_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                **dict(row),
                "enabled": bool(row["enabled"]),
            }
        finally:
            conn.close()

    def update_group_project_mapping(
        self,
        mapping_id: str,
        role: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update a group project mapping."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # Get current values
            cursor.execute(
                "SELECT * FROM scim_group_project_mappings WHERE id = ?",
                (mapping_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            new_role = role if role is not None else row["role"]
            new_enabled = enabled if enabled is not None else bool(row["enabled"])

            cursor.execute(
                """
                UPDATE scim_group_project_mappings
                SET role = ?, enabled = ?
                WHERE id = ?
                """,
                (new_role, 1 if new_enabled else 0, mapping_id),
            )
            conn.commit()

            return self.get_group_project_mapping(mapping_id)
        finally:
            conn.close()

    def delete_group_project_mapping(self, mapping_id: str) -> bool:
        """Delete a group project mapping."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM scim_group_project_mappings WHERE id = ?",
                (mapping_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def list_group_project_mappings(
        self,
        tenant_id: str,
        scim_group_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List group project mappings with optional filters."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            where_clauses = ["tenant_id = ?"]
            params: List[Any] = [tenant_id]

            if scim_group_id:
                where_clauses.append("scim_group_id = ?")
                params.append(scim_group_id)

            if project_id:
                where_clauses.append("project_id = ?")
                params.append(project_id)

            where_sql = " AND ".join(where_clauses)

            cursor.execute(
                f"""
                SELECT * FROM scim_group_project_mappings
                WHERE {where_sql}
                ORDER BY created_at DESC
                """,
                params,
            )
            return [
                {**dict(row), "enabled": bool(row["enabled"])}
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def get_mappings_for_group(self, scim_group_id: str) -> List[Dict[str, Any]]:
        """Get all project mappings for a SCIM group."""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM scim_group_project_mappings
                WHERE scim_group_id = ? AND enabled = 1
                ORDER BY created_at DESC
                """,
                (scim_group_id,),
            )
            return [
                {**dict(row), "enabled": bool(row["enabled"])}
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()


# Global instance
_scim_store: Optional[ScimStore] = None


def get_scim_store() -> ScimStore:
    """Get or create the global ScimStore instance."""
    global _scim_store
    if _scim_store is None:
        _scim_store = ScimStore()
    return _scim_store


def reset_scim_store() -> None:
    """Reset the global ScimStore instance (for testing)."""
    global _scim_store
    _scim_store = None
