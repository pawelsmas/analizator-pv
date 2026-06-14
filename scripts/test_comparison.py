"""
Comparison test: ANALIZATOR PV (bess-dispatch) vs pagra-galileo parameters.

Uses identical input parameters from pagra-galileo's excel_pagra.xlsx:
- Battery: 12 MWh / 6 MW, efficiency 85%, SoC 5%-95%
- Connection: 6 MW import, 6 MW export, 6.5 MW contracted
- Tariff: Tauron A23
- Capacity fee: 219.3 PLN/MWh (= 0.2193 PLN/kWh)
- Margins: buy +20 PLN/MWh fixed, sell -5%

Generates synthetic 8760h profiles (1 year, 1h interval).
"""

import json
import math
import sys
import time
import numpy as np
import requests

API_URL = "http://localhost:8031"
HOURS = 8760  # 1 year, hourly


def generate_load_profile(peak_kw=6000, hours=HOURS):
    """Generate realistic industrial load profile (kW)."""
    t = np.arange(hours)
    hour_of_day = t % 24
    day_of_year = t // 24

    # Base load ~40% of peak
    base = peak_kw * 0.40

    # Daily pattern: ramp up 6-8, peak 9-17, ramp down 17-20
    daily = np.zeros(hours)
    for h in range(24):
        if 6 <= h < 8:
            daily[hour_of_day == h] = 0.3 * (h - 6) / 2
        elif 8 <= h < 17:
            daily[hour_of_day == h] = 0.3
        elif 17 <= h < 20:
            daily[hour_of_day == h] = 0.3 * (20 - h) / 3
        else:
            daily[hour_of_day == h] = 0.0

    # Weekend reduction (~60% of weekday)
    weekday = (day_of_year % 7) < 5
    weekend_factor = np.where(weekday, 1.0, 0.6)

    # Seasonal variation (higher in winter)
    seasonal = 1.0 + 0.15 * np.cos(2 * np.pi * (day_of_year - 15) / 365)

    load = (base + peak_kw * daily) * weekend_factor[np.arange(hours)] * seasonal
    # Add noise
    load += np.random.normal(0, peak_kw * 0.02, hours)
    load = np.clip(load, peak_kw * 0.1, peak_kw)
    return load


def generate_pv_profile(panel_kw=8000, hours=HOURS):
    """Generate PV profile for South-facing 20deg tilt in Poland (~50N)."""
    t = np.arange(hours)
    hour_of_day = t % 24
    day_of_year = t // 24

    pv = np.zeros(hours)
    for i in range(hours):
        doy = day_of_year[i]
        hod = hour_of_day[i]

        # Solar declination
        decl = 23.45 * math.sin(math.radians(360 / 365 * (doy - 81)))
        # Hour angle
        ha = (hod - 12) * 15
        # Solar elevation
        lat = 50.0
        elev = math.degrees(math.asin(
            math.sin(math.radians(lat)) * math.sin(math.radians(decl)) +
            math.cos(math.radians(lat)) * math.cos(math.radians(decl)) * math.cos(math.radians(ha))
        ))

        if elev > 0:
            # Clear-sky irradiance (simplified)
            am = 1.0 / (math.sin(math.radians(elev)) + 0.50572 * (elev + 6.07995) ** -1.6364)
            am = min(am, 40)
            dni = 1361 * 0.7 ** (am ** 0.678)  # Simplified Meinel model

            # Tilt factor (south, 20 deg)
            tilt = 20
            cos_inc = (math.sin(math.radians(elev)) * math.cos(math.radians(tilt)) +
                       math.cos(math.radians(elev)) * math.sin(math.radians(tilt)) *
                       math.cos(math.radians(ha)))
            cos_inc = max(cos_inc, 0)

            irr = dni * cos_inc
            # Temperature derating, inverter efficiency
            pv[i] = panel_kw * (irr / 1000) * 0.85 * 0.97
        else:
            pv[i] = 0.0

    # Cloud cover variation
    cloud = np.random.uniform(0.5, 1.0, hours)
    pv *= cloud
    # Clip to inverter power (6 MW)
    pv = np.clip(pv, 0, 6000)
    return pv


