"""
Quota Store - Database tables for plans, tenant settings, project quotas, and usage tracking.

Provides:
- Plans: predefined limit configurations (free, pro, enterprise)
- TenantSettings: billing status and plan assignment per tenant
- ProjectQuotas: per-project quota overrides
- UsageDaily: daily usage counters and bytes tracking

Version: 4.0.0
"""

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import Any, Dict, List, Optional


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

QUOTA_STORE_PATH = os.getenv("QUOTA_STORE_PATH", "/data/quotas.sqlite")


# -----------------------------------------------------------------------------
# Default Plans
# -----------------------------------------------------------------------------

DEFAULT_PLANS = {
    "free": {
        "name": "Free",
        "limits": {
            "jobs_per_day": 10,
            "reports_per_day": 5,
            "shares_total": 10,
            "storage_mb": 100,
            "projects_total": 3,
        },
        "is_default": True,
    },
    "pro": {
        "name": "Pro",
        "limits": {
            "jobs_per_day": 100,
            "reports_per_day": 50,
            "shares_total": 100,
            "storage_mb": 1000,
            "projects_total": 20,
        },
        "is_default": False,
    },
    "enterprise": {
        "name": "Enterprise",
        "limits": {
            "jobs_per_day": 1000,
            "reports_per_day": 500,
            "shares_total": 1000,
            "storage_mb": 10000,
            "projects_total": 100,
        },
        "is_default": False,
    },
}


# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------

@dataclass
class Plan:
    """Plan configuration with limits."""
    id: str
    name: str
    limits_json: Dict[str, Any]
    created_at: str
    is_default: bool = False

    def get_limit(self, limit_name: str) -> Optional[int]:
        """Get a specific limit value."""
        return self.limits_json.get(limit_name)


@dataclass
class TenantSettings:
    """Tenant-level settings including plan and billing status."""
    tenant_id: str
    plan_id: str
    billing_status: str  # active, suspended, grace, cancelled
    grace_mode_until: Optional[str]
    created_at: str
    updated_at: str


@dataclass
class ProjectQuota:
    """Per-project quota overrides."""
    tenant_id: str
    project_id: str
    overrides_json: Dict[str, Any]
    created_at: str
    updated_at: str

    def get_override(self, limit_name: str) -> Optional[int]:
        """Get a specific override value."""
        return self.overrides_json.get(limit_name)


@dataclass
class UsageDaily:
    """Daily usage counters and bytes for a tenant/project."""
    tenant_id: str
    project_id: str
    date: str  # YYYY-MM-DD
    counters_json: Dict[str, int] = field(default_factory=dict)
    bytes_json: Dict[str, int] = field(default_factory=dict)
    created_at: str = ""

    def get_counter(self, counter_name: str) -> int:
        """Get a specific counter value (default 0)."""
        return self.counters_json.get(counter_name, 0)

    def get_bytes(self, bytes_name: str) -> int:
        """Get a specific bytes value (default 0)."""
        return self.bytes_json.get(bytes_name, 0)


# -----------------------------------------------------------------------------
# QuotaStore Class
# -----------------------------------------------------------------------------

