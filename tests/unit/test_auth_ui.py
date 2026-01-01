"""
Unit tests for frontend auth UI (v3.0.0 PR5).

Tests verify:
- auth.js module structure and exports
- login.html page structure
- settings.html page structure
- WhoAmI badge in index.html
"""

import pytest
import os
from pathlib import Path


# Get frontend paths
FRONTEND_DIR = Path(__file__).parent.parent.parent / "services" / "frontend-bess"


class TestAuthJsModule:
    """Tests for auth.js module structure."""

    def test_auth_js_exists(self):
        """auth.js should exist."""
        auth_js = FRONTEND_DIR / "auth.js"
        assert auth_js.exists(), "auth.js not found"

    def test_auth_js_exports_required_functions(self):
        """auth.js should export required functions to window."""
        auth_js = FRONTEND_DIR / "auth.js"
        content = auth_js.read_text(encoding="utf-8")

        required_exports = [
            "window.login",
            "window.logout",
            "window.initAuth",
            "window.authFetch",
            "window.getAuthToken",
            "window.setAuthToken",
            "window.isAuthenticated",
            "window.clearAuth",
            "window.updateWhoAmiBadge",
            "window.listApiKeys",
            "window.createApiKey",
            "window.revokeApiKey",
        ]

        for export in required_exports:
            assert export in content, f"Missing export: {export}"

    def test_auth_js_has_auth_config(self):
        """auth.js should have AUTH_CONFIG constant."""
        auth_js = FRONTEND_DIR / "auth.js"
        content = auth_js.read_text(encoding="utf-8")

        assert "AUTH_CONFIG" in content
        assert "baseUrl" in content
        assert "tokenKey" in content
        assert "loginPath" in content

    def test_auth_js_has_token_storage(self):
        """auth.js should have token storage functions."""
        auth_js = FRONTEND_DIR / "auth.js"
        content = auth_js.read_text(encoding="utf-8")

        assert "localStorage.setItem" in content
        assert "localStorage.getItem" in content
        assert "localStorage.removeItem" in content

    def test_auth_js_has_fetch_wrapper(self):
        """auth.js should have auth-aware fetch wrapper."""
        auth_js = FRONTEND_DIR / "auth.js"
        content = auth_js.read_text(encoding="utf-8")

        assert "async function authFetch" in content
        assert "Authorization" in content
        assert "Bearer" in content

    def test_auth_js_handles_401(self):
        """auth.js should handle 401 responses."""
        auth_js = FRONTEND_DIR / "auth.js"
        content = auth_js.read_text(encoding="utf-8")

        assert "response.status === 401" in content
        assert "redirect" in content.lower() or "location.href" in content


class TestLoginPage:
    """Tests for login.html page."""

    def test_login_html_exists(self):
        """login.html should exist."""
        login_html = FRONTEND_DIR / "login.html"
        assert login_html.exists(), "login.html not found"

    def test_login_page_has_form(self):
        """login.html should have login form."""
        login_html = FRONTEND_DIR / "login.html"
        content = login_html.read_text(encoding="utf-8")

        assert "loginForm" in content
        assert 'type="email"' in content
        assert 'type="password"' in content
        assert 'type="submit"' in content

    def test_login_page_includes_auth_js(self):
        """login.html should include auth.js."""
        login_html = FRONTEND_DIR / "login.html"
        content = login_html.read_text(encoding="utf-8")

        assert "auth.js" in content

    def test_login_page_has_error_display(self):
        """login.html should have error display element."""
        login_html = FRONTEND_DIR / "login.html"
        content = login_html.read_text(encoding="utf-8")

        assert "loginError" in content

    def test_login_page_handles_auth_disabled(self):
        """login.html should handle auth disabled mode."""
        login_html = FRONTEND_DIR / "login.html"
        content = login_html.read_text(encoding="utf-8")

        assert "authDisabledNotice" in content or "auth_method" in content

    def test_login_page_redirects_on_success(self):
        """login.html should redirect to index.html on success."""
        login_html = FRONTEND_DIR / "login.html"
        content = login_html.read_text(encoding="utf-8")

        assert "index.html" in content


