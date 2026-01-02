"""
Unit tests for billing UI JavaScript.

Tests verify:
- billing.html exists with correct structure
- billing.js exports expected functions
- QUOTA_LABELS contains required labels
- UI elements have correct IDs
"""

import os
import re
import pytest


# -----------------------------------------------------------------------------
# File paths
# -----------------------------------------------------------------------------

FRONTEND_PATH = os.path.join(
    os.path.dirname(__file__),
    '..',
    '..',
    'services',
    'frontend-bess'
)


# -----------------------------------------------------------------------------
# HTML Structure tests
# -----------------------------------------------------------------------------

class TestBillingHtmlStructure:
    """Tests for billing.html structure."""

    @pytest.fixture
    def html_content(self):
        """Load billing.html content."""
        html_path = os.path.join(FRONTEND_PATH, 'billing.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_billing_html_exists(self):
        """billing.html should exist."""
        html_path = os.path.join(FRONTEND_PATH, 'billing.html')
        assert os.path.exists(html_path)

    def test_has_doctype(self, html_content):
        """Should have DOCTYPE declaration."""
        assert '<!DOCTYPE html>' in html_content

    def test_has_plan_badge_element(self, html_content):
        """Should have plan badge element."""
        assert 'id="planBadge"' in html_content

    def test_has_plan_name_element(self, html_content):
        """Should have plan name element."""
        assert 'id="planName"' in html_content

    def test_has_usage_grid_element(self, html_content):
        """Should have usage grid element."""
        assert 'id="usageGrid"' in html_content

    def test_has_reset_info_element(self, html_content):
        """Should have reset info element."""
        assert 'id="resetInfo"' in html_content

    def test_has_history_table_element(self, html_content):
        """Should have history table element."""
        assert 'id="historyTable"' in html_content

    def test_has_error_message_element(self, html_content):
        """Should have error message element."""
        assert 'id="errorMessage"' in html_content

    def test_has_whoami_badge(self, html_content):
        """Should have whoami badge element."""
        assert 'id="whoamiBadge"' in html_content

    def test_includes_auth_js(self, html_content):
        """Should include auth.js script."""
        assert 'src="auth.js"' in html_content

    def test_includes_billing_js(self, html_content):
        """Should include billing.js script."""
        assert 'src="billing.js"' in html_content

    def test_has_export_button(self, html_content):
        """Should have CSV export button."""
        assert 'exportCsv()' in html_content

    def test_has_days_selector(self, html_content):
        """Should have days selector buttons."""
        assert 'loadHistory(7)' in html_content
        assert 'loadHistory(14)' in html_content
        assert 'loadHistory(30)' in html_content

    def test_has_back_link(self, html_content):
        """Should have back link to index."""
        assert 'href="index.html"' in html_content

    def test_has_usage_card_styles(self, html_content):
        """Should have usage card CSS styles."""
        assert '.usage-card' in html_content

    def test_has_progress_bar_styles(self, html_content):
        """Should have progress bar CSS styles."""
        assert '.usage-progress' in html_content
        assert '.usage-progress-bar' in html_content

    def test_has_warning_danger_states(self, html_content):
        """Should have warning and danger progress bar states."""
        assert '.usage-progress-bar.warning' in html_content
        assert '.usage-progress-bar.danger' in html_content


# -----------------------------------------------------------------------------
# JavaScript Structure tests
# -----------------------------------------------------------------------------

class TestBillingJsStructure:
    """Tests for billing.js structure."""

    @pytest.fixture
    def js_content(self):
        """Load billing.js content."""
        js_path = os.path.join(FRONTEND_PATH, 'billing.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_billing_js_exists(self):
        """billing.js should exist."""
        js_path = os.path.join(FRONTEND_PATH, 'billing.js')
        assert os.path.exists(js_path)

    def test_has_version_comment(self, js_content):
        """Should have version comment."""
        assert 'v4.0.0' in js_content

    def test_has_api_base_constant(self, js_content):
        """Should have API_BASE constant."""
        assert "API_BASE = '/api/bess-dispatch'" in js_content

    def test_has_quota_labels(self, js_content):
        """Should have QUOTA_LABELS constant."""
        assert 'QUOTA_LABELS' in js_content
        assert 'jobs_per_day' in js_content
        assert 'reports_per_day' in js_content
        assert 'storage_mb' in js_content

    def test_has_load_usage_function(self, js_content):
        """Should have loadUsage function."""
        assert 'async function loadUsage()' in js_content

    def test_has_load_history_function(self, js_content):
        """Should have loadHistory function."""
        assert 'async function loadHistory(days)' in js_content

    def test_has_export_csv_function(self, js_content):
        """Should have exportCsv function."""
        assert 'async function exportCsv()' in js_content

    def test_has_build_usage_card_function(self, js_content):
        """Should have buildUsageCard function."""
        assert 'function buildUsageCard(quota)' in js_content

    def test_has_format_date_function(self, js_content):
        """Should have formatDate function."""
        assert 'function formatDate(dateStr)' in js_content

    def test_has_get_auth_token_function(self, js_content):
        """Should have getAuthToken function."""
        assert 'function getAuthToken()' in js_content

    def test_has_check_auth_function(self, js_content):
        """Should have checkAuth function."""
        assert 'async function checkAuth()' in js_content

    def test_has_logout_function(self, js_content):
        """Should have logout function."""
        assert 'function logout()' in js_content

    def test_has_dom_content_loaded_listener(self, js_content):
        """Should have DOMContentLoaded event listener."""
        assert "document.addEventListener('DOMContentLoaded'" in js_content

    def test_fetches_usage_endpoint(self, js_content):
        """Should fetch from /usage endpoint."""
        assert '`${API_BASE}/usage`' in js_content

    def test_fetches_history_endpoint(self, js_content):
        """Should fetch from /usage/daily endpoint."""
        assert '`${API_BASE}/usage/daily?days=${days}`' in js_content

    def test_fetches_export_endpoint(self, js_content):
        """Should fetch from /usage/export/csv endpoint."""
        assert '`${API_BASE}/usage/export/csv?days=${currentDays}`' in js_content

    def test_handles_unlimited_quota(self, js_content):
        """Should handle unlimited quotas."""
        assert 'UNLIMITED' in js_content
        assert 'isUnlimited' in js_content

    def test_handles_progress_bar_states(self, js_content):
        """Should handle progress bar warning/danger states."""
        assert '>= 90' in js_content  # danger threshold
        assert '>= 70' in js_content  # warning threshold

    def test_exports_for_testing(self, js_content):
        """Should export functions for testing."""
        assert 'module.exports' in js_content


# -----------------------------------------------------------------------------
# Integration tests
# -----------------------------------------------------------------------------

class TestBillingIntegration:
    """Integration tests for billing UI."""

    def test_all_quota_types_have_labels(self):
        """All quota types should have Polish labels."""
        js_path = os.path.join(FRONTEND_PATH, 'billing.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()

        expected_quotas = [
            'jobs_per_day',
            'reports_per_day',
            'shares_total',
            'storage_mb',
            'projects_total'
        ]

        for quota in expected_quotas:
            assert quota in content, f"Missing label for {quota}"

    def test_html_has_all_required_ids(self):
        """HTML should have all required element IDs."""
        html_path = os.path.join(FRONTEND_PATH, 'billing.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        required_ids = [
            'planBadge',
            'planName',
            'usageGrid',
            'resetInfo',
            'resetText',
            'historyTable',
            'errorMessage',
            'whoamiBadge'
        ]

        for id_name in required_ids:
            assert f'id="{id_name}"' in content, f"Missing element ID: {id_name}"

    def test_js_uses_consistent_api_paths(self):
        """JavaScript should use consistent API paths."""
        js_path = os.path.join(FRONTEND_PATH, 'billing.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # All API calls should use API_BASE
        assert content.count('`${API_BASE}/') >= 3

    def test_css_is_inline(self):
        """CSS should be inline in billing.html."""
        html_path = os.path.join(FRONTEND_PATH, 'billing.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        assert '<style>' in content
        assert '</style>' in content
