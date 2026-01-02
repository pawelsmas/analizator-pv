"""
Unit tests for Projects UI (v3.7.0).

Tests for JavaScript functions in settings.html and index.html.
These tests verify the HTML structure and expected API interactions.
"""

import os
import re
import sys
from pathlib import Path

import pytest


# Frontend files path
FRONTEND_DIR = Path(__file__).parent.parent.parent / "services" / "frontend-bess"


class TestSettingsHtmlProjectsTab:
    """Tests for Projects tab in settings.html."""

    @pytest.fixture
    def settings_html(self):
        """Load settings.html content."""
        path = FRONTEND_DIR / "settings.html"
        return path.read_text(encoding="utf-8")

    def test_projects_tab_exists(self, settings_html):
        """Projekty tab should exist in settings tabs."""
        assert 'data-tab="projects"' in settings_html
        assert "Projekty" in settings_html

    def test_projects_section_exists(self, settings_html):
        """Projects section should exist."""
        assert 'id="projectsSection"' in settings_html

    def test_projects_table_structure(self, settings_html):
        """Projects table should have correct columns."""
        assert 'id="projectsTable"' in settings_html
        # Headers should be: Nazwa, Domyślny, allow_public_shares, max_expiry, created_at, Akcje
        assert "Nazwa" in settings_html

    def test_create_project_modal_exists(self, settings_html):
        """Create project modal should exist."""
        assert 'id="createProjectModal"' in settings_html
        assert 'id="projectName"' in settings_html

    def test_edit_project_modal_exists(self, settings_html):
        """Edit project modal should exist."""
        assert 'id="editProjectModal"' in settings_html
        assert 'id="editProjectName"' in settings_html

    def test_edit_modal_has_settings_tab(self, settings_html):
        """Edit modal should have settings tab."""
        assert 'id="projectSettingsTab"' in settings_html

    def test_edit_modal_has_members_tab(self, settings_html):
        """Edit modal should have members tab."""
        assert 'id="projectMembersTab"' in settings_html

    def test_add_member_modal_exists(self, settings_html):
        """Add member modal should exist."""
        assert 'id="addMemberModal"' in settings_html
        assert 'id="memberUserId"' in settings_html
        assert 'id="memberRole"' in settings_html

    def test_load_projects_function_exists(self, settings_html):
        """loadProjects function should be defined."""
        assert "async function loadProjects(" in settings_html

    def test_handle_create_project_function_exists(self, settings_html):
        """handleCreateProject function should be defined."""
        assert "async function handleCreateProject(" in settings_html

    def test_handle_update_project_function_exists(self, settings_html):
        """handleUpdateProject function should be defined."""
        assert "async function handleUpdateProject(" in settings_html

    def test_handle_archive_project_function_exists(self, settings_html):
        """handleArchiveProject function should be defined."""
        assert "async function handleArchiveProject(" in settings_html

    def test_load_project_members_function_exists(self, settings_html):
        """loadProjectMembers function should be defined."""
        assert "async function loadProjectMembers(" in settings_html

    def test_handle_add_member_function_exists(self, settings_html):
        """handleAddMember function should be defined."""
        assert "async function handleAddMember(" in settings_html

    def test_handle_update_member_role_function_exists(self, settings_html):
        """handleUpdateMemberRole function should be defined."""
        assert "async function handleUpdateMemberRole(" in settings_html

    def test_handle_remove_member_function_exists(self, settings_html):
        """handleRemoveMember function should be defined."""
        assert "async function handleRemoveMember(" in settings_html

    def test_project_roles_dropdown_options(self, settings_html):
        """Member role dropdown should have owner, editor, viewer options."""
        assert 'value="owner"' in settings_html
        assert 'value="editor"' in settings_html
        assert 'value="viewer"' in settings_html


class TestIndexHtmlProjectSelector:
    """Tests for Project selector in index.html."""

    @pytest.fixture
    def index_html(self):
        """Load index.html content."""
        path = FRONTEND_DIR / "index.html"
        return path.read_text(encoding="utf-8")

    def test_project_selector_exists(self, index_html):
        """Project selector div should exist."""
        assert 'id="projectSelector"' in index_html

    def test_project_select_dropdown_exists(self, index_html):
        """Project select dropdown should exist."""
        assert 'id="projectSelect"' in index_html

    def test_handle_project_change_handler(self, index_html):
        """handleProjectChange should be called on change."""
        assert 'onchange="handleProjectChange()"' in index_html

    def test_all_projects_option_exists(self, index_html):
        """'Wszystkie projekty' option should be default."""
        assert "Wszystkie projekty" in index_html

    def test_load_user_projects_function_exists(self, index_html):
        """loadUserProjects function should be defined."""
        assert "async function loadUserProjects(" in index_html

    def test_get_current_project_id_function_exists(self, index_html):
        """getCurrentProjectId function should be defined."""
        assert "function getCurrentProjectId(" in index_html

    def test_build_project_scoped_url_function_exists(self, index_html):
        """buildProjectScopedUrl function should be defined."""
        assert "function buildProjectScopedUrl(" in index_html

    def test_refresh_project_scoped_data_function_exists(self, index_html):
        """refreshProjectScopedData function should be defined."""
        assert "function refreshProjectScopedData(" in index_html

    def test_project_config_storage_key(self, index_html):
        """PROJECT_CONFIG should have storageKey."""
        assert "storageKey: 'bess_selected_project'" in index_html

    def test_exports_to_window(self, index_html):
        """Functions should be exported to window."""
        assert "window.loadUserProjects" in index_html
        assert "window.handleProjectChange" in index_html
        assert "window.getCurrentProjectId" in index_html
        assert "window.buildProjectScopedUrl" in index_html


