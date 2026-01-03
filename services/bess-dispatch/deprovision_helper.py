"""
Deprovision Helper (v4.4.0 PR8).

Handles user deprovisioning semantics when SCIM user is disabled/deleted.

When a user is disabled/deleted via SCIM:
1. Revoke all active sessions
2. Revoke all API keys
3. Revoke all SCIM-managed project memberships
4. Mark user as deprovisioned (active=False)

Manual resources (manual project memberships) are preserved.
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from auth_config import AUTH_DB_PATH


class DeprovisionHelper:
    """Helper for deprovisioning SCIM users."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize DeprovisionHelper."""
        self.db_path = db_path or AUTH_DB_PATH

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def deprovision_user(self, scim_user_id: str, hard_delete: bool = False) -> Dict[str, Any]:
        """
        Deprovision a SCIM user.

        This is called when a user is disabled or deleted via SCIM.

        Args:
            scim_user_id: The SCIM user ID to deprovision
            hard_delete: If True, delete the user entirely. If False, just disable.

        Returns:
            Dict with deprovisioning results:
            {
                "user_id": str,
                "sessions_revoked": int,
                "api_keys_revoked": int,
                "scim_memberships_revoked": int,
                "hard_deleted": bool
            }
        """
        result = {
            "user_id": scim_user_id,
            "sessions_revoked": 0,
            "api_keys_revoked": 0,
            "scim_memberships_revoked": 0,
            "hard_deleted": hard_delete
        }

        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # 1. Get the portal user_id from SCIM identity
            cursor.execute(
                """
                SELECT user_id FROM scim_identities
                WHERE scim_user_id = ?
                """,
                (scim_user_id,)
            )
            row = cursor.fetchone()
            if not row:
                # No linked portal user, nothing to deprovision
                return result

            portal_user_id = row["user_id"]

            # 2. Revoke all active sessions
            cursor.execute(
                """
                UPDATE user_sessions
                SET revoked_at = ?, revoked_reason = 'scim_deprovision'
                WHERE user_id = ? AND revoked_at IS NULL
                """,
                (datetime.now(timezone.utc).isoformat(), portal_user_id)
            )
            result["sessions_revoked"] = cursor.rowcount

            # 3. Revoke all API keys
            cursor.execute(
                """
                UPDATE api_keys
                SET revoked_at = ?, revoked_reason = 'scim_deprovision'
                WHERE user_id = ? AND revoked_at IS NULL
                """,
                (datetime.now(timezone.utc).isoformat(), portal_user_id)
            )
            result["api_keys_revoked"] = cursor.rowcount

            # 4. Revoke SCIM-managed project memberships
            cursor.execute(
                """
                DELETE FROM project_memberships
                WHERE user_id = ? AND source = 'scim'
                """,
                (portal_user_id,)
            )
            result["scim_memberships_revoked"] = cursor.rowcount

            # 5. Mark user as deprovisioned or delete
            if hard_delete:
                # Delete the SCIM identity
                cursor.execute(
                    "DELETE FROM scim_identities WHERE scim_user_id = ?",
                    (scim_user_id,)
                )
                # Optionally delete the user itself (depends on policy)
                # For now, we just mark as inactive
                cursor.execute(
                    """
                    UPDATE users SET active = 0, updated_at = ?
                    WHERE id = ?
                    """,
                    (datetime.now(timezone.utc).isoformat(), portal_user_id)
                )
            else:
                # Just mark as inactive
                cursor.execute(
                    """
                    UPDATE users SET active = 0, updated_at = ?
                    WHERE id = ?
                    """,
                    (datetime.now(timezone.utc).isoformat(), portal_user_id)
                )

            conn.commit()
            return result
        finally:
            conn.close()

    def reprovision_user(self, scim_user_id: str) -> Dict[str, Any]:
        """
        Re-enable a previously deprovisioned user.

        Called when a SCIM user is re-enabled (active=true).

        Args:
            scim_user_id: The SCIM user ID to reprovision

        Returns:
            Dict with reprovisioning results:
            {
                "user_id": str,
                "reactivated": bool
            }
        """
        result = {
            "user_id": scim_user_id,
            "reactivated": False
        }

        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # Get the portal user_id from SCIM identity
            cursor.execute(
                """
                SELECT user_id FROM scim_identities
                WHERE scim_user_id = ?
                """,
                (scim_user_id,)
            )
            row = cursor.fetchone()
            if not row:
                return result

            portal_user_id = row["user_id"]

            # Re-enable the user
            cursor.execute(
                """
                UPDATE users SET active = 1, updated_at = ?
                WHERE id = ? AND active = 0
                """,
                (datetime.now(timezone.utc).isoformat(), portal_user_id)
            )
            result["reactivated"] = cursor.rowcount > 0

            conn.commit()
            return result
        finally:
            conn.close()

    def get_user_resources(self, scim_user_id: str) -> Dict[str, Any]:
        """
        Get a summary of user resources that would be affected by deprovisioning.

        Useful for audit/preview before deprovisioning.

        Args:
            scim_user_id: The SCIM user ID

        Returns:
            Dict with resource counts
        """
        result = {
            "user_id": scim_user_id,
            "portal_user_id": None,
            "active_sessions": 0,
            "active_api_keys": 0,
            "scim_memberships": 0,
            "manual_memberships": 0
        }

        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # Get the portal user_id from SCIM identity
            cursor.execute(
                """
                SELECT user_id FROM scim_identities
                WHERE scim_user_id = ?
                """,
                (scim_user_id,)
            )
            row = cursor.fetchone()
            if not row:
                return result

            portal_user_id = row["user_id"]
            result["portal_user_id"] = portal_user_id

            # Count active sessions
            cursor.execute(
                """
                SELECT COUNT(*) FROM user_sessions
                WHERE user_id = ? AND revoked_at IS NULL
                """,
                (portal_user_id,)
            )
            result["active_sessions"] = cursor.fetchone()[0]

            # Count active API keys
            cursor.execute(
                """
                SELECT COUNT(*) FROM api_keys
                WHERE user_id = ? AND revoked_at IS NULL
                """,
                (portal_user_id,)
            )
            result["active_api_keys"] = cursor.fetchone()[0]

            # Count SCIM memberships
            cursor.execute(
                """
                SELECT COUNT(*) FROM project_memberships
                WHERE user_id = ? AND source = 'scim'
                """,
                (portal_user_id,)
            )
            result["scim_memberships"] = cursor.fetchone()[0]

            # Count manual memberships
            cursor.execute(
                """
                SELECT COUNT(*) FROM project_memberships
                WHERE user_id = ? AND source = 'manual'
                """,
                (portal_user_id,)
            )
            result["manual_memberships"] = cursor.fetchone()[0]

            return result
        finally:
            conn.close()

    def revoke_all_sessions(self, portal_user_id: str, reason: str = "admin_action") -> int:
        """
        Revoke all active sessions for a user.

        Args:
            portal_user_id: The portal user ID
            reason: Reason for revocation

        Returns:
            Number of sessions revoked
        """
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE user_sessions
                SET revoked_at = ?, revoked_reason = ?
                WHERE user_id = ? AND revoked_at IS NULL
                """,
                (datetime.now(timezone.utc).isoformat(), reason, portal_user_id)
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def revoke_all_api_keys(self, portal_user_id: str, reason: str = "admin_action") -> int:
        """
        Revoke all active API keys for a user.

        Args:
            portal_user_id: The portal user ID
            reason: Reason for revocation

        Returns:
            Number of API keys revoked
        """
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE api_keys
                SET revoked_at = ?, revoked_reason = ?
                WHERE user_id = ? AND revoked_at IS NULL
                """,
                (datetime.now(timezone.utc).isoformat(), reason, portal_user_id)
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()


# Global instance
_deprovision_helper: Optional[DeprovisionHelper] = None


def get_deprovision_helper() -> DeprovisionHelper:
    """Get or create the global DeprovisionHelper instance."""
    global _deprovision_helper
    if _deprovision_helper is None:
        _deprovision_helper = DeprovisionHelper()
    return _deprovision_helper


def reset_deprovision_helper() -> None:
    """Reset the global DeprovisionHelper instance (for testing)."""
    global _deprovision_helper
    _deprovision_helper = None
