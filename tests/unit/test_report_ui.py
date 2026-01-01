"""
Unit tests for Report UI components (v2.4.0 PR5).

Tests verify:
- Report download functions exist in bess.js
- Report options elements exist in index.html
- Report CSS styles exist in styles.css
"""

import os
import pytest


class TestReportJavaScriptFunctions:
    """Tests for report download functions in bess.js."""

    @pytest.fixture
    def js_content(self):
        """Load bess.js content."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "bess.js"
        )
        with open(js_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_build_report_url_function_exists(self, js_content):
        """buildReportUrl function should exist."""
        assert "function buildReportUrl(" in js_content

    def test_get_report_options_function_exists(self, js_content):
        """getReportOptionsFromUI function should exist."""
        assert "function getReportOptionsFromUI(" in js_content

    def test_trigger_download_function_exists(self, js_content):
        """triggerDownload function should exist."""
        assert "function triggerDownload(" in js_content

    def test_download_run_report_pdf_function_exists(self, js_content):
        """downloadRunReportPDF function should exist."""
        assert "function downloadRunReportPDF(" in js_content

    def test_download_run_report_xlsx_function_exists(self, js_content):
        """downloadRunReportXLSX function should exist."""
        assert "function downloadRunReportXLSX(" in js_content

    def test_download_run_report_zip_function_exists(self, js_content):
        """downloadRunReportZIP function should exist."""
        assert "function downloadRunReportZIP(" in js_content

    def test_export_portfolio_report_zip_function_exists(self, js_content):
        """exportPortfolioReportZIP function should exist."""
        assert "function exportPortfolioReportZIP(" in js_content

    def test_window_exports_report_functions(self, js_content):
        """Report functions should be exported to window."""
        assert "window.buildReportUrl" in js_content
        assert "window.downloadRunReportPDF" in js_content
        assert "window.downloadRunReportXLSX" in js_content
        assert "window.downloadRunReportZIP" in js_content
        assert "window.exportPortfolioReportZIP" in js_content

    def test_report_url_uses_correct_endpoint(self, js_content):
        """Report URL should use correct API endpoint."""
        assert "/api/bess-dispatch/runs/" in js_content
        assert "/report." in js_content

    def test_portfolio_report_uses_correct_endpoint(self, js_content):
        """Portfolio report should use correct API endpoint."""
        assert "/api/bess-dispatch/portfolio/report.zip" in js_content

    def test_build_report_url_handles_profile(self, js_content):
        """buildReportUrl should handle profile parameter."""
        assert "options.profile" in js_content
        assert "'profile'" in js_content or '"profile"' in js_content

    def test_build_report_url_handles_client_name(self, js_content):
        """buildReportUrl should handle client_name parameter."""
        assert "options.client_name" in js_content or "client_name" in js_content

    def test_build_report_url_handles_site_name(self, js_content):
        """buildReportUrl should handle site_name parameter."""
        assert "options.site_name" in js_content or "site_name" in js_content


class TestReportHtmlElements:
    """Tests for report download elements in index.html."""

    @pytest.fixture
    def html_content(self):
        """Load index.html content."""
        html_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "index.html"
        )
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_report_downloads_section_exists(self, html_content):
        """Report downloads section should exist."""
        assert "run-report-downloads" in html_content
        assert "Raporty" in html_content

    def test_pdf_download_button_exists(self, html_content):
        """PDF download button should exist."""
        assert "downloadRunReportPDF()" in html_content
        assert "PDF" in html_content

    def test_xlsx_download_button_exists(self, html_content):
        """XLSX download button should exist."""
        assert "downloadRunReportXLSX()" in html_content
        assert "XLSX" in html_content

    def test_zip_download_button_exists(self, html_content):
        """ZIP download button should exist."""
        assert "downloadRunReportZIP()" in html_content

    def test_report_profile_selector_exists(self, html_content):
        """Report profile selector should exist."""
        assert 'id="reportProfile"' in html_content
        assert "client" in html_content
        assert "engineering" in html_content

    def test_report_client_name_input_exists(self, html_content):
        """Report client name input should exist."""
        assert 'id="reportClientName"' in html_content

    def test_report_site_name_input_exists(self, html_content):
        """Report site name input should exist."""
        assert 'id="reportSiteName"' in html_content

    def test_portfolio_report_button_exists(self, html_content):
        """Portfolio report ZIP button should exist."""
        assert "exportPortfolioReportZIP()" in html_content
        assert "Raport ZIP" in html_content


class TestReportCssStyles:
    """Tests for report download styles in styles.css."""

    @pytest.fixture
    def css_content(self):
        """Load styles.css content."""
        css_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "styles.css"
        )
        with open(css_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_report_downloads_section_styled(self, css_content):
        """Report downloads section should have styles."""
        assert ".run-report-downloads" in css_content

    def test_report_buttons_styled(self, css_content):
        """Report buttons should have styles."""
        assert ".report-buttons" in css_content

    def test_report_options_styled(self, css_content):
        """Report options should have styles."""
        assert ".report-options" in css_content

    def test_report_option_row_styled(self, css_content):
        """Report option rows should have styles."""
        assert ".report-option-row" in css_content

    def test_btn_success_styled(self, css_content):
        """Button success variant should be styled."""
        assert ".btn.btn-success" in css_content or ".btn-success" in css_content


class TestReportUrlBuilderModule:
    """Tests for report_url_builder.js module."""

    @pytest.fixture
    def module_content(self):
        """Load report_url_builder.js content."""
        module_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "report_url_builder.js"
        )
        with open(module_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_module_exports_build_report_url(self, module_content):
        """Module should export buildReportUrl function."""
        assert "buildReportUrl" in module_content
        assert "exports.buildReportUrl" in module_content or "exports = {" in module_content

    def test_module_exports_build_portfolio_report_url(self, module_content):
        """Module should export buildPortfolioReportUrl function."""
        assert "buildPortfolioReportUrl" in module_content

    def test_module_exports_is_valid_run_id(self, module_content):
        """Module should export isValidRunId function."""
        assert "isValidRunId" in module_content

    def test_module_validates_format(self, module_content):
        """Module should validate format parameter."""
        assert "validFormats" in module_content or "'pdf', 'xlsx', 'zip'" in module_content

    def test_module_supports_common_js(self, module_content):
        """Module should support CommonJS exports."""
        assert "module.exports" in module_content

    def test_module_supports_browser(self, module_content):
        """Module should support browser global."""
        assert "ReportUrlBuilder" in module_content