class TestSettingsPage:
    """Tests for settings.html page."""

    def test_settings_html_exists(self):
        """settings.html should exist."""
        settings_html = FRONTEND_DIR / "settings.html"
        assert settings_html.exists(), "settings.html not found"

    def test_settings_page_has_api_keys_section(self):
        """settings.html should have API keys section."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "apiKeysSection" in content or "api-keys" in content
        assert "apiKeysTable" in content or "api-keys-table" in content

    def test_settings_page_has_create_key_modal(self):
        """settings.html should have create key modal."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "createKeyModal" in content
        assert "keyLabel" in content
        assert "keyRole" in content

    def test_settings_page_has_audit_log_section(self):
        """settings.html should have audit log section."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "auditLogSection" in content or "audit-log" in content

    def test_settings_page_includes_auth_js(self):
        """settings.html should include auth.js."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "auth.js" in content

    def test_settings_page_has_whoami_badge(self):
        """settings.html should have WhoAmI badge."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "whoamiBadge" in content

    # v3.1.0 Users/Invites tests
    def test_settings_page_has_users_section(self):
        """settings.html should have users section (v3.1.0)."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "usersSection" in content
        assert "usersTable" in content

    def test_settings_page_has_invites_section(self):
        """settings.html should have invites section (v3.1.0)."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "invitesSection" in content
        assert "invitesTable" in content

    def test_settings_page_has_create_user_modal(self):
        """settings.html should have create user modal (v3.1.0)."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "createUserModal" in content
        assert "userEmail" in content
        assert "userRole" in content
        assert "userPassword" in content

    def test_settings_page_has_create_invite_modal(self):
        """settings.html should have create invite modal (v3.1.0)."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "createInviteModal" in content
        assert "inviteEmail" in content
        assert "inviteRole" in content
        assert "inviteExpires" in content

    def test_settings_page_has_users_tab(self):
        """settings.html should have users tab (v3.1.0)."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert 'data-tab="users"' in content

    def test_settings_page_has_invites_tab(self):
        """settings.html should have invites tab (v3.1.0)."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert 'data-tab="invites"' in content

    def test_settings_page_has_load_users_function(self):
        """settings.html should have loadUsers function (v3.1.0)."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "async function loadUsers" in content

    def test_settings_page_has_load_invites_function(self):
        """settings.html should have loadInvites function (v3.1.0)."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "async function loadInvites" in content

    def test_settings_page_checks_admin_role(self):
        """settings.html should check for admin role."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "admin" in content


class TestIndexPageAuth:
    """Tests for auth integration in index.html."""

    def test_index_html_includes_auth_js(self):
        """index.html should include auth.js."""
        index_html = FRONTEND_DIR / "index.html"
        content = index_html.read_text(encoding="utf-8")

        assert "auth.js" in content

    def test_index_html_has_whoami_badge(self):
        """index.html should have WhoAmI badge element."""
        index_html = FRONTEND_DIR / "index.html"
        content = index_html.read_text(encoding="utf-8")

        assert "whoamiBadge" in content

    def test_index_html_initializes_auth(self):
        """index.html should initialize auth module."""
        index_html = FRONTEND_DIR / "index.html"
        content = index_html.read_text(encoding="utf-8")

        assert "initAuth" in content

    def test_index_html_has_settings_link(self):
        """index.html should have link to settings page."""
        index_html = FRONTEND_DIR / "index.html"
        content = index_html.read_text(encoding="utf-8")

        assert "settings.html" in content

    def test_index_html_has_logout_button(self):
        """index.html should have logout button."""
        index_html = FRONTEND_DIR / "index.html"
        content = index_html.read_text(encoding="utf-8")

        assert "logout" in content


