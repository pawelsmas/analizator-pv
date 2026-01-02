"""
Unit tests for Projects RBAC Auth scenario pack (v3.7.0 PR5).

Tests the pack definition and scenario structure.
"""

import yaml
from pathlib import Path

import pytest


PACKS_DIR = Path(__file__).parent.parent.parent / "docs" / "scenarios" / "packs"


class TestProjectsRbacAuthPack:
    """Tests for projects_rbac_auth.yml pack."""

    @pytest.fixture
    def pack_content(self):
        """Load pack YAML content."""
        path = PACKS_DIR / "projects_rbac_auth.yml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_pack_file_exists(self):
        """Pack file should exist."""
        path = PACKS_DIR / "projects_rbac_auth.yml"
        assert path.exists(), "projects_rbac_auth.yml should exist"

    def test_pack_has_name(self, pack_content):
        """Pack should have name field."""
        assert "name" in pack_content
        assert pack_content["name"] == "projects_rbac_auth"

    def test_pack_has_description(self, pack_content):
        """Pack should have description field."""
        assert "description" in pack_content
        assert "Projects" in pack_content["description"]
        assert "RBAC" in pack_content["description"]

    def test_pack_has_scenarios(self, pack_content):
        """Pack should have scenarios list."""
        assert "scenarios" in pack_content
        assert isinstance(pack_content["scenarios"], list)
        assert len(pack_content["scenarios"]) > 0

    def test_scenarios_count(self, pack_content):
        """Pack should have expected number of scenarios."""
        scenarios = pack_content["scenarios"]
        assert len(scenarios) >= 20, "Should have at least 20 scenarios"

    # Project CRUD scenarios
    def test_has_project_create_scenario(self, pack_content):
        """Pack should have project creation scenario."""
        assert "projects_create_default_project" in pack_content["scenarios"]

    def test_has_project_list_scenario(self, pack_content):
        """Pack should have project listing scenario."""
        assert "projects_list_user_projects" in pack_content["scenarios"]

    def test_has_project_update_scenario(self, pack_content):
        """Pack should have project update scenario."""
        assert "projects_update_project_settings" in pack_content["scenarios"]

    def test_has_project_archive_scenario(self, pack_content):
        """Pack should have project archive scenario."""
        assert "projects_archive_project" in pack_content["scenarios"]

    # Membership scenarios
    def test_has_add_member_owner_scenario(self, pack_content):
        """Pack should have add owner member scenario."""
        assert "projects_add_member_owner" in pack_content["scenarios"]

    def test_has_add_member_editor_scenario(self, pack_content):
        """Pack should have add editor member scenario."""
        assert "projects_add_member_editor" in pack_content["scenarios"]

    def test_has_add_member_viewer_scenario(self, pack_content):
        """Pack should have add viewer member scenario."""
        assert "projects_add_member_viewer" in pack_content["scenarios"]

    def test_has_update_member_role_scenario(self, pack_content):
        """Pack should have update member role scenario."""
        assert "projects_update_member_role" in pack_content["scenarios"]

    def test_has_remove_member_scenario(self, pack_content):
        """Pack should have remove member scenario."""
        assert "projects_remove_member" in pack_content["scenarios"]

    def test_has_owner_cannot_be_removed_scenario(self, pack_content):
        """Pack should have owner protection scenario."""
        assert "projects_owner_cannot_be_removed" in pack_content["scenarios"]

    # Scoped access scenarios
    def test_has_runs_scoped_scenario(self, pack_content):
        """Pack should have runs scoped by project scenario."""
        assert "projects_runs_scoped_by_project" in pack_content["scenarios"]

    def test_has_jobs_scoped_scenario(self, pack_content):
        """Pack should have jobs scoped by project scenario."""
        assert "projects_jobs_scoped_by_project" in pack_content["scenarios"]

    def test_has_reports_scoped_scenario(self, pack_content):
        """Pack should have reports scoped by project scenario."""
        assert "projects_reports_scoped_by_project" in pack_content["scenarios"]

    def test_has_cross_project_denied_scenario(self, pack_content):
        """Pack should have cross-project access denied scenario."""
        assert "projects_cross_project_access_denied" in pack_content["scenarios"]

    # Role-based permission scenarios
    def test_has_owner_full_access_scenario(self, pack_content):
        """Pack should have owner full access scenario."""
        assert "projects_owner_full_access" in pack_content["scenarios"]

    def test_has_editor_write_access_scenario(self, pack_content):
        """Pack should have editor write access scenario."""
        assert "projects_editor_write_access" in pack_content["scenarios"]

    def test_has_viewer_read_only_scenario(self, pack_content):
        """Pack should have viewer read-only scenario."""
        assert "projects_viewer_read_only" in pack_content["scenarios"]

    def test_has_viewer_cannot_create_runs_scenario(self, pack_content):
        """Pack should have viewer restriction scenario."""
        assert "projects_viewer_cannot_create_runs" in pack_content["scenarios"]

    def test_has_editor_cannot_manage_members_scenario(self, pack_content):
        """Pack should have editor member restriction scenario."""
        assert "projects_editor_cannot_manage_members" in pack_content["scenarios"]

    # Share policy scenarios
    def test_has_share_allow_public_scenario(self, pack_content):
        """Pack should have share allow public scenario."""
        assert "projects_share_policy_allow_public" in pack_content["scenarios"]

    def test_has_share_deny_public_scenario(self, pack_content):
        """Pack should have share deny public scenario."""
        assert "projects_share_policy_deny_public" in pack_content["scenarios"]

    def test_has_share_max_expiry_enforced_scenario(self, pack_content):
        """Pack should have share max expiry enforced scenario."""
        assert "projects_share_max_expiry_enforced" in pack_content["scenarios"]

    def test_has_share_max_expiry_clamped_scenario(self, pack_content):
        """Pack should have share max expiry clamped scenario."""
        assert "projects_share_max_expiry_clamped" in pack_content["scenarios"]

    def test_has_share_audit_events_logged_scenario(self, pack_content):
        """Pack should have share audit events logged scenario."""
        assert "projects_share_audit_events_logged" in pack_content["scenarios"]