def generate_rdn_prices(hours=HOURS):
    """Generate synthetic RDN-like prices (PLN/MWh)."""
    t = np.arange(hours)
    hour_of_day = t % 24
    day_of_year = t // 24

    # Base price ~350 PLN/MWh
    base = 350.0
    # Daily shape
    daily_shape = {
        0: -80, 1: -100, 2: -110, 3: -115, 4: -100, 5: -60,
        6: -20, 7: 30, 8: 60, 9: 80, 10: 90, 11: 85,
        12: 70, 13: 60, 14: 50, 15: 55, 16: 70, 17: 100,
        18: 120, 19: 110, 20: 80, 21: 40, 22: 0, 23: -40,
    }
    prices = np.array([base + daily_shape[h % 24] for h in range(hours)])

    # Seasonal (higher in winter)
    seasonal = 1.0 + 0.2 * np.cos(2 * np.pi * (day_of_year - 15) / 365)
    prices *= seasonal

    # Weekend discount
    weekday = (day_of_year % 7) < 5
    prices *= np.where(weekday, 1.0, 0.75)

    # Noise
    prices += np.random.normal(0, 30, hours)
    prices = np.clip(prices, 50, 800)
    return prices


def test_dispatch():
    """Run dispatch test with pagra-galileo-equivalent parameters."""
    np.random.seed(42)

    print("Generating synthetic profiles...")
    load = generate_load_profile(peak_kw=6000)
    pv = generate_pv_profile(panel_kw=8000)
    prices = generate_rdn_prices()

    # Convert prices from PLN/MWh to PLN/kWh for buy/sell
    # pagra-galileo adds: kogeneracja 3, OZE 3.5, jakosciowa 31.12, mocowa 219.3, akcyza 5, marza_kupna 20 = 281.92 PLN/MWh
    surcharges = 3 + 3.5 + 31.12 + 219.3 + 5 + 20  # = 281.92 PLN/MWh
    buy_prices = (prices + surcharges) / 1000  # PLN/kWh
    # Sell: RDN * (1-5%) - swiadectwa 4 PLN/MWh
    sell_prices = (prices * 0.95 - 4) / 1000  # PLN/kWh

    print(f"Load:  min={load.min():.0f}, max={load.max():.0f}, mean={load.mean():.0f} kW")
    print(f"PV:    min={pv.min():.0f}, max={pv.max():.0f}, mean={pv.mean():.0f} kW")
    print(f"Buy:   min={buy_prices.min():.4f}, max={buy_prices.max():.4f}, mean={buy_prices.mean():.4f} PLN/kWh")
    print(f"Sell:  min={sell_prices.min():.4f}, max={sell_prices.max():.4f}, mean={sell_prices.mean():.4f} PLN/kWh")

    # Build dispatch request matching pagra-galileo params
    request_data = {
        "pv_generation_kw": pv.tolist(),
        "load_kw": load.tolist(),
        "interval_minutes": 60,
        "topology": "pv_load",
        "battery_power_kw": 6000,
        "battery_energy_kwh": 12000,
        "roundtrip_efficiency": 0.85,
        "soc_min": 0.05,
        "soc_max": 0.95,
        "soc_initial": 0.5,
        "mode": "stacked",
        "peak_limit_kw": 6500,
        "arbitrage_config": {
            "buy_price": buy_prices.tolist(),
            "sell_price": sell_prices.tolist(),
        },
        "start_date": "2025-01-01",
        "optimize_capacity_fee": True,
    }

    print(f"\nSending dispatch request ({len(pv)} steps)...")
    t0 = time.time()
    try:
        resp = requests.post(f"{API_URL}/dispatch", json=request_data, timeout=300)
        elapsed = time.time() - t0
        print(f"Response: {resp.status_code} in {elapsed:.1f}s")

        if resp.status_code == 200:
            result = resp.json()
            print_dispatch_results(result, buy_prices, sell_prices, load, pv)
        else:
            print(f"ERROR: {resp.text[:500]}")
            return None
    except Exception as e:
        print(f"Request failed: {e}")
        return None

    return result


