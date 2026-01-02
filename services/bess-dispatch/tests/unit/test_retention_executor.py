"""
Unit tests for retention executor (v4.3.0 PR4).

Tests:
- dry_run_retention() preview
- execute_retention() with actual deletions
- Safety limits
- Advisory locks
- Legal hold skipping
"""

import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compliance_store import ComplianceStore
from retention_policy_helper import RetentionPolicy, ResourceCategory
from retention_executor import (
    PurgeResult,
    PurgeStats,
    dry_run_retention,
    execute_retention,
    get_purge_status,
    list_purge_history,
    MAX_DELETIONS_PER_RUN,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def store(temp_db):
    """Create a ComplianceStore with temporary database."""
    return ComplianceStore(db_path=temp_db)


class MockResourceStore:
    """Mock resource store for testing."""

    def __init__(self):
        self.resources: Dict[str, List[Dict[str, Any]]] = {}
        self.deleted: List[tuple] = []

    def add_resource(
        self,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        created_at: datetime,
        project_id: Optional[str] = None,
    ):
        """Add a mock resource."""
        key = f"{tenant_id}:{resource_type}"
        if key not in self.resources:
            self.resources[key] = []
        self.resources[key].append({
            "id": resource_id,
            "tenant_id": tenant_id,
            "resource_type": resource_type,
            "project_id": project_id,
            "created_at": created_at.isoformat(),
        })

    def list_resources(
        self,
        tenant_id: str,
        resource_type: str,
        project_id: Optional[str] = None,
        created_before: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List resources matching criteria."""
        key = f"{tenant_id}:{resource_type}"
        resources = self.resources.get(key, [])

        result = []
        for r in resources:
            # Filter by project
            if project_id and r.get("project_id") != project_id:
                continue

            # Filter by created_before
            if created_before:
                created = datetime.fromisoformat(r["created_at"])
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created >= created_before:
                    continue

            result.append(r)
            if len(result) >= limit:
                break

        return result

    def delete_resource(
        self,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        """Delete a resource."""
        key = f"{tenant_id}:{resource_type}"
        if key in self.resources:
            initial_len = len(self.resources[key])
            self.resources[key] = [
                r for r in self.resources[key]
                if r["id"] != resource_id
            ]
            if len(self.resources[key]) < initial_len:
                self.deleted.append((tenant_id, resource_type, resource_id))
                return True
        return False


class TestPurgeResult:
    """Tests for PurgeResult model."""

    def test_create_result(self):
        """Test creating PurgeResult."""
        result = PurgeResult(
            mode="dry_run",
            tenant_id="t1",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        assert result.mode == "dry_run"
        assert result.success is False
        assert result.total_deleted == 0

    def test_result_to_summary(self):
        """Test converting result to summary."""
        result = PurgeResult(
            mode="execute",
            tenant_id="t1",
            started_at="2024-01-01T00:00:00Z",
            success=True,
            total_deleted=10,
            categories=[
                PurgeStats(category="runs", retention_days=365, deleted=10),
            ],
        )
        summary = result.to_summary()
        assert summary["mode"] == "execute"
        assert summary["total_deleted"] == 10
        assert len(summary["categories"]) == 1


class TestDryRunRetention:
    """Tests for dry_run_retention() function."""

    def test_dry_run_no_resources(self, store):
        """Test dry run with no resources."""
        result = dry_run_retention(store, "tenant-1")

        assert result.mode == "dry_run"
        assert result.success is True
        assert result.total_found == 0
        assert result.total_to_delete == 0

    def test_dry_run_with_resources(self, store):
        """Test dry run with mock resources."""
        resource_store = MockResourceStore()

        # Add some old resources
        old_date = datetime.now(timezone.utc) - timedelta(days=500)
        for i in range(5):
            resource_store.add_resource(
                tenant_id="t1",
                resource_type="runs",
                resource_id=f"run-{i}",
                created_at=old_date,
            )

        # Create policy with 365 day retention
        store.create_retention_policy(
            tenant_id="t1",
            policy_json={"runs_days": 365},
        )

        result = dry_run_retention(
            store,
            tenant_id="t1",
            resource_store=resource_store,
        )

        assert result.success is True
        assert result.total_found >= 5
        assert result.total_to_delete >= 5

    def test_dry_run_respects_holds(self, store):
        """Test dry run respects legal holds."""
        resource_store = MockResourceStore()

        old_date = datetime.now(timezone.utc) - timedelta(days=500)
        resource_store.add_resource(
            tenant_id="t1",
            resource_type="runs",
            resource_id="held-run",
            created_at=old_date,
        )
        resource_store.add_resource(
            tenant_id="t1",
            resource_type="runs",
            resource_id="free-run",
            created_at=old_date,
        )

        # Create legal hold (use "runs" to match resource type)
        store.create_legal_hold(
            tenant_id="t1",
            resource_type="runs",
            reason="Hold",
            created_by_user_id="admin",
            resource_id="held-run",
        )

        store.create_retention_policy(
            tenant_id="t1",
            policy_json={"runs_days": 365},
        )

        result = dry_run_retention(
            store,
            tenant_id="t1",
            resource_store=resource_store,
        )

        assert result.success is True
        # One should be skipped due to hold
        runs_stats = next(
            (c for c in result.categories if c.category == "runs"),
            None,
        )
        assert runs_stats is not None
        assert runs_stats.skipped_held >= 1

    def test_dry_run_indefinite_retention(self, store):
        """Test dry run with indefinite retention."""
        resource_store = MockResourceStore()

        old_date = datetime.now(timezone.utc) - timedelta(days=1000)
        resource_store.add_resource(
            tenant_id="t1",
            resource_type="runs",
            resource_id="old-run",
            created_at=old_date,
        )

        # Create policy with indefinite retention
        store.create_retention_policy(
            tenant_id="t1",
            policy_json={"runs_days": 0},  # 0 = indefinite
        )

        result = dry_run_retention(
            store,
            tenant_id="t1",
            resource_store=resource_store,
        )

        assert result.success is True
        runs_stats = next(
            (c for c in result.categories if c.category == "runs"),
            None,
        )
        assert runs_stats is not None
        assert runs_stats.to_delete == 0  # Nothing to delete


class TestExecuteRetention:
    """Tests for execute_retention() function."""

    def test_execute_deletes_resources(self, store):
        """Test execute actually deletes resources."""
        resource_store = MockResourceStore()

        old_date = datetime.now(timezone.utc) - timedelta(days=500)
        for i in range(3):
            resource_store.add_resource(
                tenant_id="t1",
                resource_type="runs",
                resource_id=f"run-{i}",
                created_at=old_date,
            )

        store.create_retention_policy(
            tenant_id="t1",
            policy_json={"runs_days": 365},
        )

        result = execute_retention(
            store,
            tenant_id="t1",
            resource_store=resource_store,
        )

        assert result.success is True
        assert result.mode == "execute"
        assert result.total_deleted >= 3
        assert len(resource_store.deleted) >= 3

    def test_execute_respects_holds(self, store):
        """Test execute respects legal holds."""
        resource_store = MockResourceStore()

        old_date = datetime.now(timezone.utc) - timedelta(days=500)
        resource_store.add_resource(
            tenant_id="t1",
            resource_type="runs",
            resource_id="held-run",
            created_at=old_date,
        )
        resource_store.add_resource(
            tenant_id="t1",
            resource_type="runs",
            resource_id="free-run",
            created_at=old_date,
        )

        # Create legal hold (use "runs" to match resource type)
        store.create_legal_hold(
            tenant_id="t1",
            resource_type="runs",
            reason="Hold",
            created_by_user_id="admin",
            resource_id="held-run",
        )

        store.create_retention_policy(
            tenant_id="t1",
            policy_json={"runs_days": 365},
        )

        result = execute_retention(
            store,
            tenant_id="t1",
            resource_store=resource_store,
        )

        assert result.success is True
        # Only free-run should be deleted
        deleted_ids = [d[2] for d in resource_store.deleted]
        assert "held-run" not in deleted_ids
        assert result.total_skipped_held >= 1

    def test_execute_respects_max_deletions(self, store):
        """Test execute respects max deletions limit."""
        resource_store = MockResourceStore()

        old_date = datetime.now(timezone.utc) - timedelta(days=500)
        for i in range(100):
            resource_store.add_resource(
                tenant_id="t1",
                resource_type="runs",
                resource_id=f"run-{i}",
                created_at=old_date,
            )

        store.create_retention_policy(
            tenant_id="t1",
            policy_json={"runs_days": 365},
        )

        result = execute_retention(
            store,
            tenant_id="t1",
            resource_store=resource_store,
            max_deletions=10,
        )

        assert result.success is True
        assert result.total_deleted <= 10
        assert result.hit_limit is True

    def test_execute_creates_purge_run_record(self, store):
        """Test execute creates purge run record."""
        resource_store = MockResourceStore()

        store.create_retention_policy(
            tenant_id="t1",
            policy_json={"runs_days": 365},
        )

        execute_retention(
            store,
            tenant_id="t1",
            resource_store=resource_store,
        )

        # Check purge run was created
        runs = list_purge_history(store, "t1")
        assert len(runs) == 1
        assert runs[0]["mode"] == "execute"
        assert runs[0]["finished_at"] is not None

    def test_execute_on_delete_callback(self, store):
        """Test on_delete callback is called."""
        resource_store = MockResourceStore()

        old_date = datetime.now(timezone.utc) - timedelta(days=500)
        resource_store.add_resource(
            tenant_id="t1",
            resource_type="runs",
            resource_id="run-1",
            created_at=old_date,
        )

        store.create_retention_policy(
            tenant_id="t1",
            policy_json={"runs_days": 365},
        )

        callback_calls = []

        def on_delete(tenant_id, resource_type, resource_id):
            callback_calls.append((tenant_id, resource_type, resource_id))

        execute_retention(
            store,
            tenant_id="t1",
            resource_store=resource_store,
            on_delete=on_delete,
        )

        assert len(callback_calls) >= 1

    def test_execute_no_resource_store(self, store):
        """Test execute with no resource store."""
        store.create_retention_policy(
            tenant_id="t1",
            policy_json={"runs_days": 365},
        )

        result = execute_retention(
            store,
            tenant_id="t1",
            resource_store=None,
        )

        assert result.success is True
        assert result.total_deleted == 0


class TestPurgeHistory:
    """Tests for purge history functions."""

    def test_list_purge_history(self, store):
        """Test listing purge history."""
        # Create some purge runs
        store.create_retention_policy(
            tenant_id="t1",
            policy_json={"runs_days": 365},
        )

        execute_retention(store, tenant_id="t1")
        execute_retention(store, tenant_id="t1")

        runs = list_purge_history(store, "t1")
        assert len(runs) == 2

    def test_get_purge_status(self, store):
        """Test getting purge status."""
        store.create_retention_policy(
            tenant_id="t1",
            policy_json={"runs_days": 365},
        )

        execute_retention(store, tenant_id="t1")

        runs = list_purge_history(store, "t1")
        assert len(runs) == 1

        status = get_purge_status(store, runs[0]["id"])
        assert status is not None
        assert status["mode"] == "execute"


class TestSpecificCategories:
    """Tests for processing specific categories."""

    def test_dry_run_specific_categories(self, store):
        """Test dry run with specific categories."""
        resource_store = MockResourceStore()

        old_date = datetime.now(timezone.utc) - timedelta(days=500)
        resource_store.add_resource(
            tenant_id="t1",
            resource_type="runs",
            resource_id="run-1",
            created_at=old_date,
        )
        resource_store.add_resource(
            tenant_id="t1",
            resource_type="jobs",
            resource_id="job-1",
            created_at=old_date,
        )

        store.create_retention_policy(
            tenant_id="t1",
            policy_json={"runs_days": 365, "jobs_days": 90},
        )

        # Only process runs
        result = dry_run_retention(
            store,
            tenant_id="t1",
            resource_store=resource_store,
            categories=[ResourceCategory.RUNS],
        )

        assert result.success is True
        assert len(result.categories) == 1
        assert result.categories[0].category == "runs"

    def test_execute_specific_categories(self, store):
        """Test execute with specific categories."""
        resource_store = MockResourceStore()

        old_date = datetime.now(timezone.utc) - timedelta(days=500)
        resource_store.add_resource(
            tenant_id="t1",
            resource_type="runs",
            resource_id="run-1",
            created_at=old_date,
        )
        resource_store.add_resource(
            tenant_id="t1",
            resource_type="jobs",
            resource_id="job-1",
            created_at=old_date,
        )

        store.create_retention_policy(
            tenant_id="t1",
            policy_json={"runs_days": 365, "jobs_days": 90},
        )

        # Only process runs
        result = execute_retention(
            store,
            tenant_id="t1",
            resource_store=resource_store,
            categories=[ResourceCategory.RUNS],
        )

        assert result.success is True
        # Only run should be deleted
        deleted_types = [d[1] for d in resource_store.deleted]
        assert "runs" in deleted_types
        assert "jobs" not in deleted_types