class TestAuthDocumentation:
    """Tests for AUTH.md documentation updates."""

    @pytest.fixture
    def auth_doc(self):
        """Load AUTH.md content."""
        path = Path(__file__).parent.parent.parent / "docs" / "AUTH.md"
        return path.read_text(encoding="utf-8")

    def test_version_updated(self, auth_doc):
        """AUTH.md should reference v3.7.0."""
        assert "v3.7.0" in auth_doc

    def test_projects_section_exists(self, auth_doc):
        """AUTH.md should have Projects section."""
        assert "## Projects & Per-Project RBAC" in auth_doc

    def test_project_endpoints_documented(self, auth_doc):
        """AUTH.md should document project endpoints."""
        assert "/projects" in auth_doc
        assert "/members" in auth_doc

    def test_project_roles_documented(self, auth_doc):
        """AUTH.md should document project roles."""
        assert "owner > editor > viewer" in auth_doc

    def test_share_policies_documented(self, auth_doc):
        """AUTH.md should document share policies."""
        assert "allow_public_shares" in auth_doc
        assert "share_max_expiry_hours" in auth_doc

    def test_migration_documented(self, auth_doc):
        """AUTH.md should document migration from v3.6.x."""
        assert "Migration from v3.6.x" in auth_doc

    def test_audit_events_documented(self, auth_doc):
        """AUTH.md should document project audit events."""
        assert "project_created" in auth_doc
        assert "share_create_denied" in auth_doc

    def test_frontend_integration_documented(self, auth_doc):
        """AUTH.md should document frontend integration."""
        assert "Project Selector" in auth_doc
        assert "Projects Admin" in auth_doc


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
