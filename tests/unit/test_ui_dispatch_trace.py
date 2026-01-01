"""
Unit tests for UI Dispatch Trace tab components (v2.2.0 PR4).

Tests verify:
- Dispatch trace section HTML structure exists
- JavaScript functions are defined
- Cycle summary elements exist
- Invariants display elements exist
"""

import pytest
import os


class TestDispatchTraceSectionHTML:
    """Tests for dispatch trace section in index.html."""

    @pytest.fixture
    def html_content(self):
        """Load index.html content."""
        html_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "index.html"
        )
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_dispatch_trace_section_exists(self, html_content):
        """Verify dispatch trace section div exists."""
        assert 'id="dispatchTraceSection"' in html_content

    def test_soc_chart_canvas_exists(self, html_content):
        """Verify SOC timeseries chart canvas exists."""
        assert 'id="socTimeseriesChart"' in html_content

    def test_power_chart_canvas_exists(self, html_content):
        """Verify power timeseries chart canvas exists."""
        assert 'id="powerTimeseriesChart"' in html_content

    def test_soc_chart_placeholder_exists(self, html_content):
        """Verify SOC chart placeholder exists."""
        assert 'id="socChartPlaceholder"' in html_content

    def test_power_chart_placeholder_exists(self, html_content):
        """Verify power chart placeholder exists."""
        assert 'id="powerChartPlaceholder"' in html_content


class TestCycleSummaryElementsHTML:
    """Tests for cycle summary elements in index.html."""

    @pytest.fixture
    def html_content(self):
        """Load index.html content."""
        html_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "index.html"
        )
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_cycle_total_efc_element_exists(self, html_content):
        """Verify total EFC display element exists."""
        assert 'id="cycleTotalEfc"' in html_content

    def test_cycle_avg_daily_efc_element_exists(self, html_content):
        """Verify avg daily EFC display element exists."""
        assert 'id="cycleAvgDailyEfc"' in html_content

    def test_cycle_max_daily_efc_element_exists(self, html_content):
        """Verify max daily EFC display element exists."""
        assert 'id="cycleMaxDailyEfc"' in html_content

    def test_cycle_throughput_element_exists(self, html_content):
        """Verify throughput display element exists."""
        assert 'id="cycleThroughputMwh"' in html_content

    def test_cycle_limit_warning_element_exists(self, html_content):
        """Verify cycle limit warning element exists."""
        assert 'id="cycleLimitWarning"' in html_content

    def test_cycle_limit_days_element_exists(self, html_content):
        """Verify cycle limit days element exists."""
        assert 'id="cycleLimitDays"' in html_content


class TestInvariantsElementsHTML:
    """Tests for invariants display elements in index.html."""

    @pytest.fixture
    def html_content(self):
        """Load index.html content."""
        html_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "index.html"
        )
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_invariants_status_container_exists(self, html_content):
        """Verify invariants status container exists."""
        assert 'id="invariantsStatus"' in html_content

    def test_invariant_soc_bounds_element_exists(self, html_content):
        """Verify SOC bounds invariant element exists."""
        assert 'id="invariantSocBounds"' in html_content

    def test_invariant_power_limits_element_exists(self, html_content):
        """Verify power limits invariant element exists."""
        assert 'id="invariantPowerLimits"' in html_content

    def test_invariant_no_simultaneous_element_exists(self, html_content):
        """Verify no-simultaneous invariant element exists."""
        assert 'id="invariantNoSimultaneous"' in html_content

    def test_invariant_energy_balance_element_exists(self, html_content):
        """Verify energy balance invariant element exists."""
        assert 'id="invariantEnergyBalance"' in html_content

    def test_invariants_all_ok_element_exists(self, html_content):
        """Verify all-ok status element exists."""
        assert 'id="invariantsAllOk"' in html_content

    def test_invariants_violations_element_exists(self, html_content):
        """Verify violations status element exists."""
        assert 'id="invariantsViolations"' in html_content

    def test_invariants_violation_count_element_exists(self, html_content):
        """Verify violation count element exists."""
        assert 'id="invariantsViolationCount"' in html_content


class TestDispatchTraceJavaScript:
    """Tests for dispatch trace JavaScript functions."""

    @pytest.fixture
    def js_content(self):
        """Load bess.js content."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "bess.js"
        )
        with open(js_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_update_dispatch_trace_display_function_exists(self, js_content):
        """Verify updateDispatchTraceDisplay function exists."""
        assert "function updateDispatchTraceDisplay" in js_content

    def test_update_soc_chart_function_exists(self, js_content):
        """Verify updateSocChart function exists."""
        assert "function updateSocChart" in js_content

    def test_update_power_chart_function_exists(self, js_content):
        """Verify updatePowerChart function exists."""
        assert "function updatePowerChart" in js_content

    def test_update_cycle_summary_display_function_exists(self, js_content):
        """Verify updateCycleSummaryDisplay function exists."""
        assert "function updateCycleSummaryDisplay" in js_content

    def test_update_invariants_display_function_exists(self, js_content):
        """Verify updateInvariantsDisplay function exists."""
        assert "function updateInvariantsDisplay" in js_content

    def test_export_battery_trace_function_exists(self, js_content):
        """Verify exportBatteryTrace function exists."""
        assert "function exportBatteryTrace" in js_content

    def test_clear_dispatch_trace_display_function_exists(self, js_content):
        """Verify clearDispatchTraceDisplay function exists."""
        assert "function clearDispatchTraceDisplay" in js_content

    def test_dispatch_trace_functions_exported(self, js_content):
        """Verify dispatch trace functions are exported to window."""
        assert "window.updateDispatchTraceDisplay" in js_content
        assert "window.exportBatteryTrace" in js_content
        assert "window.clearDispatchTraceDisplay" in js_content


class TestExportTraceButtonHTML:
    """Tests for export trace button in index.html."""

    @pytest.fixture
    def html_content(self):
        """Load index.html content."""
        html_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "index.html"
        )
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_export_trace_button_exists(self, html_content):
        """Verify export trace button exists."""
        assert 'id="exportTraceBtn"' in html_content

    def test_export_trace_button_calls_function(self, html_content):
        """Verify export trace button calls exportBatteryTrace."""
        assert 'onclick="exportBatteryTrace()"' in html_content


class TestSizingRequestIncludesTraceFlag:
    """Tests for include_battery_trace flag in sizing request."""

    @pytest.fixture
    def js_content(self):
        """Load bess.js content."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "services", "frontend-bess", "bess.js"
        )
        with open(js_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_include_battery_trace_flag_set(self, js_content):
        """Verify include_battery_trace flag is set in request."""
        assert "include_battery_trace = true" in js_content or "include_battery_trace: true" in js_content

    def test_include_invariants_flag_set(self, js_content):
        """Verify include_invariants flag is set in request."""
        assert "include_invariants = true" in js_content or "include_invariants: true" in js_content
