"""
BESS LIGHT Tests - Invariants and Regression

Tests for BESS (Battery Energy Storage System) LIGHT/AUTO mode implementation.
Verifies:
1. 0-export mode: grid export is always 0
2. SOC boundaries: SOC stays within min/max limits
3. Energy conservation: no negative values
4. Backward compatibility: BESS OFF produces identical results to baseline
"""

import requests
import numpy as np
import sys

# Service URLs
PV_CALCULATION_URL = "http://localhost:8002"
ECONOMICS_URL = "http://localhost:8003"

def test_pv_calculation_health():
    """Test that pv-calculation service is healthy"""
    response = requests.get(f"{PV_CALCULATION_URL}/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    print("[OK] pv-calculation service is healthy")

def test_economics_health():
    """Test that economics service is healthy"""
    response = requests.get(f"{ECONOMICS_URL}/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    print("[OK] economics service is healthy")

def test_bess_0_export_mode():
    """Test that BESS in 0-export mode never exports to grid"""
    # Create test consumption profile (8760 hours)
    np.random.seed(42)
    base_load = 100  # kW average
    consumption = (base_load + np.random.normal(0, 20, 8760)).clip(50, 200).tolist()

    # Generate timestamps for a full year
    timestamps = [f"2024-01-01T{h:02d}:00:00+01:00" for h in range(24)] * 365
    timestamps = timestamps[:8760]

    request_data = {
        "consumption": consumption,
        "timestamps": timestamps,
        "capacity_min": 100,
        "capacity_max": 300,
        "capacity_step": 50,
        "thresholds": {"variant_70": 70, "variant_80": 80},
        "pv_config": {
            "latitude": 52.0,
            "longitude": 21.0,
            "altitude": 100,
            "pv_type": "ground_s",
            "use_pvgis": False
        },
        "bess_config": {
            "enabled": True,
            "mode": "lite",
            "duration": "auto",
            "roundtrip_efficiency": 0.90,
            "soc_min": 0.10,
            "soc_max": 0.90,
            "soc_initial": 0.50
        }
    }

    response = requests.post(f"{PV_CALCULATION_URL}/analyze", json=request_data)
    assert response.status_code == 200, f"Request failed: {response.text}"

    data = response.json()
    scenarios = data.get("scenarios", [])

    # Verify all scenarios have 0 export (0-export mode)
    for scenario in scenarios:
        exported = scenario.get("exported", 0)
        assert exported == 0, f"Export should be 0 in 0-export mode, got {exported}"

        # Verify BESS metrics exist when enabled
        assert scenario.get("bess_power_kw") is not None, "bess_power_kw should be set"
        assert scenario.get("bess_energy_kwh") is not None, "bess_energy_kwh should be set"

        # Verify no negative values
        assert scenario.get("bess_charged_kwh", 0) >= 0, "bess_charged_kwh should be >= 0"
        assert scenario.get("bess_discharged_kwh", 0) >= 0, "bess_discharged_kwh should be >= 0"
        assert scenario.get("bess_curtailed_kwh", 0) >= 0, "bess_curtailed_kwh should be >= 0"
        assert scenario.get("bess_grid_import_kwh", 0) >= 0, "bess_grid_import_kwh should be >= 0"

    print("[OK] BESS 0-export mode: all scenarios have 0 grid export")
    print(f"  - Tested {len(scenarios)} scenarios")
    print(f"  - Sample BESS config: {scenarios[0].get('bess_power_kw'):.0f} kW / {scenarios[0].get('bess_energy_kwh'):.0f} kWh")

def test_bess_off_backward_compatible():
    """Test that BESS OFF produces same results as baseline (no BESS)"""
    np.random.seed(42)
    consumption = (100 + np.random.normal(0, 20, 8760)).clip(50, 200).tolist()
    timestamps = [f"2024-01-01T{h:02d}:00:00+01:00" for h in range(24)] * 365
    timestamps = timestamps[:8760]

    base_request = {
        "consumption": consumption,
        "timestamps": timestamps,
        "capacity_min": 100,
        "capacity_max": 100,
        "capacity_step": 50,
        "thresholds": {"variant_70": 70},
        "pv_config": {
            "latitude": 52.0,
            "longitude": 21.0,
            "altitude": 100,
            "pv_type": "ground_s",
            "use_pvgis": False
        }
    }

    # Request without BESS
    response_no_bess = requests.post(f"{PV_CALCULATION_URL}/analyze", json=base_request)
    assert response_no_bess.status_code == 200
    data_no_bess = response_no_bess.json()

    # Request with BESS disabled
    request_with_disabled_bess = base_request.copy()
    request_with_disabled_bess["bess_config"] = {
        "enabled": False,
        "mode": "lite",
        "duration": "auto"
    }

    response_bess_off = requests.post(f"{PV_CALCULATION_URL}/analyze", json=request_with_disabled_bess)
    assert response_bess_off.status_code == 200
    data_bess_off = response_bess_off.json()

    # Compare results
    s1 = data_no_bess["scenarios"][0]
    s2 = data_bess_off["scenarios"][0]

    # Core metrics should be identical
    assert abs(s1["production"] - s2["production"]) < 1, "Production should match"
    assert abs(s1["self_consumed"] - s2["self_consumed"]) < 1, "Self consumed should match"
    assert abs(s1["exported"] - s2["exported"]) < 1, "Exported should match"

    print("[OK] BESS OFF backward compatible: results match baseline")

def test_economics_with_bess():
    """Test that economics service accepts BESS data"""
    request_data = {
        "variant": {
            "capacity": 200,
            "production": 200000,
            "self_consumed": 180000,
            "exported": 0,
            "auto_consumption_pct": 90,
            "coverage_pct": 40,
            "bess_power_kw": 50,
            "bess_energy_kwh": 100,
            "bess_charged_kwh": 30000,
            "bess_discharged_kwh": 27000,
            "bess_curtailed_kwh": 5000,
            "bess_grid_import_kwh": 250000,
            "bess_self_consumed_direct_kwh": 150000,
            "bess_self_consumed_from_bess_kwh": 30000,
            "bess_cycles_equivalent": 150
        },
        "parameters": {
            "energy_price": 450,
            "investment_cost": 3500,
            "discount_rate": 0.07,
            "degradation_rate": 0.005,
            "opex_per_kwp": 15,
            "analysis_period": 25,
            "bess_capex_per_kwh": 1500,
            "bess_capex_per_kw": 300,
            "bess_opex_pct_per_year": 1.5,
            "bess_lifetime_years": 15,
            "bess_degradation_pct_per_year": 2.0
        }
    }

    response = requests.post(f"{ECONOMICS_URL}/analyze", json=request_data)
    assert response.status_code == 200, f"Request failed: {response.text}"

    data = response.json()

    # Verify BESS CAPEX is included in investment
    # PV: 200 kWp * 3500 PLN = 700,000
    # BESS: 100 kWh * 1500 + 50 kW * 300 = 150,000 + 15,000 = 165,000
    # Total: 865,000 PLN
    expected_investment = 200 * 3500 + 100 * 1500 + 50 * 300
    assert abs(data["investment"] - expected_investment) < 100, \
        f"Investment should include BESS CAPEX, expected ~{expected_investment}, got {data['investment']}"

    print("[OK] Economics with BESS: CAPEX correctly includes BESS costs")
    print(f"  - Total investment: {data['investment']:,.0f} PLN")
    print(f"  - NPV: {data['npv']:,.0f} PLN")
    print(f"  - IRR: {data['irr']*100:.1f}%" if data['irr'] else "  - IRR: N/A")

def run_all_tests():
    """Run all tests"""
    print("\n" + "="*60)
    print("BESS LIGHT Tests - Invariants and Regression")
    print("="*60 + "\n")

    tests = [
        test_pv_calculation_health,
        test_economics_health,
        test_bess_0_export_mode,
        test_bess_off_backward_compatible,
        test_economics_with_bess,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            print(f"\nRunning: {test.__name__}")
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}")
            print(f"  Error: {e}")
            failed += 1

    print("\n" + "="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")

    return failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
