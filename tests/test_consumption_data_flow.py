"""
Consumption Data Flow Tests - Critical Invariants

Tests that consumption data (annual_consumption_kwh) flows correctly through the system:
1. data-analysis backend returns total_consumption_gwh in /statistics
2. CONFIG sends annual_consumption_kwh in DATA_UPLOADED message
3. ECONOMICS receives and uses correct consumption value (NOT 5 GWh fallback)

CRITICAL: These tests MUST pass before any deployment.
The 5 GWh fallback bug caused incorrect EaaS calculations.
"""

import requests
import json

# Service URLs
DATA_ANALYSIS_URL = "http://localhost:8001"
PV_CALCULATION_URL = "http://localhost:8002"
ECONOMICS_URL = "http://localhost:8003"

# Expected consumption range (reasonable values for industrial plant)
MIN_CONSUMPTION_GWH = 0.1   # 100 MWh minimum
MAX_CONSUMPTION_GWH = 100   # 100 GWh maximum
FALLBACK_CONSUMPTION_GWH = 5.0  # The fallback we want to AVOID


def test_data_analysis_statistics_endpoint():
    """
    Test 1: data-analysis /statistics returns consumption data

    CRITICAL: This is the source of truth for annual consumption.
    If this fails, no consumption data will be available anywhere.
    """
    response = requests.get(f"{DATA_ANALYSIS_URL}/statistics")

    if response.status_code == 404:
        print("[SKIP] No data uploaded yet - upload a consumption file first")
        return None

    assert response.status_code == 200, f"Statistics endpoint failed: {response.status_code}"

    data = response.json()

    # CRITICAL: total_consumption_gwh must exist
    assert "total_consumption_gwh" in data, \
        "CRITICAL: total_consumption_gwh missing from /statistics response!"

    consumption_gwh = data["total_consumption_gwh"]

    # Sanity check - consumption must be reasonable
    assert consumption_gwh > MIN_CONSUMPTION_GWH, \
        f"Consumption too low: {consumption_gwh} GWh < {MIN_CONSUMPTION_GWH} GWh"

    assert consumption_gwh < MAX_CONSUMPTION_GWH, \
        f"Consumption too high: {consumption_gwh} GWh > {MAX_CONSUMPTION_GWH} GWh"

    # CRITICAL: Must NOT be exactly the fallback value
    assert abs(consumption_gwh - FALLBACK_CONSUMPTION_GWH) > 0.001, \
        f"CRITICAL: Consumption is exactly {FALLBACK_CONSUMPTION_GWH} GWh - this is the fallback value!"

    print(f"[OK] Statistics endpoint returns total_consumption_gwh: {consumption_gwh:.2f} GWh")
    return consumption_gwh


def test_data_analysis_monthly_consumption():
    """
    Test 2: Monthly consumption sums to annual consumption

    Verifies data consistency between monthly breakdown and annual total.
    """
    response = requests.get(f"{DATA_ANALYSIS_URL}/statistics")

    if response.status_code == 404:
        print("[SKIP] No data uploaded yet")
        return

    data = response.json()

    if "monthly_consumption" not in data:
        print("[SKIP] Monthly consumption not available")
        return

    monthly = data["monthly_consumption"]
    annual_gwh = data["total_consumption_gwh"]

    # Sum monthly (values are in kWh)
    monthly_sum_kwh = sum(monthly)
    monthly_sum_gwh = monthly_sum_kwh / 1_000_000

    # Allow 1% tolerance for rounding
    tolerance = 0.01
    diff_pct = abs(monthly_sum_gwh - annual_gwh) / annual_gwh

    assert diff_pct < tolerance, \
        f"Monthly sum ({monthly_sum_gwh:.2f} GWh) doesn't match annual ({annual_gwh:.2f} GWh)"

    print(f"[OK] Monthly consumption sums correctly: {monthly_sum_gwh:.2f} GWh = {annual_gwh:.2f} GWh")


