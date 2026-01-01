"""
Unit tests for Portfolio UI (v2.3.0 PR5).

Tests verify:
- Portfolio card HTML elements exist
- Portfolio styles are defined
- JavaScript functions are exported
"""

import pytest
import os


class TestPortfolioHtmlElements:
    """Tests for portfolio HTML elements in index.html."""

    @pytest.fixture
    def html_content(self):
        """Load index.html content."""
        html_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "index.html"
        )
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_portfolio_card_exists(self, html_content):
        """Portfolio card div should exist."""
        assert 'class="config-card portfolio-card"' in html_content

    def test_portfolio_run_select_exists(self, html_content):
        """Portfolio run select element should exist."""
        assert 'id="portfolioRunSelect"' in html_content

    def test_portfolio_summary_button_exists(self, html_content):
        """Run Portfolio Summary button should exist."""
        assert 'id="runPortfolioSummaryBtn"' in html_content

    def test_portfolio_results_container_exists(self, html_content):
        """Portfolio results container should exist."""
        assert 'id="portfolioResultsContainer"' in html_content

    def test_portfolio_items_total_element_exists(self, html_content):
        """Portfolio items total element should exist."""
        assert 'id="portfolioItemsTotal"' in html_content

    def test_portfolio_total_npv_element_exists(self, html_content):
        """Portfolio total NPV element should exist."""
        assert 'id="portfolioTotalNpv"' in html_content

    def test_portfolio_export_csv_button_exists(self, html_content):
        """Export CSV button should exist."""
        assert 'onclick="exportPortfolioCSV()"' in html_content

    def test_portfolio_export_zip_button_exists(self, html_content):
        """Export ZIP button should exist."""
        assert 'onclick="exportPortfolioZIP()"' in html_content

    def test_portfolio_items_table_exists(self, html_content):
        """Portfolio items table should exist."""
        assert 'id="portfolioItemsBody"' in html_content


class TestPortfolioCssStyles:
    """Tests for portfolio CSS styles."""

    @pytest.fixture
    def css_content(self):
        """Load styles.css content."""
        css_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "styles.css"
        )
        with open(css_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_portfolio_card_style_exists(self, css_content):
        """Portfolio card style should exist."""
        assert ".portfolio-card" in css_content

    def test_portfolio_inputs_style_exists(self, css_content):
        """Portfolio inputs style should exist."""
        assert ".portfolio-inputs" in css_content

    def test_portfolio_results_container_style_exists(self, css_content):
        """Portfolio results container style should exist."""
        assert ".portfolio-results-container" in css_content

    def test_portfolio_status_style_exists(self, css_content):
        """Portfolio status style should exist."""
        assert ".portfolio-status" in css_content

    def test_portfolio_summary_style_exists(self, css_content):
        """Portfolio summary style should exist."""
        assert ".portfolio-summary" in css_content

    def test_portfolio_items_table_style_exists(self, css_content):
        """Portfolio items table style should exist."""
        assert ".portfolio-items .items-table" in css_content

    def test_portfolio_actions_style_exists(self, css_content):
        """Portfolio actions style should exist."""
        assert ".portfolio-actions" in css_content


class TestPortfolioJavaScriptFunctions:
    """Tests for portfolio JavaScript functions in bess.js."""

    @pytest.fixture
    def js_content(self):
        """Load bess.js content."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "bess.js"
        )
        with open(js_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_load_available_runs_function_exists(self, js_content):
        """loadAvailableRuns function should exist."""
        assert "function loadAvailableRuns()" in js_content

    def test_refresh_run_list_function_exists(self, js_content):
        """refreshRunList function should exist."""
        assert "function refreshRunList()" in js_content

    def test_update_portfolio_selection_function_exists(self, js_content):
        """updatePortfolioSelection function should exist."""
        assert "function updatePortfolioSelection()" in js_content

    def test_run_portfolio_summary_function_exists(self, js_content):
        """runPortfolioSummary function should exist."""
        assert "async function runPortfolioSummary()" in js_content

    def test_display_portfolio_results_function_exists(self, js_content):
        """displayPortfolioResults function should exist."""
        assert "function displayPortfolioResults(data)" in js_content

    def test_export_portfolio_csv_function_exists(self, js_content):
        """exportPortfolioCSV function should exist."""
        assert "async function exportPortfolioCSV()" in js_content

    def test_export_portfolio_zip_function_exists(self, js_content):
        """exportPortfolioZIP function should exist."""
        assert "async function exportPortfolioZIP()" in js_content

    def test_window_exports_portfolio_functions(self, js_content):
        """Portfolio functions should be exported to window."""
        assert "window.loadAvailableRuns" in js_content
        assert "window.runPortfolioSummary" in js_content
        assert "window.exportPortfolioCSV" in js_content
        assert "window.exportPortfolioZIP" in js_content

    def test_portfolio_version_log(self, js_content):
        """Version log should mention v2.3.0 Portfolio."""
        assert "v2.3.0 Portfolio" in js_content


class TestPortfolioApiEndpoints:
    """Tests for portfolio API endpoint calls in bess.js."""

    @pytest.fixture
    def js_content(self):
        """Load bess.js content."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "bess.js"
        )
        with open(js_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_portfolio_summary_endpoint_called(self, js_content):
        """Portfolio summary endpoint should be called."""
        assert "/api/bess-dispatch/portfolio/summary" in js_content

    def test_portfolio_export_csv_endpoint_called(self, js_content):
        """Portfolio export CSV endpoint should be called."""
        assert "/api/bess-dispatch/portfolio/summary/export/csv" in js_content

    def test_portfolio_export_zip_endpoint_called(self, js_content):
        """Portfolio export ZIP endpoint should be called."""
        assert "/api/bess-dispatch/portfolio/summary/export/zip" in js_content

    def test_runs_endpoint_called(self, js_content):
        """Runs endpoint should be called for loading available runs."""
        assert "/runs?limit=50" in js_content
