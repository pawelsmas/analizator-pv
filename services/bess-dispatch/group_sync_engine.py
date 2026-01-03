"""
Group Sync Engine (v4.4.0 PR6).

Synchronizes SCIM group memberships to project memberships.

When a SCIM group is mapped to a project:
- Adding user to SCIM group → adds project membership (source='scim')
- Removing user from SCIM group → removes project membership (if source='scim')

Manual memberships (source='manual') are never modified by sync.
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from auth_config import AUTH_DB_PATH
from scim_store import ScimStore, MembershipSource


class GroupSyncEngine:
    """Engine for syncing SCIM groups to project memberships."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize GroupSyncEngine."""
        self.db_path = db_path or AUTH_DB_PATH
        self.scim_store = ScimStore(db_path)

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def sync_group(self, scim_group_id: str) -> Dict[str, Any]:
        """
        Sync a single SCIM group to all its mapped projects.

        Returns:
            Dict with sync results:
            {
                "group_id": str,
                "mappings_processed": int,
                "members_added": int,
                "members_removed": int,
                "errors": List[str]
            }
        """
        result = {
            "group_id": scim_group_id,
            "mappings_processed": 0,
            "members_added": 0,
            "members_removed": 0,
            "errors": []
        }

        # Get group
        group = self.scim_store.get_scim_group(scim_group_id)
        if not group:
            result["errors"].append(f"Group {scim_group_id} not found")
            return result

        # Get enabled mappings for this group
        mappings = self.scim_store.get_mappings_for_group(scim_group_id)

        # Get current SCIM group members
        scim_members = self.scim_store.get_group_members(scim_group_id)
        scim_user_ids = {m["id"] for m in scim_members}

        for mapping in mappings:
            if not mapping["enabled"]:
                continue

            try:
                added, removed = self._sync_mapping(
                    tenant_id=group["tenant_id"],
                    scim_group_id=scim_group_id,
                    project_id=mapping["project_id"],
                    role=mapping["role"],
                    scim_user_ids=scim_user_ids
                )
                result["mappings_processed"] += 1
                result["members_added"] += added
                result["members_removed"] += removed
            except Exception as e:
                result["errors"].append(
                    f"Error syncing to project {mapping['project_id']}: {str(e)}"
                )

        return result

    def _sync_mapping(
        self,
        tenant_id: str,
        scim_group_id: str,
        project_id: str,
        role: str,
        scim_user_ids: set
    ) -> Tuple[int, int]:
        """
        Sync a single group-project mapping.

        Returns:
            Tuple of (members_added, members_removed)
        """
        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # Get current SCIM-managed memberships for this group+project
            cursor.execute(
                """
                SELECT user_id FROM project_memberships
                WHERE tenant_id = ? AND project_id = ? AND scim_group_id = ?
                AND source = 'scim'
                """,
                (tenant_id, project_id, scim_group_id)
            )
            current_members = {row["user_id"] for row in cursor.fetchall()}

            # Calculate diff
            # Note: scim_user_ids are SCIM user IDs, we need to map to portal user IDs
            # For now, we assume SCIM user ID == portal user ID (simplified)
            # In a real implementation, you'd look up the mapping
            to_add = scim_user_ids - current_members
            to_remove = current_members - scim_user_ids

            now = datetime.now(timezone.utc).isoformat()

            # Remove old memberships
            if to_remove:
                cursor.executemany(
                    """
                    DELETE FROM project_memberships
                    WHERE tenant_id = ? AND project_id = ? AND user_id = ?
                    AND scim_group_id = ? AND source = 'scim'
                    """,
                    [(tenant_id, project_id, uid, scim_group_id) for uid in to_remove]
                )

            # Add new memberships
            for user_id in to_add:
                membership_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO project_memberships
                    (id, tenant_id, project_id, user_id, role, source, scim_group_id, created_at)
                    VALUES (?, ?, ?, ?, ?, 'scim', ?, ?)
                    """,
                    (membership_id, tenant_id, project_id, user_id, role, scim_group_id, now)
                )

            conn.commit()
            return len(to_add), len(to_remove)
        finally:
            conn.close()

    def sync_all_groups(self, tenant_id: str) -> Dict[str, Any]:
        """
        Sync all SCIM groups for a tenant.

        Returns:
            Dict with aggregate sync results
        """
        result = {
            "tenant_id": tenant_id,
            "groups_processed": 0,
            "mappings_processed": 0,
            "members_added": 0,
            "members_removed": 0,
            "errors": []
        }

        # Get all groups for tenant
        groups = self.scim_store.list_scim_groups(tenant_id)

        for group in groups:
            group_result = self.sync_group(group["id"])
            result["groups_processed"] += 1
            result["mappings_processed"] += group_result["mappings_processed"]
            result["members_added"] += group_result["members_added"]
            result["members_removed"] += group_result["members_removed"]
            result["errors"].extend(group_result["errors"])

        return result

    def sync_user(self, scim_user_id: str) -> Dict[str, Any]:
        """
        Sync all group memberships for a specific user.

        Useful when user is added/removed from multiple groups.

        Returns:
            Dict with sync results for the user
        """
        result = {
            "user_id": scim_user_id,
            "groups_synced": 0,
            "memberships_added": 0,
            "memberships_removed": 0,
            "errors": []
        }

        # Get user
        user = self.scim_store.get_scim_user(scim_user_id)
        if not user:
            result["errors"].append(f"User {scim_user_id} not found")
            return result

        # Get all groups this user belongs to
        groups = self.scim_store.get_user_groups(scim_user_id)

        for group in groups:
            group_result = self.sync_group(group["id"])
            result["groups_synced"] += 1
            result["memberships_added"] += group_result["members_added"]
            result["memberships_removed"] += group_result["members_removed"]
            result["errors"].extend(group_result["errors"])

        return result

    def get_scim_memberships(
        self,
        tenant_id: str,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all SCIM-managed memberships with optional filters.

        Returns list of memberships with source='scim'.
        """
        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            where_clauses = ["source = 'scim'", "tenant_id = ?"]
            params: List[Any] = [tenant_id]

            if project_id:
                where_clauses.append("project_id = ?")
                params.append(project_id)

            if user_id:
                where_clauses.append("user_id = ?")
                params.append(user_id)

            where_sql = " AND ".join(where_clauses)

            cursor.execute(
                f"""
                SELECT * FROM project_memberships
                WHERE {where_sql}
                ORDER BY created_at DESC
                """,
                params
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def revoke_scim_memberships(
        self,
        tenant_id: str,
        scim_group_id: str,
        project_id: Optional[str] = None
    ) -> int:
        """
        Revoke all SCIM memberships for a group (and optionally a specific project).

        Called when a mapping is disabled or deleted.

        Returns:
            Number of memberships removed
        """
        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            if project_id:
                cursor.execute(
                    """
                    DELETE FROM project_memberships
                    WHERE tenant_id = ? AND scim_group_id = ? AND project_id = ?
                    AND source = 'scim'
                    """,
                    (tenant_id, scim_group_id, project_id)
                )
            else:
                cursor.execute(
                    """
                    DELETE FROM project_memberships
                    WHERE tenant_id = ? AND scim_group_id = ? AND source = 'scim'
                    """,
                    (tenant_id, scim_group_id)
                )

            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def get_sync_status(self, tenant_id: str) -> Dict[str, Any]:
        """
        Get sync status summary for a tenant.

        Returns:
            Dict with counts and status
        """
        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # Count SCIM groups
            cursor.execute(
                "SELECT COUNT(*) FROM scim_groups WHERE tenant_id = ?",
                (tenant_id,)
            )
            groups_count = cursor.fetchone()[0]

            # Count enabled mappings
            cursor.execute(
                """
                SELECT COUNT(*) FROM scim_group_project_mappings
                WHERE tenant_id = ? AND enabled = 1
                """,
                (tenant_id,)
            )
            mappings_count = cursor.fetchone()[0]

            # Count SCIM-managed memberships
            cursor.execute(
                """
                SELECT COUNT(*) FROM project_memberships
                WHERE tenant_id = ? AND source = 'scim'
                """,
                (tenant_id,)
            )
            scim_memberships = cursor.fetchone()[0]

            # Count manual memberships
            cursor.execute(
                """
                SELECT COUNT(*) FROM project_memberships
                WHERE tenant_id = ? AND source = 'manual'
                """,
                (tenant_id,)
            )
            manual_memberships = cursor.fetchone()[0]

            return {
                "tenant_id": tenant_id,
                "scim_groups": groups_count,
                "enabled_mappings": mappings_count,
                "scim_memberships": scim_memberships,
                "manual_memberships": manual_memberships
            }
        finally:
            conn.close()


# Global instance
_sync_engine: Optional[GroupSyncEngine] = None


def get_sync_engine() -> GroupSyncEngine:
    """Get or create the global GroupSyncEngine instance."""
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = GroupSyncEngine()
    return _sync_engine


def reset_sync_engine() -> None:
    """Reset the global GroupSyncEngine instance (for testing)."""
    global _sync_engine
    _sync_engine = None
