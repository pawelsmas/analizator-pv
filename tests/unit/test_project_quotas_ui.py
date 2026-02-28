"""
Unit tests for project quotas UI.

Tests verify:
- project-quotas.html exists with correct structure
- project-quotas.js exports expected functions
- UI elements have correct IDs
"""

import os
import pytest


FRONTEND_PATH = os.path.join(
    os.path.dirname(__file__),
    '..',
    '..',
    'services',
    'frontend-bess'
)


class TestProjectQuotasHtml:
    """Tests for project-quotas.html structure."""

    @pytest.fixture
    def html_content(self):
        """Load HTML content."""
        html_path = os.path.join(FRONTEND_PATH, 'project-quotas.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_file_exists(self):
        """File should exist."""
        html_path = os.path.join(FRONTEND_PATH, 'project-quotas.html')
        assert os.path.exists(html_path)

    def test_has_doctype(self, html_content):
        """Should have DOCTYPE."""
        assert '<!DOCTYPE html>' in html_content

    def test_has_project_selector(self, html_content):
        """Should have project selector."""
        assert 'id="projectSelect"' in html_content

    def test_has_quotas_form(self, html_content):
        """Should have quotas form."""
        assert 'id="quotasForm"' in html_content

    def test_has_override_inputs(self, html_content):
        """Should have override inputs."""
        assert 'id="overrideJobs"' in html_content
        assert 'id="overrideReports"' in html_content
        assert 'id="overrideShares"' in html_content
        assert 'id="overrideStorage"' in html_content

    def test_has_plan_limit_displays(self, html_content):
        """Should have plan limit displays."""
        assert 'id="planLimitJobs"' in html_content
        assert 'id="planLimitReports"' in html_content
        assert 'id="planLimitShares"' in html_content
        assert 'id="planLimitStorage"' in html_content

    def test_has_usage_grid(self, html_content):
        """Should have usage grid."""
        assert 'id="usageGrid"' in html_content

    def test_has_save_button(self, html_content):
        """Should have save button."""
        assert 'id="saveBtn"' in html_content

    def test_has_override_badge(self, html_content):
        """Should have override badge."""
        assert 'id="overrideBadge"' in html_content

    def test_has_messages(self, html_content):
        """Should have success/error message elements."""
        assert 'id="successMessage"' in html_content
        assert 'id="errorMessage"' in html_content

    def test_has_admin_notice(self, html_content):
        """Should have admin notice."""
        assert 'id="adminNotice"' in html_content

    def test_includes_auth_js(self, html_content):
        """Should include auth.js."""
        assert 'src="auth.js"' in html_content

    def test_includes_project_quotas_js(self, html_content):
        """Should include project-quotas.js."""
        assert 'src="project-quotas.js"' in html_content

    def test_has_back_link(self, html_content):
        """Should have back link to billing."""
        assert 'href="billing.html"' in html_content

    def test_has_polish_labels(self, html_content):
        """Should have Polish labels."""
        assert 'Kwoty Projektu' in html_content or 'KWOTY PROJEKTU' in html_content
        assert 'Zapisz' in html_content
        assert 'Anuluj' in html_content


class TestProjectQuotasJs:
    """Tests for project-quotas.js structure."""

    @pytest.fixture
    def js_content(self):
        """Load JS content."""
        js_path = os.path.join(FRONTEND_PATH, 'project-quotas.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_file_exists(self):
        """File should exist."""
        js_path = os.path.join(FRONTEND_PATH, 'project-quotas.js')
        assert os.path.exists(js_path)

    def test_has_version_comment(self, js_content):
        """Should have version comment."""
        assert 'v4.0.0' in js_content

    def test_has_api_base(self, js_content):
        """Should have API_BASE."""
        assert "API_BASE = '/api/bess-dispatch'" in js_content

    def test_has_load_project_list_function(self, js_content):
        """Should have loadProjectList function."""
        assert 'async function loadProjectList()' in js_content

    def test_has_load_project_quotas_function(self, js_content):
        """Should have loadProjectQuotas function."""
        assert 'async function loadProjectQuotas()' in js_content

    def test_has_save_quotas_function(self, js_content):
        """Should have saveQuotas function."""
        assert 'async function saveQuotas(' in js_content

    def test_has_reset_form_function(self, js_content):
        """Should have resetForm function."""
        assert 'function resetForm()' in js_content

    def test_has_format_limit_function(self, js_content):
        """Should have formatLimit function."""
        assert 'function formatLimit(' in js_content

    def test_has_get_quota_label_function(self, js_content):
        """Should have getQuotaLabel function."""
        assert 'function getQuotaLabel(' in js_content

    def test_has_check_auth_function(self, js_content):
        """Should have checkAuth function."""
        assert 'async function checkAuth()' in js_content

    def test_fetches_project_quotas_endpoint(self, js_content):
        """Should fetch project quotas endpoint."""
        assert '/projects/${projectId}/quotas' in js_content

    def test_fetches_project_usage_endpoint(self, js_content):
        """Should fetch project usage endpoint."""
        assert '/projects/${projectId}/usage' in js_content

    def test_sends_patch_request(self, js_content):
        """Should send PATCH request for saving."""
        assert "method: 'PATCH'" in js_content

    def test_handles_admin_check(self, js_content):
        """Should handle admin role check."""
        assert 'isAdmin' in js_content
        assert "role === 'admin'" in js_content

    def test_has_quota_labels_mapping(self, js_content):
        """Should have quota labels mapping."""
        assert 'jobs_per_day' in js_content
        assert 'reports_per_day' in js_content
        assert 'storage_mb' in js_content

    def test_exports_for_testing(self, js_content):
        """Should export functions for testing."""
        assert 'module.exports' in js_content


class TestProjectQuotasIntegration:
    """Integration tests."""

    def test_html_has_all_required_ids(self):
        """HTML should have all required element IDs."""
        html_path = os.path.join(FRONTEND_PATH, 'project-quotas.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        required_ids = [
            'projectSelect',
            'quotasForm',
            'quotasContent',
            'overrideJobs',
            'overrideReports',
            'overrideShares',
            'overrideStorage',
            'planLimitJobs',
            'planLimitReports',
            'planLimitShares',
            'planLimitStorage',
            'usageGrid',
            'saveBtn',
            'overrideBadge',
            'successMessage',
            'errorMessage',
            'adminNotice',
            'actionsBar',
            'whoamiBadge'
        ]

        for id_name in required_ids:
            assert f'id="{id_name}"' in content, f"Missing element ID: {id_name}"

    def test_js_handles_all_quota_types(self):
        """JS should handle all quota types."""
        js_path = os.path.join(FRONTEND_PATH, 'project-quotas.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()

        quota_types = [
            'jobs_per_day',
            'reports_per_day',
            'shares_total',
            'storage_mb',
            'projects_total'
        ]

        for quota in quota_types:
            assert quota in content, f"Missing quota type handling: {quota}"
