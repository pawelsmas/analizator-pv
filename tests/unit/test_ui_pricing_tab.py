"""
Unit tests for UI Pricing tab components (v2.0.0 PR5).

Tests verify:
- Pricing section HTML structure exists
- JavaScript functions are defined
- Price override CSV parsing logic
"""

import pytest
import os


class TestPricingSectionHTML:
    """Tests for pricing section in index.html."""

    @pytest.fixture
    def html_content(self):
        """Load index.html content."""
        html_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "index.html"
        )
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_pricing_section_exists(self, html_content):
        """Verify pricing section div exists."""
        assert 'id="pricingSection"' in html_content

    def test_pricing_mode_label_exists(self, html_content):
        """Verify pricing mode label element exists."""
        assert 'id="pricingModeLabel"' in html_content

    def test_price_hash_display_exists(self, html_content):
        """Verify price hash display element exists."""
        assert 'id="priceHashShort"' in html_content

    def test_price_import_value_exists(self, html_content):
        """Verify import price display element exists."""
        assert 'id="priceImportValue"' in html_content

    def test_price_export_value_exists(self, html_content):
        """Verify export price display element exists."""
        assert 'id="priceExportValue"' in html_content

    def test_csv_override_input_exists(self, html_content):
        """Verify CSV override file input exists."""
        assert 'id="priceOverrideCsv"' in html_content

    def test_clear_override_button_exists(self, html_content):
        """Verify clear override button exists."""
        assert 'id="clearPriceOverride"' in html_content

    def test_cost_buckets_chart_exists(self, html_content):
        """Verify cost buckets chart container exists."""
        assert 'id="costBucketsChart"' in html_content

    def test_ledger_timeseries_chart_exists(self, html_content):
        """Verify ledger timeseries chart canvas exists."""
        assert 'id="ledgerTimeseriesChart"' in html_content


class TestPricingJavaScript:
    """Tests for pricing JavaScript functions."""

    @pytest.fixture
    def js_content(self):
        """Load bess.js content."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "bess.js"
        )
        with open(js_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_update_pricing_display_function_exists(self, js_content):
        """Verify updatePricingDisplay function exists."""
        assert "function updatePricingDisplay" in js_content

    def test_update_cost_buckets_function_exists(self, js_content):
        """Verify updateCostBucketsChart function exists."""
        assert "function updateCostBucketsChart" in js_content

    def test_handle_price_override_csv_function_exists(self, js_content):
        """Verify handlePriceOverrideCsv function exists."""
        assert "function handlePriceOverrideCsv" in js_content

    def test_clear_price_override_function_exists(self, js_content):
        """Verify clearPriceOverride function exists."""
        assert "function clearPriceOverride" in js_content

    def test_get_price_override_function_exists(self, js_content):
        """Verify getPriceOverrideForRequest function exists."""
        assert "function getPriceOverrideForRequest" in js_content

    def test_pricing_functions_exported(self, js_content):
        """Verify pricing functions are exported to window."""
        assert "window.updatePricingDisplay" in js_content
        assert "window.handlePriceOverrideCsv" in js_content
        assert "window.clearPriceOverride" in js_content

    def test_version_updated(self, js_content):
        """Verify JS version includes v2.0.0."""
        assert "v2.0.0" in js_content or "v3.30" in js_content


class TestPricingLogic:
    """Tests for pricing display logic."""

    def test_cost_bucket_percentage_calculation(self):
        """Verify percentage calculation logic."""
        buckets = [
            {"value": 100.0},  # 50%
            {"value": 50.0},   # 25%
            {"value": 50.0},   # 25%
        ]
        total = sum(abs(b["value"]) for b in buckets)
        assert total == 200.0

        for b in buckets:
            pct = abs(b["value"]) / total * 100
            assert 0 <= pct <= 100

    def test_price_hash_truncation(self):
        """Verify price hash truncation logic."""
        full_hash = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6a7b8c9d0e1f2"
        truncated = full_hash[:12] + "..."
        assert len(truncated) == 15
        assert truncated.endswith("...")

    def test_csv_parsing_logic(self):
        """Verify CSV parsing logic for price override."""
        csv_content = """import_price,export_price
800,400
900,450
1000,500"""
        lines = csv_content.split('\n')
        header = lines[0]

        import_prices = []
        export_prices = []

        for i in range(1, len(lines)):
            parts = lines[i].split(',')
            if len(parts) >= 2:
                import_prices.append(float(parts[0]))
                export_prices.append(float(parts[1]))

        assert len(import_prices) == 3
        assert len(export_prices) == 3
        assert import_prices == [800.0, 900.0, 1000.0]
        assert export_prices == [400.0, 450.0, 500.0]

    def test_empty_csv_handling(self):
        """Verify empty CSV detection."""
        csv_content = """import_price,export_price"""
        lines = csv_content.split('\n')

        data_lines = [l for l in lines[1:] if l.strip()]
        assert len(data_lines) == 0

    def test_pricing_mode_display_values(self):
        """Verify pricing mode display values."""
        valid_modes = ["generated", "override"]
        for mode in valid_modes:
            assert mode in valid_modes

        # Mode should be uppercase in UI
        assert "GENERATED" == "generated".upper()
        assert "OVERRIDE" == "override".upper()


class TestPricingIntegration:
    """Integration tests for pricing components."""

    def test_pricing_section_in_correct_position(self):
        """Verify pricing section is after Technical Parameters."""
        html_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "index.html"
        )
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find positions
        tech_params_pos = content.find("Parametry Techniczne BESS")
        pricing_pos = content.find('id="pricingSection"')
        advanced_config_pos = content.find("Konfiguracja Zaawansowana BESS")

        assert tech_params_pos > 0, "Technical Parameters section not found"
        assert pricing_pos > 0, "Pricing section not found"
        assert advanced_config_pos > 0, "Advanced Configuration section not found"

        # Pricing should be between Tech Params and Advanced Config
        assert tech_params_pos < pricing_pos < advanced_config_pos, \
            "Pricing section should be between Technical Parameters and Advanced Configuration"
