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
