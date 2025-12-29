"""
Contract tests for v0.8.0 sizing constraint and Pareto metrics.

These tests verify that the /metrics endpoint includes:
- Sizing constraint request counters
- Feasibility counters
- Pareto frontier metrics

Run with: pytest tests/contract/test_sizing_constraint_metrics.py -v
"""
import pytest
import requests
from ._api import post_json


SIZING_PATH = "/sizing"
METRICS_URL = "http://localhost:8031/metrics"


class TestSizingConstraintMetrics:
    """Tests for sizing constraint metrics (v0.8.0)."""

    def test_sizing_constraints_requests_counter_increments(self):
        """Verify bess_sizing_constraints_requests_total increments with constraints_config."""
        # Make a sizing request WITH constraints_config
        payload = {
            "load_kw": [100, 120, 110, 90],
            "pv_generation_kw": [50, 70, 80, 60],
            "energy_price_pln_kwh": 0.8,
            "constraints_config": {
                "max_capex_pln": 200000,
            }
        }
        post_json(SIZING_PATH, payload)

        # Check metrics
        metrics_resp = requests.get(METRICS_URL)
        assert metrics_resp.status_code == 200
        assert "bess_sizing_constraints_requests_total" in metrics_resp.text

    def test_sizing_feasible_variants_histogram(self):
        """Verify bess_sizing_feasible_variants_count histogram is present."""
        # Make a sizing request WITH constraints_config
        payload = {
            "load_kw": [100, 120, 110, 90],
            "pv_generation_kw": [50, 70, 80, 60],
            "energy_price_pln_kwh": 0.8,
            "constraints_config": {
                "max_payback_years": 15,
            }
        }
        post_json(SIZING_PATH, payload)

        # Check metrics
        metrics_resp = requests.get(METRICS_URL)
        assert metrics_resp.status_code == 200
        assert "bess_sizing_feasible_variants_count" in metrics_resp.text

    def test_constraint_type_counters(self):
        """Verify constraint-specific counters increment."""
        # Make a sizing request with multiple constraint types
        payload = {
            "load_kw": [100, 120, 110, 90],
            "pv_generation_kw": [50, 70, 80, 60],
            "energy_price_pln_kwh": 0.8,
            "constraints_config": {
                "max_capex_pln": 200000,
                "max_payback_years": 15,
                "min_npv_pln": 0,
            }
        }
        post_json(SIZING_PATH, payload)

        # Check metrics
        metrics_resp = requests.get(METRICS_URL)
        assert metrics_resp.status_code == 200
        metrics_text = metrics_resp.text

        assert "bess_sizing_constraint_max_capex_total" in metrics_text
        assert "bess_sizing_constraint_max_payback_total" in metrics_text
        assert "bess_sizing_constraint_min_npv_total" in metrics_text


class TestParetoFrontierMetrics:
    """Tests for Pareto frontier metrics (v0.8.0)."""

    def test_pareto_frontier_requests_counter(self):
        """Verify bess_pareto_frontier_requests_total counter increments."""
        # Make any sizing request (Pareto is always calculated)
        payload = {
            "load_kw": [100, 120, 110, 90],
            "pv_generation_kw": [50, 70, 80, 60],
            "energy_price_pln_kwh": 0.8,
        }
        post_json(SIZING_PATH, payload)

        # Check metrics
        metrics_resp = requests.get(METRICS_URL)
        assert metrics_resp.status_code == 200
        assert "bess_pareto_frontier_requests_total" in metrics_resp.text

    def test_pareto_frontier_size_histogram(self):
        """Verify bess_pareto_frontier_size histogram is present."""
        # Make any sizing request
        payload = {
            "load_kw": [100, 120, 110, 90],
            "pv_generation_kw": [50, 70, 80, 60],
            "energy_price_pln_kwh": 0.8,
        }
        post_json(SIZING_PATH, payload)

        # Check metrics
        metrics_resp = requests.get(METRICS_URL)
        assert metrics_resp.status_code == 200
        assert "bess_pareto_frontier_size" in metrics_resp.text

    def test_pareto_dominated_count_histogram(self):
        """Verify bess_pareto_dominated_count histogram is present."""
        # Make any sizing request
        payload = {
            "load_kw": [100, 120, 110, 90],
            "pv_generation_kw": [50, 70, 80, 60],
            "energy_price_pln_kwh": 0.8,
        }
        post_json(SIZING_PATH, payload)

        # Check metrics
        metrics_resp = requests.get(METRICS_URL)
        assert metrics_resp.status_code == 200
        assert "bess_pareto_dominated_count" in metrics_resp.text


class TestMetricsFormat:
    """Tests for Prometheus metrics format."""

    def test_all_metrics_have_help_lines(self):
        """Verify all v0.8.0 metrics have HELP descriptions."""
        # Make a request to populate metrics
        payload = {
            "load_kw": [100, 120, 110, 90],
            "pv_generation_kw": [50, 70, 80, 60],
            "energy_price_pln_kwh": 0.8,
            "constraints_config": {"max_capex_pln": 200000}
        }
        post_json(SIZING_PATH, payload)

        metrics_resp = requests.get(METRICS_URL)
        metrics_text = metrics_resp.text

        # Check for HELP lines for v0.8.0 metrics
        assert "# HELP bess_sizing_constraints_requests_total" in metrics_text
        assert "# HELP bess_pareto_frontier_requests_total" in metrics_text

    def test_all_metrics_have_type_lines(self):
        """Verify all v0.8.0 metrics have TYPE declarations."""
        # Make a request to populate metrics
        payload = {
            "load_kw": [100, 120, 110, 90],
            "pv_generation_kw": [50, 70, 80, 60],
            "energy_price_pln_kwh": 0.8,
            "constraints_config": {"max_capex_pln": 200000}
        }
        post_json(SIZING_PATH, payload)

        metrics_resp = requests.get(METRICS_URL)
        metrics_text = metrics_resp.text

        # Check for TYPE lines for v0.8.0 metrics
        assert "# TYPE bess_sizing_constraints_requests_total counter" in metrics_text
        assert "# TYPE bess_pareto_frontier_requests_total counter" in metrics_text
        assert "# TYPE bess_sizing_feasible_variants_count histogram" in metrics_text
        assert "# TYPE bess_pareto_frontier_size histogram" in metrics_text