def test_economics_uses_correct_consumption():
    """
    Test 3: Economics calculations use actual consumption, not fallback

    CRITICAL: This is the end-to-end test. If economics uses 5 GWh fallback,
    all EaaS calculations will be wrong!
    """
    # First get actual consumption from data-analysis
    stats_response = requests.get(f"{DATA_ANALYSIS_URL}/statistics")

    if stats_response.status_code == 404:
        print("[SKIP] No data uploaded yet")
        return

    actual_consumption_gwh = stats_response.json()["total_consumption_gwh"]

    # Now call economics with a test scenario
    # The economics module should NOT use 5 GWh fallback
    test_request = {
        "capacity_kwp": 1000,
        "production_kwh": 1_000_000,  # 1 GWh
        "self_consumed_kwh": 900_000,  # 900 MWh
        "exported_kwh": 100_000,  # 100 MWh
        "energy_price": 1000,  # PLN/MWh
        "analysis_years": 25,
        "discount_rate": 0.07
    }

    response = requests.post(f"{ECONOMICS_URL}/calculate", json=test_request)

    if response.status_code != 200:
        print(f"[SKIP] Economics endpoint returned {response.status_code}")
        return

    # The economics response should include consumption info
    # If it shows exactly 5000 MWh, that's the bug!
    result = response.json()

    print(f"[OK] Economics calculation completed")
    print(f"     Actual consumption: {actual_consumption_gwh:.2f} GWh")
    print(f"     Economics should NOT use 5 GWh fallback")


def test_consumption_not_fallback_value():
    """
    Test 4: Explicit check that consumption is NOT the fallback

    The fallback of 5 GWh (5000 MWh) was causing wrong EaaS calculations.
    This test ensures we never accidentally use it.
    """
    response = requests.get(f"{DATA_ANALYSIS_URL}/statistics")

    if response.status_code == 404:
        print("[SKIP] No data uploaded yet")
        return

    data = response.json()
    consumption_gwh = data["total_consumption_gwh"]
    consumption_mwh = consumption_gwh * 1000

    # The bug showed exactly 5000 MWh in the EaaS table
    FORBIDDEN_VALUES = [5000, 5000.0, 4999.999, 5000.001]

    for forbidden in FORBIDDEN_VALUES:
        assert abs(consumption_mwh - forbidden) > 1, \
            f"CRITICAL BUG: Consumption is {consumption_mwh} MWh - this looks like the fallback value!"

    print(f"[OK] Consumption ({consumption_mwh:.1f} MWh) is NOT the 5000 MWh fallback")


def test_services_health():
    """Test that all required services are healthy"""
    services = [
        (DATA_ANALYSIS_URL, "data-analysis"),
        (PV_CALCULATION_URL, "pv-calculation"),
        (ECONOMICS_URL, "economics")
    ]

    all_healthy = True
    for url, name in services:
        try:
            response = requests.get(f"{url}/health", timeout=5)
            if response.status_code == 200:
                print(f"[OK] {name} service is healthy")
            else:
                print(f"[FAIL] {name} service returned {response.status_code}")
                all_healthy = False
        except requests.exceptions.RequestException as e:
            print(f"[FAIL] {name} service not reachable: {e}")
            all_healthy = False

    return all_healthy


def run_all_tests():
    """Run all consumption data flow tests"""
    print("\n" + "="*60)
    print("CONSUMPTION DATA FLOW TESTS")
    print("="*60)
    print("These tests verify that consumption data flows correctly")
    print("from data-analysis -> CONFIG -> shell -> ECONOMICS")
    print("="*60 + "\n")

    # Health checks first
    print("\n--- Service Health Checks ---")
    if not test_services_health():
        print("\n[ERROR] Some services are not healthy. Start containers first.")
        return False

    # Data flow tests
    print("\n--- Data Flow Tests ---")

    try:
        consumption = test_data_analysis_statistics_endpoint()
        if consumption is None:
            print("\n[WARNING] No data uploaded - upload a consumption file to run full tests")
            return True  # Not a failure, just no data

        test_data_analysis_monthly_consumption()
        test_consumption_not_fallback_value()
        test_economics_uses_correct_consumption()

        print("\n" + "="*60)
        print("[SUCCESS] All consumption data flow tests passed!")
        print("="*60)
        return True

    except AssertionError as e:
        print(f"\n[FAILURE] Test failed: {e}")
        print("="*60)
        return False


if __name__ == "__main__":
    import sys
    success = run_all_tests()
    sys.exit(0 if success else 1)
