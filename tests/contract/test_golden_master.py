"""
Golden master tests for BESS sizing API.

These tests capture the current behavior (December 2025 baseline) and
verify future changes don't inadvertently break the API contract.

To update the golden master after intentional changes:
  pytest tests/contract/test_golden_master.py --update-golden
"""
import pytest
import requests
import json
import os
from pathlib import Path

# Golden master file location
GOLDEN_DIR = Path(__file__).parent / "golden"


def pytest_addoption(parser):
    """Add --update-golden option to pytest."""
    try:
        parser.addoption(
            "--update-golden",
            action="store_true",
            default=False,
            help="Update golden master files with current API responses",
        )
    except ValueError:
        # Option already registered
        pass


@pytest.fixture
def update_golden(request):
    """Check if --update-golden flag is set."""
    return request.config.getoption("--update-golden", default=False)


@pytest.fixture
def golden_dir():
    """Ensure golden directory exists."""
    GOLDEN_DIR.mkdir(exist_ok=True)
    return GOLDEN_DIR


class TestGoldenMaster:
    """Golden master tests for sizing API response structure."""

    def test_sizing_response_structure(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
        update_golden,
        golden_dir,
    ):
        """
        Golden master: Verify sizing response structure matches baseline.

        Checks:
        - All expected top-level keys present
        - Variant structure is consistent
        - savings_breakdown components exist
        """
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        # Extract structure (keys only, not values)
        structure = {
            "top_level_keys": sorted(data.keys()),
            "variant_keys": sorted(data["variants"][0].keys()) if data.get("variants") else [],
            "savings_breakdown_keys": sorted(
                data["variants"][0].get("savings_breakdown", {}).keys()
            )
            if data.get("variants")
            else [],
            "period_info_keys": sorted(data.get("period_info", {}).keys()),
        }

        golden_file = golden_dir / "sizing_response_structure.json"

        if update_golden:
            with open(golden_file, "w") as f:
                json.dump(structure, f, indent=2)
            pytest.skip("Updated golden master")
        else:
            if not golden_file.exists():
                # First run - create golden master
                with open(golden_file, "w") as f:
                    json.dump(structure, f, indent=2)
                print(f"Created golden master: {golden_file}")

            with open(golden_file) as f:
                expected = json.load(f)

            # Compare structures
            assert structure["top_level_keys"] == expected["top_level_keys"], (
                f"Top-level keys changed.\n"
                f"Expected: {expected['top_level_keys']}\n"
                f"Got: {structure['top_level_keys']}"
            )

            assert structure["variant_keys"] == expected["variant_keys"], (
                f"Variant keys changed.\n"
                f"Expected: {expected['variant_keys']}\n"
                f"Got: {structure['variant_keys']}"
            )

            assert structure["savings_breakdown_keys"] == expected["savings_breakdown_keys"], (
                f"savings_breakdown keys changed.\n"
                f"Expected: {expected['savings_breakdown_keys']}\n"
                f"Got: {structure['savings_breakdown_keys']}"
            )

    def test_net_savings_formula_consistency(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
        update_golden,
        golden_dir,
    ):
        """
        Golden master: Verify net savings calculation is consistent.

        Formula: net = energy + capacity + demand + arbitrage - degradation
        """
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        results = []
        for variant in data.get("variants", []):
            sb = variant.get("savings_breakdown", {})
            energy = sb.get("energy_savings_pln", 0)
            capacity = sb.get("capacity_fee_savings_pln", 0)
            demand = sb.get("demand_charge_savings_pln", 0)
            arbitrage = sb.get("arbitrage_savings_pln", 0)
            degradation = abs(sb.get("degradation_cost_pln", 0))
            net = sb.get("net_savings_pln", 0)

            calculated = energy + capacity + demand + arbitrage - degradation
            diff = abs(net - calculated)

            results.append({
                "variant": variant.get("variant", "unknown"),
                "net_from_api": round(net, 2),
                "calculated": round(calculated, 2),
                "difference": round(diff, 2),
                "formula_consistent": diff < 1.0,  # Allow 1 PLN tolerance
            })

        golden_file = golden_dir / "net_savings_formula.json"

        if update_golden:
            with open(golden_file, "w") as f:
                json.dump(results, f, indent=2)
            pytest.skip("Updated golden master")
        else:
            # Just verify formula is consistent for all variants
            for r in results:
                assert r["formula_consistent"], (
                    f"Variant {r['variant']}: net_savings formula mismatch. "
                    f"API={r['net_from_api']}, calculated={r['calculated']}, diff={r['difference']}"
                )

    def test_recommended_variant_is_highest_score(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """
        Golden master: Recommended variant must have highest score.

        This is a behavioral invariant that should never change.
        """
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        if not variants:
            pytest.skip("No variants returned")

        # Find recommended and highest score variants
        recommended = [v for v in variants if v.get("is_recommended", False)]
        assert len(recommended) == 1, "Exactly one variant should be recommended"

        highest_score = max(variants, key=lambda v: v.get("score", float("-inf")))

        assert recommended[0]["variant"] == highest_score["variant"], (
            f"Recommended variant {recommended[0]['variant']} (score={recommended[0]['score']:.2f}) "
            f"is not highest score variant {highest_score['variant']} (score={highest_score['score']:.2f})"
        )