class QuotaStore:
    """SQLite-backed store for quotas, plans, and usage tracking."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize QuotaStore with SQLite database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path or QUOTA_STORE_PATH
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize database schema with all quota tables."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = self._get_conn()
        try:
            # Plans table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    limits_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_default INTEGER NOT NULL DEFAULT 0
                )
            """)

            # Tenant settings table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tenant_settings (
                    tenant_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    billing_status TEXT NOT NULL DEFAULT 'active',
                    grace_mode_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (plan_id) REFERENCES plans(id)
                )
            """)

            # Project quotas table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_quotas (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    overrides_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id)
                )
            """)

            # Usage daily table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_daily (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    counters_json TEXT NOT NULL DEFAULT '{}',
                    bytes_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, date)
                )
            """)

            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tenant_settings_plan_id ON tenant_settings(plan_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_project_quotas_tenant_id ON project_quotas(tenant_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_daily_tenant_id ON usage_daily(tenant_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_daily_date ON usage_daily(date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_daily_tenant_project ON usage_daily(tenant_id, project_id)")

            conn.commit()

            # Seed default plans if not exist
            self._seed_default_plans(conn)

        finally:
            conn.close()

    def _seed_default_plans(self, conn: sqlite3.Connection) -> None:
        """Seed default plans if they don't exist."""
        now = datetime.now(timezone.utc).isoformat()
        for plan_id, plan_data in DEFAULT_PLANS.items():
            cursor = conn.execute("SELECT id FROM plans WHERE id = ?", (plan_id,))
            if cursor.fetchone() is None:
                conn.execute(
                    """
                    INSERT INTO plans (id, name, limits_json, created_at, is_default)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        plan_id,
                        plan_data["name"],
                        json.dumps(plan_data["limits"]),
                        now,
                        1 if plan_data["is_default"] else 0,
                    ),
                )
        conn.commit()

    # -------------------------------------------------------------------------
    # Plans CRUD
    # -------------------------------------------------------------------------

    def list_plans(self) -> List[Plan]:
        """List all available plans."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT * FROM plans ORDER BY is_default DESC, name")
            return [
                Plan(
                    id=row["id"],
                    name=row["name"],
                    limits_json=json.loads(row["limits_json"]),
                    created_at=row["created_at"],
                    is_default=bool(row["is_default"]),
                )
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        """Get a plan by ID."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return Plan(
                id=row["id"],
                name=row["name"],
                limits_json=json.loads(row["limits_json"]),
                created_at=row["created_at"],
                is_default=bool(row["is_default"]),
            )
        finally:
            conn.close()

    def get_default_plan(self) -> Optional[Plan]:
        """Get the default plan."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT * FROM plans WHERE is_default = 1 LIMIT 1")
            row = cursor.fetchone()
            if row is None:
                return None
            return Plan(
                id=row["id"],
                name=row["name"],
                limits_json=json.loads(row["limits_json"]),
                created_at=row["created_at"],
                is_default=True,
            )
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Tenant Settings CRUD
    # -------------------------------------------------------------------------

    def get_tenant_settings(self, tenant_id: str) -> Optional[TenantSettings]:
        """Get tenant settings."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM tenant_settings WHERE tenant_id = ?",
                (tenant_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return TenantSettings(
                tenant_id=row["tenant_id"],
                plan_id=row["plan_id"],
                billing_status=row["billing_status"],
                grace_mode_until=row["grace_mode_until"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        finally:
            conn.close()

    def upsert_tenant_settings(
        self,
        tenant_id: str,
        plan_id: Optional[str] = None,
        billing_status: Optional[str] = None,
        grace_mode_until: Optional[str] = None,
    ) -> TenantSettings:
        """Create or update tenant settings."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            existing = self.get_tenant_settings(tenant_id)
            if existing is None:
                # Create new
                default_plan = self.get_default_plan()
                actual_plan_id = plan_id or (default_plan.id if default_plan else "free")
                actual_billing_status = billing_status or "active"
                conn.execute(
                    """
                    INSERT INTO tenant_settings
                    (tenant_id, plan_id, billing_status, grace_mode_until, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (tenant_id, actual_plan_id, actual_billing_status, grace_mode_until, now, now),
                )
            else:
                # Update existing
                updates = []
                params = []
                if plan_id is not None:
                    updates.append("plan_id = ?")
                    params.append(plan_id)
                if billing_status is not None:
                    updates.append("billing_status = ?")
                    params.append(billing_status)
                if grace_mode_until is not None:
                    updates.append("grace_mode_until = ?")
                    params.append(grace_mode_until)
                if updates:
                    updates.append("updated_at = ?")
                    params.append(now)
                    params.append(tenant_id)
                    conn.execute(
                        f"UPDATE tenant_settings SET {', '.join(updates)} WHERE tenant_id = ?",
                        params,
                    )
            conn.commit()
            return self.get_tenant_settings(tenant_id)
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Project Quotas CRUD
    # -------------------------------------------------------------------------

    def get_project_quota(self, tenant_id: str, project_id: str) -> Optional[ProjectQuota]:
        """Get project quota overrides."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM project_quotas WHERE tenant_id = ? AND project_id = ?",
                (tenant_id, project_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return ProjectQuota(
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                overrides_json=json.loads(row["overrides_json"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        finally:
            conn.close()

    def upsert_project_quota(
        self,
        tenant_id: str,
        project_id: str,
        overrides: Dict[str, Any],
    ) -> ProjectQuota:
        """Create or update project quota overrides."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            existing = self.get_project_quota(tenant_id, project_id)
            if existing is None:
                # Create new
                conn.execute(
                    """
                    INSERT INTO project_quotas
                    (tenant_id, project_id, overrides_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (tenant_id, project_id, json.dumps(overrides), now, now),
                )
            else:
                # Merge overrides
                merged = {**existing.overrides_json, **overrides}
                conn.execute(
                    """
                    UPDATE project_quotas
                    SET overrides_json = ?, updated_at = ?
                    WHERE tenant_id = ? AND project_id = ?
                    """,
                    (json.dumps(merged), now, tenant_id, project_id),
                )
            conn.commit()
            return self.get_project_quota(tenant_id, project_id)
        finally:
            conn.close()

    def list_project_quotas(self, tenant_id: str) -> List[ProjectQuota]:
        """List all project quotas for a tenant."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM project_quotas WHERE tenant_id = ? ORDER BY project_id",
                (tenant_id,),
            )
            return [
                ProjectQuota(
                    tenant_id=row["tenant_id"],
                    project_id=row["project_id"],
                    overrides_json=json.loads(row["overrides_json"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Usage Daily CRUD
    # -------------------------------------------------------------------------

    def get_usage_daily(
        self,
        tenant_id: str,
        project_id: str,
        usage_date: str,
    ) -> Optional[UsageDaily]:
        """Get usage for a specific date."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM usage_daily
                WHERE tenant_id = ? AND project_id = ? AND date = ?
                """,
                (tenant_id, project_id, usage_date),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return UsageDaily(
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                date=row["date"],
                counters_json=json.loads(row["counters_json"]),
                bytes_json=json.loads(row["bytes_json"]),
                created_at=row["created_at"],
            )
        finally:
            conn.close()

    def upsert_usage_daily(
        self,
        tenant_id: str,
        project_id: str,
        usage_date: str,
        counter_increments: Optional[Dict[str, int]] = None,
        bytes_increments: Optional[Dict[str, int]] = None,
    ) -> UsageDaily:
        """
        Upsert usage counters/bytes with atomic increment.

        This is idempotent in the sense that it atomically increments
        existing values rather than overwriting them.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            existing = self.get_usage_daily(tenant_id, project_id, usage_date)
            if existing is None:
                # Create new record
                new_counters = counter_increments or {}
                new_bytes = bytes_increments or {}
                conn.execute(
                    """
                    INSERT INTO usage_daily
                    (tenant_id, project_id, date, counters_json, bytes_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        project_id,
                        usage_date,
                        json.dumps(new_counters),
                        json.dumps(new_bytes),
                        now,
                    ),
                )
            else:
                # Increment existing values
                new_counters = existing.counters_json.copy()
                new_bytes = existing.bytes_json.copy()

                if counter_increments:
                    for key, val in counter_increments.items():
                        new_counters[key] = new_counters.get(key, 0) + val

                if bytes_increments:
                    for key, val in bytes_increments.items():
                        new_bytes[key] = new_bytes.get(key, 0) + val

                conn.execute(
                    """
                    UPDATE usage_daily
                    SET counters_json = ?, bytes_json = ?
                    WHERE tenant_id = ? AND project_id = ? AND date = ?
                    """,
                    (
                        json.dumps(new_counters),
                        json.dumps(new_bytes),
                        tenant_id,
                        project_id,
                        usage_date,
                    ),
                )
            conn.commit()
            return self.get_usage_daily(tenant_id, project_id, usage_date)
        finally:
            conn.close()

    def list_usage_daily(
        self,
        tenant_id: str,
        project_id: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> List[UsageDaily]:
        """List usage records with optional filters."""
        conn = self._get_conn()
        try:
            query = "SELECT * FROM usage_daily WHERE tenant_id = ?"
            params: List[Any] = [tenant_id]

            if project_id is not None:
                query += " AND project_id = ?"
                params.append(project_id)

            if from_date is not None:
                query += " AND date >= ?"
                params.append(from_date)

            if to_date is not None:
                query += " AND date <= ?"
                params.append(to_date)

            query += " ORDER BY date DESC, project_id"

            cursor = conn.execute(query, params)
            return [
                UsageDaily(
                    tenant_id=row["tenant_id"],
                    project_id=row["project_id"],
                    date=row["date"],
                    counters_json=json.loads(row["counters_json"]),
                    bytes_json=json.loads(row["bytes_json"]),
                    created_at=row["created_at"],
                )
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def aggregate_usage_daily(
        self,
        tenant_id: str,
        project_id: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate usage over a date range."""
        records = self.list_usage_daily(tenant_id, project_id, from_date, to_date)

        total_counters: Dict[str, int] = {}
        total_bytes: Dict[str, int] = {}

        for record in records:
            for key, val in record.counters_json.items():
                total_counters[key] = total_counters.get(key, 0) + val
            for key, val in record.bytes_json.items():
                total_bytes[key] = total_bytes.get(key, 0) + val

        return {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "from_date": from_date,
            "to_date": to_date,
            "days_count": len(set(r.date for r in records)),
            "counters": total_counters,
            "bytes": total_bytes,
        }

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def get_today_date(self) -> str:
        """Get today's date in YYYY-MM-DD format (UTC)."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def tables_exist(self) -> Dict[str, bool]:
        """Check which tables exist in the database."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            existing = {row["name"] for row in cursor.fetchall()}
            return {
                "plans": "plans" in existing,
                "tenant_settings": "tenant_settings" in existing,
                "project_quotas": "project_quotas" in existing,
                "usage_daily": "usage_daily" in existing,
            }
        finally:
            conn.close()