def print_dispatch_results(result, buy_prices, sell_prices, load, pv):
    """Print and analyze dispatch results."""
    # Response is flat, not nested under 'summary'
    r = result

    print("\n" + "=" * 60)
    print("DISPATCH RESULTS (ANALIZATOR PV / bess-dispatch)")
    print("=" * 60)

    # Energy metrics
    print(f"\n--- Energy flows ---")
    print(f"Total load:           {r.get('total_load_kwh', 0)/1000:.1f} MWh")
    print(f"Total PV generation:  {r.get('total_pv_kwh', 0)/1000:.1f} MWh")
    print(f"Grid import:          {r.get('total_grid_import_kwh', 0)/1000:.1f} MWh")
    print(f"Grid export:          {r.get('total_grid_export_kwh', 0)/1000:.1f} MWh")
    print(f"Battery charge:       {r.get('total_charge_kwh', 0)/1000:.1f} MWh")
    print(f"Battery discharge:    {r.get('total_discharge_kwh', 0)/1000:.1f} MWh")

    # Cost metrics
    print(f"\n--- Costs ---")
    print(f"Baseline cost:        {r.get('baseline_cost_pln', 0)/1000:.1f} k PLN")
    print(f"Project cost:         {r.get('project_cost_pln', 0)/1000:.1f} k PLN")
    print(f"Annual savings:       {r.get('annual_savings_pln', 0)/1000:.1f} k PLN")

    savings_bd = r.get("savings_breakdown", {})
    if savings_bd:
        for k, v in savings_bd.items():
            if isinstance(v, (int, float)):
                print(f"  {k}: {v:.0f} PLN")

    # Battery metrics
    print(f"\n--- Battery ---")
    charge = r.get('total_charge_kwh', 0)
    discharge = r.get('total_discharge_kwh', 0)
    energy_kwh = r.get('battery_energy_kwh', 12000)
    efc = (charge + discharge) / 2 / energy_kwh if energy_kwh > 0 else 0
    print(f"EFC (equiv. full cycles): {efc:.1f}")
    print(f"Peak grid import (new): {r.get('new_peak_kw', 0):.0f} kW")
    print(f"Peak reduction:       {r.get('peak_reduction_kw', 0):.0f} kW ({r.get('peak_reduction_pct', 0):.1f}%)")

    # Compare vs pagra-galileo expectations
    print("\n" + "=" * 60)
    print("PAGRA-GALILEO PARAMETER COMPARISON")
    print("=" * 60)
    print(f"Battery:      12 MWh / 6 MW (match: energy={r.get('battery_energy_kwh', 0)/1000:.0f} MWh)")
    print(f"Efficiency:   85% roundtrip (match: configured)")
    print(f"SoC range:    5-95% (match: configured)")
    print(f"Peak limit:   6.5 MW (configured)")
    print(f"Connection:   6 MW import / 6 MW export (configured)")
    print(f"Tariff:       Tauron A23")
    print(f"Cap fee rate: 219.3 PLN/MWh = 0.2193 PLN/kWh")

    # Sanity checks
    print("\n--- Sanity Checks ---")
    total_load = r.get('total_load_kwh', 0)
    total_pv = r.get('total_pv_kwh', 0)
    grid_import = r.get('total_grid_import_kwh', 0)
    grid_export = r.get('total_grid_export_kwh', 0)
    charge = r.get('total_charge_kwh', 0)
    discharge = r.get('total_discharge_kwh', 0)

    # Energy balance: load = pv_direct + grid_import + discharge - charge - export
    # Or: grid_import + pv = load + grid_export + charge - discharge + losses
    balance = grid_import + total_pv - total_load - grid_export - charge + discharge
    print(f"Energy balance residual: {balance/1000:.2f} MWh (should be ~0, losses accounted)")

    # EFC reasonableness for 12 MWh battery
    if efc > 0:
        annual_throughput = efc * 12  # MWh
        print(f"Annual throughput:    {annual_throughput:.0f} MWh ({efc:.0f} cycles)")
        if efc < 50:
            print(f"  WARNING: Low cycle count - battery may be underutilized")
        elif efc > 500:
            print(f"  WARNING: High cycle count - may degrade battery faster")
        else:
            print(f"  OK: Reasonable cycle count")

    return True


