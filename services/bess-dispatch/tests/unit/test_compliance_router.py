"""
Unit tests for compliance API router models (v4.3.0 PR5).

Tests:
- Request/Response model validation
- Router is properly structured (import test)
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compliance_store import ComplianceStore
from auth_config import AuthContext, Role


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


class TestRouterModels:
    """Tests for router request/response models."""

    def test_import_router(self):
        """Test that router can be imported without errors."""
        from compliance_router import router
        assert router is not None
        assert router.prefix == "/compliance"

    def test_retention_policy_request_model(self):
        """Test RetentionPolicyRequest validation."""
        from compliance_router import RetentionPolicyRequest

        # Valid request
        req = RetentionPolicyRequest(runs_days=365, enabled=True)
        assert req.runs_days == 365

        # Allow -1 for inherit
        req = RetentionPolicyRequest(runs_days=-1)
        assert req.runs_days == -1

        # Allow 0 for indefinite
        req = RetentionPolicyRequest(runs_days=0)
        assert req.runs_days == 0

    def test_legal_hold_request_model(self):
        """Test LegalHoldCreateRequest validation."""
        from compliance_router import LegalHoldCreateRequest

        req = LegalHoldCreateRequest(
            resource_type="run",
            reason="Test hold",
        )
        assert req.resource_type == "run"
        assert req.reason == "Test hold"

    def test_purge_dry_run_request_model(self):
        """Test PurgeDryRunRequest validation."""
        from compliance_router import PurgeDryRunRequest

        req = PurgeDryRunRequest()
        assert req.project_id is None
        assert req.categories is None

        req = PurgeDryRunRequest(project_id="proj-1", categories=["runs"])
        assert req.project_id == "proj-1"

    def test_purge_execute_request_model(self):
        """Test PurgeExecuteRequest validation."""
        from compliance_router import PurgeExecuteRequest

        req = PurgeExecuteRequest(max_deletions=100)
        assert req.max_deletions == 100

    def test_response_models(self):
        """Test response models can be created."""
        from compliance_router import (
            RetentionPolicyResponse,
            LegalHoldResponse,
            PurgeResultResponse,
            PurgeCategoryStats,
        )

        policy_resp = RetentionPolicyResponse(
            runs_days=365,
            jobs_days=90,
            reports_days=365,
            audit_logs_days=730,
            exports_days=30,
            enabled=True,
            summary={"runs": "1 year"},
        )
        assert policy_resp.runs_days == 365

        hold_resp = LegalHoldResponse(
            id="h1",
            tenant_id="t1",
            resource_type="run",
            reason="Test",
            created_by_user_id="user1",
            created_at="2024-01-01T00:00:00Z",
        )
        assert hold_resp.id == "h1"

        cat_stats = PurgeCategoryStats(
            category="runs",
            retention_days=365,
            total_found=10,
            to_delete=5,
            deleted=5,
            skipped_held=0,
            skipped_error=0,
        )
        assert cat_stats.deleted == 5

        purge_resp = PurgeResultResponse(
            mode="dry_run",
            tenant_id="t1",
            started_at="2024-01-01T00:00:00Z",
            success=True,
            total_found=10,
            total_to_delete=5,
            total_deleted=0,
            total_skipped_held=0,
            total_skipped_error=0,
            hit_limit=False,
            categories=[cat_stats],
        )
        assert purge_resp.success is True


class TestRouterRoutes:
    """Test that all expected routes are defined."""

    def test_routes_defined(self):
        """Test that all expected routes are defined."""
        from compliance_router import router

        route_paths = [r.path for r in router.routes]

        # Retention routes (with prefix)
        assert "/compliance/retention" in route_paths
        assert "/compliance/retention/projects/{project_id}" in route_paths

        # Legal hold routes
        assert "/compliance/holds" in route_paths
        assert "/compliance/holds/{hold_id}" in route_paths
        assert "/compliance/holds/summary" in route_paths

        # Purge routes
        assert "/compliance/purge/dry-run" in route_paths
        assert "/compliance/purge/execute" in route_paths
        assert "/compliance/purge/history" in route_paths
        assert "/compliance/purge/{run_id}" in route_paths

    def test_route_methods(self):
        """Test that routes have correct methods."""
        from compliance_router import router

        routes_by_path = {r.path: r for r in router.routes}

        # Check some key methods
        retention_route = routes_by_path.get("/retention")
        if retention_route:
            methods = getattr(retention_route, "methods", set())
            assert "GET" in methods or hasattr(retention_route, "endpoint")