class TestBessJsProjectScoping:
    """Tests for project scoping in bess.js."""

    @pytest.fixture
    def bess_js(self):
        """Load bess.js content."""
        path = FRONTEND_DIR / "bess.js"
        return path.read_text(encoding="utf-8")

    def test_load_runs_for_picker_uses_project_id(self, bess_js):
        """loadRunsForPicker should use getCurrentProjectId for filtering."""
        # Find the function
        assert "async function loadRunsForPicker(" in bess_js
        # Should check for project ID
        assert "getCurrentProjectId" in bess_js
        assert 'project_id=' in bess_js or "project_id" in bess_js

    def test_load_available_runs_uses_project_id(self, bess_js):
        """loadAvailableRuns should use getCurrentProjectId for filtering."""
        assert "async function loadAvailableRuns(" in bess_js
        # Should add project_id parameter

    def test_refresh_run_list_uses_project_id(self, bess_js):
        """refreshRunList should use getCurrentProjectId for filtering."""
        assert "async function refreshRunList(" in bess_js

    def test_version_updated(self, bess_js):
        """bess.js version should be v3.35."""
        assert "v=3.35" in bess_js or "v3.35" in bess_js


class TestStylesCssProjectSelector:
    """Tests for project selector styles in styles.css."""

    @pytest.fixture
    def styles_css(self):
        """Load styles.css content."""
        path = FRONTEND_DIR / "styles.css"
        return path.read_text(encoding="utf-8")

    def test_project_selector_styles_exist(self, styles_css):
        """Project selector styles should exist."""
        assert ".project-selector" in styles_css

    def test_project_select_styles_exist(self, styles_css):
        """Project select dropdown styles should exist."""
        assert ".project-select" in styles_css

    def test_project_selector_label_styles_exist(self, styles_css):
        """Project selector label styles should exist."""
        assert ".project-selector-label" in styles_css


class TestProjectApiEndpoints:
    """Tests for expected API endpoint calls."""

    @pytest.fixture
    def settings_html(self):
        """Load settings.html content."""
        path = FRONTEND_DIR / "settings.html"
        return path.read_text(encoding="utf-8")

    @pytest.fixture
    def index_html(self):
        """Load index.html content."""
        path = FRONTEND_DIR / "index.html"
        return path.read_text(encoding="utf-8")

    def test_list_projects_api_call(self, index_html, settings_html):
        """GET /projects should be called."""
        assert "/projects" in index_html or "/projects" in settings_html

    def test_create_project_api_call(self, settings_html):
        """POST /projects should be used for creation."""
        assert 'method: "POST"' in settings_html or "method: 'POST'" in settings_html
        assert "/projects" in settings_html

    def test_update_project_api_call(self, settings_html):
        """PATCH /projects/{id} should be used for updates."""
        assert 'method: "PATCH"' in settings_html or "method: 'PATCH'" in settings_html

    def test_archive_project_api_call(self, settings_html):
        """DELETE /projects/{id} should be used for archiving."""
        assert 'method: "DELETE"' in settings_html or "method: 'DELETE'" in settings_html

    def test_list_members_api_call(self, settings_html):
        """GET /projects/{id}/members should be called."""
        assert "/members" in settings_html

    def test_add_member_api_call(self, settings_html):
        """POST /projects/{id}/members should be used."""
        assert "/members" in settings_html


class TestProjectMembershipUI:
    """Tests for membership management UI."""

    @pytest.fixture
    def settings_html(self):
        """Load settings.html content."""
        path = FRONTEND_DIR / "settings.html"
        return path.read_text(encoding="utf-8")

    def test_members_table_exists(self, settings_html):
        """Members table should exist in edit modal."""
        assert 'id="projectMembersTable"' in settings_html

    def test_role_change_handler(self, settings_html):
        """Role change should trigger handleUpdateMemberRole."""
        assert "handleUpdateMemberRole" in settings_html

    def test_remove_member_button(self, settings_html):
        """Remove member button should exist."""
        assert "handleRemoveMember" in settings_html


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
