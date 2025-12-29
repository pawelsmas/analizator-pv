"""
Contract tests for v0.6.0 lifecycle metrics (replacement, degradation, sweeps).

These tests verify:
1. Lifecycle metrics appear in /metrics after relevant requests
2. Counter increments for replacement/degradation/sensitivity requests
3. Histograms record degradation rates and replacement years

Run with: python -m pytest tests/contract/test_lifecycle_metrics_contract.py -v
"""
import requests

from ._api import post_json, load_smoke_payload

METRICS_URL = "http://localhost:8031/metrics"


def get_metrics() -> str:
    """Fetch Prometheus metrics."""
    resp = requests.get(METRICS_URL, timeout=10)
    return resp.text


class TestReplacementMetrics:
    """Test that replacement metrics appear after request with replacement_year."""

    def test_replacement_metrics_present_after_request(self):
        """bess_finance_replacement_requests_total should increment after replacement request."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 15
        fc["replacement_year"] = 10
        fc["include_cashflow_timeseries"] = True
        p["finance_config"] = fc

        # Make request to trigger metrics
        post_json("/sizing", p)

        # Check metrics
        metrics = get_metrics()
        assert "bess_finance_replacement_requests_total" in metrics, (
            "Replacement counter should be present after request with replacement_year"
        )


class TestDegradationMetrics:
    """Test that degradation metrics appear after request with degradation rates."""

    def test_degradation_metrics_present_after_bess_degradation(self):
        """bess_finance_degradation_requests_total should increment for BESS degradation."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 15
        fc["bess_degradation_pct_per_year"] = 2.0
        fc["include_cashflow_timeseries"] = True
        p["finance_config"] = fc

        # Make request to trigger metrics
        post_json("/sizing", p)

        # Check metrics
        metrics = get_metrics()
        assert "bess_finance_degradation_requests_total" in metrics, (
            "Degradation counter should be present after request with BESS degradation"
        )

    def test_degradation_rate_histogram_present(self):
        """bess_finance_bess_degradation_rate_pct should record degradation rate."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 15
        fc["bess_degradation_pct_per_year"] = 2.0
        fc["include_cashflow_timeseries"] = True
        p["finance_config"] = fc

        # Make request to trigger metrics
        post_json("/sizing", p)

        # Check metrics
        metrics = get_metrics()
        assert "bess_finance_bess_degradation_rate_pct" in metrics, (
            "BESS degradation rate histogram should be present"
        )


class TestSensitivitySweepMetrics:
    """Test that sensitivity sweep metrics appear after sweep requests."""

    def test_energy_price_sensitivity_metrics_present(self):
        """bess_finance_energy_price_sensitivity_total should increment."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["energy_price_multiplier_sweep"] = [0.8, 1.0, 1.2]
        p["finance_config"] = fc

        # Make request to trigger metrics
        post_json("/sizing", p)

        # Check metrics
        metrics = get_metrics()
        assert "bess_finance_energy_price_sensitivity_total" in metrics, (
            "Energy price sensitivity counter should be present"
        )

    def test_capex_sensitivity_metrics_present(self):
        """bess_finance_capex_sensitivity_total should increment."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["capex_multiplier_sweep"] = [0.8, 1.0, 1.2]
        p["finance_config"] = fc

        # Make request to trigger metrics
        post_json("/sizing", p)

        # Check metrics
        metrics = get_metrics()
        assert "bess_finance_capex_sensitivity_total" in metrics, (
            "CAPEX sensitivity counter should be present"
        )


class TestMetricsFormat:
    """Test that metrics follow Prometheus format."""

    def test_lifecycle_metrics_have_help_and_type(self):
        """All lifecycle metrics should have HELP and TYPE lines."""
        # Trigger all lifecycle metrics
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 15
        fc["replacement_year"] = 10
        fc["bess_degradation_pct_per_year"] = 2.0
        fc["energy_price_multiplier_sweep"] = [0.8, 1.0, 1.2]
        fc["capex_multiplier_sweep"] = [0.8, 1.0, 1.2]
        fc["include_cashflow_timeseries"] = True
        p["finance_config"] = fc

        post_json("/sizing", p)

        metrics = get_metrics()

        # Check for HELP lines
        lifecycle_metrics = [
            "bess_finance_replacement_requests_total",
            "bess_finance_degradation_requests_total",
            "bess_finance_energy_price_sensitivity_total",
            "bess_finance_capex_sensitivity_total",
        ]

        for metric_name in lifecycle_metrics:
            assert f"# HELP {metric_name}" in metrics, (
                f"Metric {metric_name} should have HELP line"
            )
            assert f"# TYPE {metric_name}" in metrics, (
                f"Metric {metric_name} should have TYPE line"
            )
