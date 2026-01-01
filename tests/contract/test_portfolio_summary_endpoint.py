"""
Contract tests for POST /api/bess-dispatch/portfolio/summary endpoint (v2.3.0).

Tests verify:
- Endpoint aggregates multiple run IDs into portfolio summary
- Total NPV equals sum of individual run NPVs (within tolerance)
- Mixed assumptions detection works correctly
- Error handling for invalid/missing run IDs
"""

import pytest
import requests
import time

BASE_URL = "http://localhost:8031"


def create_sizing_request(pv_kwp: float = 10.0, load_kw: float = 5.0):
    """Create a minimal sizing request."""
    return {
        "dispatch": {
            "battery": {
                "energy_kwh": 50.0,
                "power_kw": 25.0,
                "efficiency_charge": 0.95,
                "efficiency_discharge": 0.95,
                "soc_min_pct": 10,
                "soc_max_pct": 90,
                "soc_start_pct": 50,
            },
            "mode": "pv_surplus",
            "resolution": "hourly",
            "pv_generation_kw": [pv_kwp * 0.5] * 8760,
            "load_kw": [load_kw] * 8760,
        },
        "sizing": {
            "objective": "npv",
            "variants": ["small"],
        },
    }


def run_sizing_and_get_run_id(request: dict) -> str:
    """Run sizing and return the run_id."""
    response = requests.post(f"{BASE_URL}/sizing", json=request)
    assert response.status_code == 200, f"Sizing failed: {response.text}"
    data = response.json()
    # run_id may be in meta or cache_info
    run_id = data.get("meta", {}).get("run_id") or data.get("cache_info", {}).get("run_id")
    assert run_id, f"No run_id in response: {data}"
    return run_id


class TestPortfolioSummaryEndpoint:
    """Contract tests for portfolio summary endpoint."""

    def test_portfolio_summary_with_two_runs(self):
        """Test aggregating two sizing runs into portfolio."""
        # Create two sizing runs with different PV sizes
        run_id_1 = run_sizing_and_get_run_id(create_sizing_request(pv_kwp=10.0))
        run_id_2 = run_sizing_and_get_run_id(create_sizing_request(pv_kwp=20.0))

        # Request portfolio summary
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/portfolio/summary",
            json={"run_ids": [run_id_1, run_id_2]}
        )

        assert response.status_code == 200, f"Portfolio summary failed: {response.text}"
        data = response.json()

        # Verify structure
        assert "summary" in data
        assert "items" in data
        assert "errors" in data

        # Verify summary counts
        summary = data["summary"]
        assert summary["items_total"] == 2
        assert summary["items_ok"] == 2
        assert summary["items_error"] == 0

        # Verify items
        items = data["items"]
        assert len(items) == 2
        assert items[0]["run_id"] == run_id_1
        assert items[1]["run_id"] == run_id_2

    def test_portfolio_summary_total_npv_equals_sum(self):
        """Test that total_npv equals sum of individual run NPVs."""
        # Create two sizing runs
        run_id_1 = run_sizing_and_get_run_id(create_sizing_request(pv_kwp=15.0))
        run_id_2 = run_sizing_and_get_run_id(create_sizing_request(pv_kwp=25.0))

        # Get individual run NPVs
        run1 = requests.get(f"{BASE_URL}/runs/{run_id_1}").json()
        run2 = requests.get(f"{BASE_URL}/runs/{run_id_2}").json()

        npv1 = run1.get("recommended", {}).get("finance_summary", {}).get("npv_pln", 0)
        npv2 = run2.get("recommended", {}).get("finance_summary", {}).get("npv_pln", 0)

        # Request portfolio summary
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/portfolio/summary",
            json={"run_ids": [run_id_1, run_id_2]}
        )

        assert response.status_code == 200
        data = response.json()

        # Verify total NPV equals sum (within tolerance for floating point)
        total_npv = data["summary"]["total_npv_pln"]
        expected_npv = npv1 + npv2

        # Use relative tolerance for floating point comparison
        assert abs(total_npv - expected_npv) < 1.0, \
            f"Total NPV {total_npv} != sum {expected_npv}"

    def test_portfolio_summary_handles_missing_run_id(self):
        """Test that missing run IDs are reported as errors."""
        # Create one valid run
        run_id_valid = run_sizing_and_get_run_id(create_sizing_request())

        # Request with one valid and one invalid run_id
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/portfolio/summary",
            json={"run_ids": [run_id_valid, "nonexistent-run-id-12345"]}
        )

        assert response.status_code == 200
        data = response.json()

        # Verify counts
        assert data["summary"]["items_total"] == 2
        assert data["summary"]["items_ok"] == 1
        assert data["summary"]["items_error"] == 1

        # Verify error is reported
        assert len(data["errors"]) == 1
        assert data["errors"][0]["run_id"] == "nonexistent-run-id-12345"
        assert "not found" in data["errors"][0]["error"].lower()

    def test_portfolio_summary_with_labels_and_tags(self):
        """Test that labels and tags are included in response."""
        run_id_1 = run_sizing_and_get_run_id(create_sizing_request())
        run_id_2 = run_sizing_and_get_run_id(create_sizing_request())

        # Request with labels and tags
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/portfolio/summary",
            json={
                "run_ids": [run_id_1, run_id_2],
                "labels": {
                    run_id_1: "Site A",
                    run_id_2: "Site B",
                },
                "tags": {
                    run_id_1: ["region:north", "type:industrial"],
                    run_id_2: ["region:south", "type:commercial"],
                },
            }
        )

        assert response.status_code == 200
        data = response.json()

        # Verify labels are in items
        items = {item["run_id"]: item for item in data["items"]}
        assert items[run_id_1]["label"] == "Site A"
        assert items[run_id_2]["label"] == "Site B"
        assert "region:north" in items[run_id_1]["tags"]
        assert "region:south" in items[run_id_2]["tags"]

    def test_portfolio_summary_top_items_by_npv(self):
        """Test that top items by NPV are returned."""
        # Create multiple runs
        run_ids = []
        for i in range(3):
            run_id = run_sizing_and_get_run_id(
                create_sizing_request(pv_kwp=10.0 + i * 5)
            )
            run_ids.append(run_id)

        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/portfolio/summary",
            json={"run_ids": run_ids}
        )

        assert response.status_code == 200
        data = response.json()

        # Verify top_items_by_npv is present and sorted
        top_items = data["summary"]["top_items_by_npv"]
        assert len(top_items) <= 5
        assert len(top_items) == 3  # We only have 3 runs

        # Verify they're sorted by NPV descending
        npvs = [item["npv_pln"] for item in top_items]
        assert npvs == sorted(npvs, reverse=True)

    def test_portfolio_summary_empty_run_ids_rejected(self):
        """Test that empty run_ids list is rejected."""
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/portfolio/summary",
            json={"run_ids": []}
        )

        # Should be rejected with 422 (validation error)
        assert response.status_code == 422


class TestPortfolioSummaryVersions:
    """Tests for version/assumptions tracking in portfolio."""

    def test_single_assumptions_version_not_mixed(self):
        """Test that same assumptions version is not flagged as mixed."""
        run_id_1 = run_sizing_and_get_run_id(create_sizing_request())
        run_id_2 = run_sizing_and_get_run_id(create_sizing_request())

        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/portfolio/summary",
            json={"run_ids": [run_id_1, run_id_2]}
        )

        assert response.status_code == 200
        data = response.json()

        # Same engine version = not mixed
        assert data["summary"]["mixed_assumptions"] is False
        # Should have exactly one version
        assert len(data["summary"]["assumptions_versions"]) <= 1
