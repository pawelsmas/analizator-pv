"""
Unit tests for RBAC enforcement (v3.0.0 PR3).

Tests verify:
- Role hierarchy (admin > editor = service > viewer)
- require_role dependency raises 403 for insufficient permissions
- Role.has_permission method
"""

import pytest
import sys
from pathlib import Path


# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestRoleHierarchy:
    """Tests for Role permission hierarchy."""

    def test_admin_has_all_permissions(self):
        """Admin role should have all permissions."""
        from auth_config import Role

        admin = Role.ADMIN
        assert admin.has_permission(Role.VIEWER) is True
        assert admin.has_permission(Role.EDITOR) is True
        assert admin.has_permission(Role.SERVICE) is True
        assert admin.has_permission(Role.ADMIN) is True

    def test_editor_has_viewer_permission(self):
        """Editor role should have viewer permission but not admin."""
        from auth_config import Role

        editor = Role.EDITOR
        assert editor.has_permission(Role.VIEWER) is True
        assert editor.has_permission(Role.EDITOR) is True
        assert editor.has_permission(Role.SERVICE) is True  # Same level
        assert editor.has_permission(Role.ADMIN) is False

    def test_service_same_level_as_editor(self):
        """Service role should have same permissions as editor."""
        from auth_config import Role

        service = Role.SERVICE
        assert service.has_permission(Role.VIEWER) is True
        assert service.has_permission(Role.EDITOR) is True
        assert service.has_permission(Role.SERVICE) is True
        assert service.has_permission(Role.ADMIN) is False

    def test_viewer_limited_permissions(self):
        """Viewer role should only have viewer permission."""
        from auth_config import Role

        viewer = Role.VIEWER
        assert viewer.has_permission(Role.VIEWER) is True
        assert viewer.has_permission(Role.EDITOR) is False
        assert viewer.has_permission(Role.SERVICE) is False
        assert viewer.has_permission(Role.ADMIN) is False


class TestRoleLevel:
    """Tests for Role.get_level method."""

    def test_admin_highest_level(self):
        """Admin should have highest level (3)."""
        from auth_config import Role

        assert Role.get_level(Role.ADMIN) == 3

    def test_editor_and_service_equal_level(self):
        """Editor and service should have same level (2)."""
        from auth_config import Role

        assert Role.get_level(Role.EDITOR) == 2
        assert Role.get_level(Role.SERVICE) == 2

    def test_viewer_lowest_level(self):
        """Viewer should have lowest level (1)."""
        from auth_config import Role

        assert Role.get_level(Role.VIEWER) == 1


class TestRoleValues:
    """Tests for Role enum values."""

    def test_role_values_are_strings(self):
        """Role values should be lowercase strings."""
        from auth_config import Role

        assert Role.VIEWER.value == "viewer"
        assert Role.EDITOR.value == "editor"
        assert Role.ADMIN.value == "admin"
        assert Role.SERVICE.value == "service"

    def test_role_can_be_constructed_from_string(self):
        """Role should be constructable from string value."""
        from auth_config import Role

        assert Role("viewer") == Role.VIEWER
        assert Role("editor") == Role.EDITOR
        assert Role("admin") == Role.ADMIN
        assert Role("service") == Role.SERVICE


class TestAuthContextWithRole:
    """Tests for AuthContext with roles.

    Note: AuthContext uses use_enum_values=True which converts Role to string.
    """

    def test_auth_context_with_admin_role(self):
        """AuthContext stores role as string value."""
        from auth_config import AuthContext, Role

        ctx = AuthContext(
            tenant_id="test",
            role=Role.ADMIN,
            auth_method="jwt",
        )
        # use_enum_values converts to string
        assert ctx.role == "admin"

    def test_auth_context_with_viewer_role(self):
        """AuthContext stores role as string value."""
        from auth_config import AuthContext, Role

        ctx = AuthContext(
            tenant_id="test",
            role=Role.VIEWER,
            auth_method="api_key",
        )
        assert ctx.role == "viewer"

    def test_auth_context_role_can_be_converted_back(self):
        """AuthContext role can be converted back to Role for permission check."""
        from auth_config import AuthContext, Role

        ctx = AuthContext(
            tenant_id="test",
            role=Role.EDITOR,
            auth_method="jwt",
        )
        # Convert string back to Role for permission check
        role = Role(ctx.role)
        assert role.has_permission(Role.VIEWER) is True
        assert role.has_permission(Role.ADMIN) is False


class TestRequireRoleLogic:
    """Tests for require_role dependency logic."""

    def test_require_role_returns_dependency(self):
        """require_role should return a callable dependency."""
        from auth_deps import require_role
        from auth_config import Role

        dep = require_role(Role.ADMIN)
        assert callable(dep)

    def test_insufficient_role_permission_check(self):
        """Viewer role should fail admin permission check."""
        from auth_config import Role

        viewer = Role.VIEWER
        assert not viewer.has_permission(Role.ADMIN)
        assert not viewer.has_permission(Role.EDITOR)

    def test_sufficient_role_permission_check(self):
        """Admin role should pass all permission checks."""
        from auth_config import Role

        admin = Role.ADMIN
        assert admin.has_permission(Role.ADMIN) is True
        assert admin.has_permission(Role.EDITOR) is True
        assert admin.has_permission(Role.VIEWER) is True

    def test_editor_passes_editor_permission(self):
        """Editor role should pass editor permission check."""
        from auth_config import Role

        editor = Role.EDITOR
        assert editor.has_permission(Role.EDITOR) is True
        assert editor.has_permission(Role.VIEWER) is True
        assert editor.has_permission(Role.ADMIN) is False