class TestStylesAuthSection:
    """Tests for auth styles in styles.css."""

    def test_styles_has_whoami_badge(self):
        """styles.css should have WhoAmI badge styles."""
        styles_css = FRONTEND_DIR / "styles.css"
        content = styles_css.read_text(encoding="utf-8")

        assert ".whoami-badge" in content
        assert ".whoami-email" in content
        assert ".whoami-role" in content

    def test_styles_has_role_colors(self):
        """styles.css should have role-specific colors."""
        styles_css = FRONTEND_DIR / "styles.css"
        content = styles_css.read_text(encoding="utf-8")

        assert ".role-admin" in content
        assert ".role-editor" in content
        assert ".role-viewer" in content
        assert ".role-service" in content

    def test_styles_has_api_keys_table(self):
        """styles.css should have API keys table styles."""
        styles_css = FRONTEND_DIR / "styles.css"
        content = styles_css.read_text(encoding="utf-8")

        assert ".api-keys-table" in content
        assert ".api-key-role" in content

    def test_styles_has_modal(self):
        """styles.css should have modal styles."""
        styles_css = FRONTEND_DIR / "styles.css"
        content = styles_css.read_text(encoding="utf-8")

        assert ".modal-overlay" in content
        assert ".modal-content" in content

    def test_styles_has_audit_log(self):
        """styles.css should have audit log styles."""
        styles_css = FRONTEND_DIR / "styles.css"
        content = styles_css.read_text(encoding="utf-8")

        assert ".audit-log-table" in content or ".audit-action" in content

    # v3.1.0 Audit Explorer styles
    def test_styles_has_audit_export_buttons(self):
        """styles.css should have audit export button styles (v3.1.0)."""
        styles_css = FRONTEND_DIR / "styles.css"
        content = styles_css.read_text(encoding="utf-8")

        assert ".audit-export-buttons" in content
        assert ".btn-export-secondary" in content

    def test_styles_has_audit_date_filters(self):
        """styles.css should have audit date filter styles (v3.1.0)."""
        styles_css = FRONTEND_DIR / "styles.css"
        content = styles_css.read_text(encoding="utf-8")

        assert ".audit-date-filters" in content
        assert ".date-filter-label" in content
        assert ".btn-clear-filters" in content

    def test_styles_has_new_audit_actions(self):
        """styles.css should have new audit action styles (v3.1.0)."""
        styles_css = FRONTEND_DIR / "styles.css"
        content = styles_css.read_text(encoding="utf-8")

        assert ".audit-action.user_created" in content
        assert ".audit-action.invite_created" in content
        assert ".audit-action.share_created" in content


class TestAuditExplorerUI:
    """Tests for audit explorer UI (v3.1.0 PR5)."""

    def test_audit_section_has_resource_filter(self):
        """settings.html should have resource type filter (v3.1.0)."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "auditResourceFilter" in content
        assert 'value="user"' in content
        assert 'value="invite"' in content
        assert 'value="share"' in content

    def test_audit_section_has_date_filters(self):
        """settings.html should have date filters (v3.1.0)."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "auditFromDate" in content
        assert "auditToDate" in content
        assert 'type="date"' in content

    def test_audit_section_has_csv_export(self):
        """settings.html should have CSV export button (v3.1.0)."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "exportAuditCsvFile" in content
        assert "CSV" in content

    def test_audit_section_has_json_export(self):
        """settings.html should have JSON export button (v3.1.0)."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "exportAuditJsonFile" in content
        assert "JSON" in content

    def test_audit_section_has_clear_filters(self):
        """settings.html should have clear filters button (v3.1.0)."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert "clearAuditFilters" in content
        assert "Wyczysc" in content

    def test_audit_has_new_action_options(self):
        """settings.html should have new action filter options (v3.1.0)."""
        settings_html = FRONTEND_DIR / "settings.html"
        content = settings_html.read_text(encoding="utf-8")

        assert 'value="user_created"' in content
        assert 'value="invite_created"' in content
        assert 'value="share_created"' in content

    def test_auth_js_has_csv_export(self):
        """auth.js should have exportAuditCsv function (v3.1.0)."""
        auth_js = FRONTEND_DIR / "auth.js"
        content = auth_js.read_text(encoding="utf-8")

        assert "async function exportAuditCsv" in content
        assert "window.exportAuditCsv" in content

    def test_auth_js_has_json_export(self):
        """auth.js should have exportAuditJson function (v3.1.0)."""
        auth_js = FRONTEND_DIR / "auth.js"
        content = auth_js.read_text(encoding="utf-8")

        assert "async function exportAuditJson" in content
        assert "window.exportAuditJson" in content

    def test_auth_js_query_supports_resource_type(self):
        """auth.js queryAuditLog should support resource_type (v3.1.0)."""
        auth_js = FRONTEND_DIR / "auth.js"
        content = auth_js.read_text(encoding="utf-8")

        assert "params.resource_type" in content

    def test_auth_js_query_supports_date_range(self):
        """auth.js queryAuditLog should support date range (v3.1.0)."""
        auth_js = FRONTEND_DIR / "auth.js"
        content = auth_js.read_text(encoding="utf-8")

        assert "params.from_date" in content
        assert "params.to_date" in content
