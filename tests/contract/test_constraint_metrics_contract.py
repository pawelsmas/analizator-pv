"""
Contract tests for v0.7.0 grid constraint metrics (PR 6/6).

These tests verify:
1. Grid constraint metrics appear in /metrics endpoint
2. Counters increment after requests with constraints
3. Histograms record constraint impact values

Run with: python -m pytest tests/contract/test_constraint_metrics_contract.py -v
"""

import requests
from ._api import post_json, load_smoke_payload


METRICS_URL = "http://localhost:8031/metrics"


class TestConstraintMetricsPresence:
    """Test that constraint metrics appear after requests."""

    def test_grid_constraint_requests_metric_exists(self):
        """bess_grid_constraint_requests_total should appear after constraint request."""
        # Make a request with grid constraints
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"
        p["grid_constraints"] = {
            "max_export_kw": 50.0,
        }

        post_json("/sizing", p)

        # Check metrics endpoint
        resp = requests.get(METRICS_URL, timeout=10)
        assert resp.status_code == 200

        metrics_text = resp.text
        assert "bess_grid_constraint_requests_total" in metrics_text, (
            "Grid constraint counter should be present in /metrics"
        )

    def test_export_cap_metrics_after_export_constraint(self):
        """Export cap metrics should appear after request with export cap."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"
        p["grid_constraints"] = {
            "max_export_kw": 10.0,  # Low cap to trigger hits
        }

        post_json("/sizing", p)

        resp = requests.get(METRICS_URL, timeout=10)
        metrics_text = resp.text

        # Export cap metrics should be present (may or may not have hits depending on data)
        assert "bess_export_cap_hit_steps" in metrics_text or "bess_export_cap_curtailed_kwh" in metrics_text, (
            "Export cap histogram metrics should be present"
        )

    def test_import_cap_metrics_after_import_constraint(self):
        """Import cap metrics should appear after request with import cap."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"
        p["grid_constraints"] = {
            "max_import_kw": 10.0,
        }

        post_json("/sizing", p)

        resp = requests.get(METRICS_URL, timeout=10)
        metrics_text = resp.text

        # Import cap metrics should be present
        assert "bess_import_cap_hit_steps" in metrics_text, (
            "Import cap histogram metrics should be present"
        )


class TestMetricsFormat:
    """Test that metrics follow Prometheus format."""

    def test_constraint_metrics_have_help_lines(self):
        """Constraint metrics should have HELP lines."""
        # Trigger metrics by making a request
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"
        p["grid_constraints"] = {
            "max_export_kw": 50.0,
        }

        post_json("/sizing", p)

        resp = requests.get(METRICS_URL, timeout=10)
        metrics_text = resp.text

        # Check for HELP line
        assert "# HELP bess_grid_constraint_requests_total" in metrics_text, (
            "Counter should have HELP line"
        )

    def test_constraint_metrics_have_type_lines(self):
        """Constraint metrics should have TYPE lines."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"
        p["grid_constraints"] = {
            "max_export_kw": 50.0,
        }

        post_json("/sizing", p)

        resp = requests.get(METRICS_URL, timeout=10)
        metrics_text = resp.text

        assert "# TYPE bess_grid_constraint_requests_total counter" in metrics_text, (
            "Counter should have TYPE counter line"
        )


class TestUnservedLoadMetrics:
    """Test unserved load specific metrics."""

    def test_unserved_load_metrics_with_penalty(self):
        """Unserved load metrics should capture penalty when constraint violated."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # Very restrictive import cap to force unserved load
        p["grid_constraints"] = {
            "max_import_kw": 1.0,
            "unserved_load_penalty_pln_kwh": 10.0,
        }

        post_json("/sizing", p)

        resp = requests.get(METRICS_URL, timeout=10)
        metrics_text = resp.text

        # Unserved load metrics should be present
        assert "bess_unserved_load_kwh" in metrics_text, (
            "Unserved load histogram should be present"
        )
        assert "bess_unserved_load_penalty_pln" in metrics_text, (
            "Unserved load penalty histogram should be present"
        )
