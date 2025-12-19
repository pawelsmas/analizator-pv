"""
Test script to compare BESS sizing between pv-calculation and profile-analysis services.
Uses identical parameters to identify any differences in methodology.
"""
import requests
import json
import numpy as np

# API endpoints
PV_CALCULATION_URL = "http://localhost:8002"
PROFILE_ANALYSIS_URL = "http://localhost:8040"

# Common test parameters (same for both services)
TEST_PARAMS = {
    # PV parameters
    "pv_capacity_kwp": 11950,  # Wariant C
    "latitude": 52.0,
    "longitude": 21.0,

    # BESS economic parameters (from Settings)
    "capex_per_kwh": 1500,
    "capex_per_kw": 300,
    "opex_pct_per_year": 1.5,
    "roundtrip_efficiency": 0.90,
    "lifetime_years": 15,

    # Degradation model (two-phase)
    "degradation_year1_pct": 3.0,
    "degradation_pct_per_year": 2.0,
    "auxiliary_loss_pct_per_day": 0.1,

    # NPV parameters
    "discount_rate": 0.07,
    "project_years": 25,
    "energy_price_plnmwh": 851,
}

def generate_synthetic_data(hours=8760):
    """Generate synthetic consumption and PV production data for testing.

    Creates data that will generate SIGNIFICANT PV surplus during day to make BESS useful.
    """
    from datetime import datetime, timedelta

    np.random.seed(42)  # Reproducible

    # Consumption: industrial profile with night-heavy pattern
    # Lower during day (when PV is producing), higher at night
    # This creates surplus during day that BESS can capture
    t = np.arange(hours)
    hour_of_day = t % 24
    day_of_year = t // 24

    # Day pattern: LOWER during day (9-16), HIGHER at night
    # This creates significant surplus during peak PV hours
    daily_pattern = np.where(
        (hour_of_day >= 9) & (hour_of_day <= 16),
        0.3,  # Very low during peak PV hours (creates surplus!)
        0.8   # Normal at other times
    )
    weekly_pattern = np.where((t // 24) % 7 < 5, 1.0, 0.5)  # Much lower on weekends

    # Base consumption ~2500 kW average (lower than PV peak!)
    consumption = 2500 * daily_pattern * weekly_pattern
    consumption += np.random.normal(0, 100, hours)  # Less noise
    consumption = np.maximum(consumption, 200)  # Min 200 kW

    # PV production: REALISTIC based on capacity
    # Peak production ~ 0.9 * capacity at noon in summer
    # Annual yield ~1100 kWh/kWp

    # Solar elevation approximation
    solar_factor = np.maximum(0, np.sin(np.pi * (hour_of_day - 6) / 12))
    # Stronger seasonal variation for Poland (lat 52)
    seasonal_factor = 0.4 + 0.6 * np.sin(2 * np.pi * (day_of_year - 80) / 365)
    seasonal_factor = np.maximum(seasonal_factor, 0.2)

    pv_profile = solar_factor * seasonal_factor  # kWh per kWp per hour
    pv_production = pv_profile * TEST_PARAMS["pv_capacity_kwp"]

    # Add cloud variation (less aggressive)
    cloud_factor = 0.8 + 0.2 * np.random.random(hours)
    pv_production *= cloud_factor

    # Generate timestamps (2023-01-01 00:00 to 2023-12-31 23:00)
    start_date = datetime(2023, 1, 1, 0, 0, 0)
    timestamps = [(start_date + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S") for i in range(hours)]

    return consumption.tolist(), pv_production.tolist(), pv_profile.tolist(), timestamps

def test_pv_calculation_bess_sizing(consumption, pv_profile, timestamps):
    """Test BESS sizing via pv-calculation service."""
    print("\n" + "="*60)
    print("TEST 1: pv-calculation auto_size_bess_lite")
    print("="*60)

    # Build request for pv-calculation
    request = {
        "pv_config": {
            "type": "ground_s",
            "latitude": TEST_PARAMS["latitude"],
            "longitude": TEST_PARAMS["longitude"],
            "tilt": 35,
            "azimuth": 180,
            "pv_yield": 1100,
            "dc_ac_ratio": 1.35,
            "energy_price": TEST_PARAMS["energy_price_plnmwh"],
            "discount_rate": TEST_PARAMS["discount_rate"]
        },
        "consumption": consumption,
        "timestamps": timestamps,
        "capacity_min": TEST_PARAMS["pv_capacity_kwp"],
        "capacity_max": TEST_PARAMS["pv_capacity_kwp"],
        "capacity_step": 500,
        "bess_config": {
            "enabled": True,
            "mode": "light",
            "duration": "auto",
            "roundtrip_efficiency": TEST_PARAMS["roundtrip_efficiency"],
            "soc_min": 0.10,
            "soc_max": 0.90,
            "capex_per_kwh": TEST_PARAMS["capex_per_kwh"],
            "capex_per_kw": TEST_PARAMS["capex_per_kw"],
            "opex_pct_per_year": TEST_PARAMS["opex_pct_per_year"],
            "lifetime_years": TEST_PARAMS["lifetime_years"],
            "degradation_year1_pct": TEST_PARAMS["degradation_year1_pct"],
            "degradation_pct_per_year": TEST_PARAMS["degradation_pct_per_year"],
            "auxiliary_loss_pct_per_day": TEST_PARAMS["auxiliary_loss_pct_per_day"]
        }
    }

    try:
        response = requests.post(f"{PV_CALCULATION_URL}/analyze", json=request, timeout=120)
        if response.status_code != 200:
            print(f"ERROR: {response.status_code} - {response.text[:500]}")
            return None

        result = response.json()

        # Extract BESS sizing from the single scenario
        scenarios = result.get("scenarios", [])
        if scenarios:
            scenario = scenarios[0]
            bess_power = scenario.get("bess_power_kw", 0)
            bess_energy = scenario.get("bess_energy_kwh", 0)
            bess_discharged = scenario.get("bess_discharged_kwh", 0)

            print(f"\nRESULT from pv-calculation:")
            print(f"  PV Capacity: {scenario.get('capacity', 0)} kWp")
            print(f"  BESS Power: {bess_power:.0f} kW")
            print(f"  BESS Energy: {bess_energy:.0f} kWh")
            print(f"  Duration: {bess_energy/bess_power:.1f}h" if bess_power > 0 else "  Duration: N/A")
            print(f"  Annual Discharge: {bess_discharged/1000:.1f} MWh")
            print(f"  Self-consumed: {scenario.get('self_consumed', 0)/1000:.1f} MWh")
            print(f"  Autoconsumption: {scenario.get('auto_consumption_pct', 0):.1f}%")

            return {
                "source": "pv-calculation",
                "bess_power_kw": bess_power,
                "bess_energy_kwh": bess_energy,
                "annual_discharge_kwh": bess_discharged,
                "autoconsumption_pct": scenario.get("auto_consumption_pct", 0)
            }

    except Exception as e:
        print(f"ERROR calling pv-calculation: {e}")
        return None

def test_profile_analysis_bess_sizing(consumption, pv_production):
    """Test BESS sizing via profile-analysis service."""
    print("\n" + "="*60)
    print("TEST 2: profile-analysis Pareto optimization")
    print("="*60)

    # Build request for profile-analysis
    request = {
        "pv_generation_kwh": pv_production,
        "load_kwh": consumption,
        "pv_capacity_kwp": TEST_PARAMS["pv_capacity_kwp"],
        "energy_price_plnmwh": TEST_PARAMS["energy_price_plnmwh"],
        "bess_capex_per_kwh": TEST_PARAMS["capex_per_kwh"],
        "bess_capex_per_kw": TEST_PARAMS["capex_per_kw"],
        "bess_efficiency": TEST_PARAMS["roundtrip_efficiency"],
        "discount_rate": TEST_PARAMS["discount_rate"],
        "project_years": TEST_PARAMS["project_years"],
        "pareto_points": 15,  # More points for better resolution
        "use_pypsa_optimizer": True,  # Use PyPSA for consistency

        # Degradation and OPEX parameters (same as pv-calculation)
        "bess_degradation_year1_pct": TEST_PARAMS["degradation_year1_pct"],
        "bess_degradation_pct_per_year": TEST_PARAMS["degradation_pct_per_year"],
        "bess_auxiliary_loss_pct_per_day": TEST_PARAMS["auxiliary_loss_pct_per_day"],
        "bess_opex_pct_per_year": TEST_PARAMS["opex_pct_per_year"],

        # Disable extra features for fair comparison
        "peak_shaving_enabled": False,
        "price_arbitrage_enabled": False
    }

    try:
        response = requests.post(f"{PROFILE_ANALYSIS_URL}/analyze", json=request, timeout=120)
        if response.status_code != 200:
            print(f"ERROR: {response.status_code} - {response.text[:500]}")
            return None

        result = response.json()

        # Extract recommended BESS (Best NPV from Pareto)
        recommended_power = result.get("recommended_bess_power_kw", 0)
        recommended_energy = result.get("recommended_bess_energy_kwh", 0)
        recommended_discharge = result.get("recommended_bess_annual_discharge_mwh", 0) * 1000  # MWh -> kWh

        print(f"\nRESULT from profile-analysis (Best NPV):")
        print(f"  BESS Power: {recommended_power:.0f} kW")
        print(f"  BESS Energy: {recommended_energy:.0f} kWh")
        print(f"  Duration: {recommended_energy/recommended_power:.1f}h" if recommended_power > 0 else "  Duration: N/A")
        print(f"  Annual Discharge: {recommended_discharge/1000:.1f} MWh")

        # Show Pareto frontier
        pareto = result.get("pareto_frontier", [])
        if pareto:
            print(f"\n  Pareto Frontier ({len(pareto)} points):")
            print(f"  {'Power':>8} | {'Energy':>8} | {'NPV':>10} | {'Cycles':>8} | {'Payback':>8}")
            print(f"  {'-'*8} | {'-'*8} | {'-'*10} | {'-'*8} | {'-'*8}")
            for p in pareto:
                print(f"  {p['power_kw']:>8.0f} | {p['energy_kwh']:>8.0f} | {p['npv_mln_pln']:>10.2f} | {p['annual_cycles']:>8.1f} | {p['payback_years']:>8.1f}")

        # Direct consumption (PV only, without BESS)
        direct_consumption = result.get("direct_consumption_mwh", 0)

        return {
            "source": "profile-analysis",
            "bess_power_kw": recommended_power,
            "bess_energy_kwh": recommended_energy,
            "annual_discharge_kwh": recommended_discharge,
            "direct_consumption_mwh": direct_consumption,
            "pareto_frontier": pareto
        }

    except Exception as e:
        print(f"ERROR calling profile-analysis: {e}")
        import traceback
        traceback.print_exc()
        return None

def compare_results(result1, result2):
    """Compare results from both services."""
    print("\n" + "="*60)
    print("COMPARISON")
    print("="*60)

    if not result1 or not result2:
        print("Cannot compare - one or both results missing")
        return

    print(f"\n{'Metric':<25} | {'pv-calculation':>15} | {'profile-analysis':>15} | {'Diff':>10}")
    print("-"*75)

    # Compare BESS sizing
    power_diff = result1["bess_power_kw"] - result2["bess_power_kw"]
    energy_diff = result1["bess_energy_kwh"] - result2["bess_energy_kwh"]
    discharge_diff = result1["annual_discharge_kwh"] - result2["annual_discharge_kwh"]

    print(f"{'BESS Power (kW)':<25} | {result1['bess_power_kw']:>15.0f} | {result2['bess_power_kw']:>15.0f} | {power_diff:>+10.0f}")
    print(f"{'BESS Energy (kWh)':<25} | {result1['bess_energy_kwh']:>15.0f} | {result2['bess_energy_kwh']:>15.0f} | {energy_diff:>+10.0f}")
    print(f"{'Annual Discharge (kWh)':<25} | {result1['annual_discharge_kwh']:>15.0f} | {result2['annual_discharge_kwh']:>15.0f} | {discharge_diff:>+10.0f}")

    # Duration
    dur1 = result1["bess_energy_kwh"] / result1["bess_power_kw"] if result1["bess_power_kw"] > 0 else 0
    dur2 = result2["bess_energy_kwh"] / result2["bess_power_kw"] if result2["bess_power_kw"] > 0 else 0
    print(f"{'Duration (h)':<25} | {dur1:>15.1f} | {dur2:>15.1f} | {dur1-dur2:>+10.1f}")

    print("\n" + "="*60)
    print("ANALYSIS")
    print("="*60)

    if abs(energy_diff) < 100:
        print("\n[OK] BESS sizes are very similar (diff < 100 kWh)")
    else:
        pct_diff = (energy_diff / result2["bess_energy_kwh"]) * 100 if result2["bess_energy_kwh"] > 0 else 0
        print(f"\n[DIFF] BESS sizes differ by {abs(energy_diff):.0f} kWh ({abs(pct_diff):.1f}%)")

        if result1["bess_energy_kwh"] > result2["bess_energy_kwh"]:
            print("  -> pv-calculation recommends LARGER BESS")
            print("  -> This is because pv-calculation sizes BESS to capture MORE surplus")
            print("  -> profile-analysis sizes BESS for BEST NPV (smaller, higher ROI)")
        else:
            print("  -> profile-analysis recommends LARGER BESS")

    # Check if Pareto shows why
    if "pareto_frontier" in result2 and result2["pareto_frontier"]:
        pareto = result2["pareto_frontier"]
        best_npv = max(pareto, key=lambda p: p["npv_mln_pln"])
        largest = max(pareto, key=lambda p: p["energy_kwh"])

        print(f"\n  Pareto analysis:")
        print(f"    Best NPV point: {best_npv['energy_kwh']:.0f} kWh, NPV = {best_npv['npv_mln_pln']:.2f} mln PLN")
        print(f"    Largest tested: {largest['energy_kwh']:.0f} kWh, NPV = {largest['npv_mln_pln']:.2f} mln PLN")

        if largest["energy_kwh"] < result1["bess_energy_kwh"]:
            print(f"\n  [!] pv-calculation size ({result1['bess_energy_kwh']:.0f} kWh) is OUTSIDE Pareto range!")
            print(f"      profile-analysis max tested was {largest['energy_kwh']:.0f} kWh")
            print(f"      This explains the difference - different search ranges!")

def get_pvgis_pv_data():
    """
    Get ACTUAL PV production data from pv-calculation (which uses PVGIS).
    This ensures both services use IDENTICAL PV data.
    """
    from datetime import datetime, timedelta
    hours = 8760
    np.random.seed(42)
    t = np.arange(hours)
    hour_of_day = t % 24

    # Industrial profile with NIGHT-HEAVY consumption
    # This creates scenario where BESS is profitable (charge from PV surplus during day,
    # discharge at night when there's no PV)
    daily_pattern = np.where(
        (hour_of_day >= 8) & (hour_of_day <= 16),
        0.4,  # LOW during peak PV hours (creates surplus!)
        1.0   # HIGH at night (needs stored energy)
    )
    weekly_pattern = np.where((t // 24) % 7 < 5, 1.0, 0.5)

    # Lower base load to create more surplus
    consumption = 2000 * daily_pattern * weekly_pattern
    consumption += np.random.normal(0, 100, hours)
    consumption = np.maximum(consumption, 200)
    consumption = consumption.tolist()

    # Generate timestamps
    start_date = datetime(2023, 1, 1, 0, 0, 0)
    timestamps = [(start_date + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S") for i in range(hours)]

    # Call pv-calculation WITHOUT BESS to get the pv_profile from PVGIS
    print("\nStep 1: Getting PVGIS-based PV profile from pv-calculation...")

    request = {
        "pv_config": {
            "type": "ground_s",
            "latitude": TEST_PARAMS["latitude"],
            "longitude": TEST_PARAMS["longitude"],
            "tilt": 35,
            "azimuth": 180,
            "pv_yield": 1100,
            "dc_ac_ratio": 1.35,
            "energy_price": TEST_PARAMS["energy_price_plnmwh"],
            "discount_rate": TEST_PARAMS["discount_rate"]
        },
        "consumption": consumption,
        "timestamps": timestamps,
        "capacity_min": TEST_PARAMS["pv_capacity_kwp"],
        "capacity_max": TEST_PARAMS["pv_capacity_kwp"],
        "capacity_step": 500,
        "bess_config": None  # No BESS - just get PV data
    }

    try:
        response = requests.post(f"{PV_CALCULATION_URL}/analyze", json=request, timeout=120)
        if response.status_code != 200:
            print(f"ERROR: {response.status_code} - {response.text[:500]}")
            return None, None, None, None

        result = response.json()

        # Extract pv_profile (per kWp)
        pv_profile = result.get("pv_profile", [])
        if not pv_profile:
            print("ERROR: No pv_profile in response")
            return None, None, None, None

        # Calculate absolute PV production (kWh)
        pv_production = [p * TEST_PARAMS["pv_capacity_kwp"] for p in pv_profile]

        annual_pv = sum(pv_production) / 1000
        annual_load = sum(consumption) / 1000
        print(f"  PV production from PVGIS: {annual_pv:.1f} MWh/year")
        print(f"  Load consumption: {annual_load:.1f} MWh/year")
        print(f"  PV/Load ratio: {annual_pv/annual_load*100:.1f}%")

        # Calculate surplus
        surplus = [max(0, pv - load) for pv, load in zip(pv_production, consumption)]
        annual_surplus = sum(surplus) / 1000
        print(f"  Annual surplus: {annual_surplus:.1f} MWh")

        return consumption, pv_production, pv_profile, timestamps

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None, None


def main():
    print("="*60)
    print("BESS SIZING COMPARISON TEST")
    print("="*60)
    print("Using IDENTICAL data from PVGIS for both services")
    print("="*60)
    print(f"\nTest parameters:")
    for key, value in TEST_PARAMS.items():
        print(f"  {key}: {value}")

    # Get REAL data from pv-calculation (PVGIS-based)
    consumption, pv_production, pv_profile, timestamps = get_pvgis_pv_data()

    if consumption is None:
        print("\nFailed to get PVGIS data. Exiting.")
        return

    annual_consumption = sum(consumption) / 1000  # MWh
    annual_production = sum(pv_production) / 1000  # MWh
    print(f"\nData for comparison:")
    print(f"  Annual consumption: {annual_consumption:.1f} MWh")
    print(f"  Annual PV production: {annual_production:.1f} MWh")
    print(f"  PV/Load ratio: {annual_production/annual_consumption*100:.1f}%")

    # Test both services with IDENTICAL data
    result1 = test_pv_calculation_bess_sizing(consumption, pv_profile, timestamps)
    result2 = test_profile_analysis_bess_sizing(consumption, pv_production)

    # Compare
    compare_results(result1, result2)

    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)

if __name__ == "__main__":
    main()