def test_sizing():
    """Run sizing test with matching parameters."""
    np.random.seed(42)

    load = generate_load_profile(peak_kw=6000)
    pv = generate_pv_profile(panel_kw=8000)
    prices = generate_rdn_prices()

    surcharges = 3 + 3.5 + 31.12 + 219.3 + 5 + 20
    buy_prices = (prices + surcharges) / 1000
    sell_prices = (prices * 0.95 - 4) / 1000

    request_data = {
        "pv_generation_kw": pv.tolist(),
        "load_kw": load.tolist(),
        "interval_minutes": 60,
        "topology": "pv_load",
        "battery_power_kw": 6000,
        "roundtrip_efficiency": 0.85,
        "soc_min": 0.05,
        "soc_max": 0.95,
        "mode": "stacked",
        "peak_limit_kw": 6500,
        "durations_h": [2],  # 12 MWh = 6MW * 2h
        "finance": {
            "capex_per_kwh": 1200,
            "capex_per_kw": 200,
            "opex_pct": 2.0,
            "discount_rate": 8.0,
            "project_lifetime_years": 15,
            "bess_lifetime_years": 15,
            "bess_degradation_pct_per_year": 2.5,
        },
        "arbitrage_config": {
            "buy_price": buy_prices.tolist(),
            "sell_price": sell_prices.tolist(),
        },
        "start_date": "2025-01-01",
        "optimize_capacity_fee": True,
    }

    print(f"\nSending sizing request...")
    t0 = time.time()
    try:
        resp = requests.post(f"{API_URL}/sizing", json=request_data, timeout=600)
        elapsed = time.time() - t0
        print(f"Response: {resp.status_code} in {elapsed:.1f}s")

        if resp.status_code == 200:
            result = resp.json()
            print_sizing_results(result)
        else:
            print(f"ERROR: {resp.text[:500]}")
    except Exception as e:
        print(f"Request failed: {e}")


def print_sizing_results(result):
    """Print sizing results."""
    print("\n" + "=" * 60)
    print("SIZING RESULTS")
    print("=" * 60)

    print(f"Recommended: {result.get('recommended_variant', 'N/A')}")
    print(f"  Power:  {result.get('recommended_power_kw', 0)/1000:.1f} MW")
    print(f"  Energy: {result.get('recommended_energy_kwh', 0)/1000:.1f} MWh")
    print(f"  Reason: {result.get('recommended_reason', 'N/A')}")

    variants = result.get("variants", [])
    for v in variants:
        print(f"\n--- Variant: {v.get('variant_label', v.get('variant', 'N/A'))} ---")
        print(f"  Power:    {v.get('power_kw', 0)/1000:.1f} MW")
        print(f"  Energy:   {v.get('energy_kwh', 0)/1000:.1f} MWh")
        print(f"  Duration: {v.get('duration_h', 0)}h")
        print(f"  CAPEX:    {v.get('capex_pln', 0)/1000:.0f} k PLN")
        print(f"  Savings:  {v.get('annual_savings_pln', 0)/1000:.1f} k PLN/yr")
        print(f"  NPV:      {v.get('npv_pln', 0)/1000:.0f} k PLN")
        irr = v.get('irr_pct')
        print(f"  IRR:      {irr:.1f}%" if irr else "  IRR:      N/A")
        print(f"  Payback:  {v.get('simple_payback_years', 'N/A'):.1f} years")

        deg = v.get("degradation", {})
        if deg:
            print(f"  EFC:      {deg.get('efc_total', 0):.0f} cycles/yr")
            print(f"  Throughput: {deg.get('throughput_total_mwh', 0):.1f} MWh/yr")


if __name__ == "__main__":
    print("=" * 60)
    print("COMPARISON TEST: ANALIZATOR PV vs pagra-galileo")
    print("=" * 60)
    print(f"\nUsing pagra-galileo parameters from excel_pagra.xlsx:")
    print(f"  Battery: 12 MWh / 6 MW, eff=85%, SoC=5-95%")
    print(f"  Connection: 6 MW import, 6 MW export, 6.5 MW contracted")
    print(f"  Tariff: Tauron A23")
    print(f"  PV: 8 MWp South 20deg")
    print(f"  Load: ~6 MW industrial")

    # Check health
    try:
        r = requests.get(f"{API_URL}/health", timeout=5)
        print(f"\nbess-dispatch status: {r.json()['status']}")
    except:
        print("\nERROR: bess-dispatch not running at localhost:8031")
        sys.exit(1)

    # Run dispatch test
    print("\n\n>>> TEST 1: DISPATCH <<<")
    result = test_dispatch()

    # Run sizing test
    if result:
        print("\n\n>>> TEST 2: SIZING <<<")
        test_sizing()
