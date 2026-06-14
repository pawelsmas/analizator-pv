"""
Comparison test: BTM-only dispatch vs BTM + Ancillary Services stacked.

Demonstrates the revenue uplift from virtualized battery multi-service optimization.
Matches pagra-galileo parameters: 12 MWh / 6 MW, 85% eff, Tauron A23.
"""

import requests
import numpy as np
import json
import sys

BASE_URL = "http://localhost:8031"

# -- Common parameters (matching pagra-galileo) --
BATTERY_POWER_KW = 6000
BATTERY_ENERGY_KWH = 12000
EFFICIENCY = 0.85
HOURS = 8760

# Generate synthetic annual profiles
np.random.seed(42)
hours = np.arange(HOURS)
day_of_year = hours // 24
hour_of_day = hours % 24

# Industrial load: 3-6 MW with daily pattern + seasonal variation
seasonal = 1 + 0.15 * np.sin(2 * np.pi * day_of_year / 365 - np.pi / 2)
daily = np.where(
    (hour_of_day >= 6) & (hour_of_day <= 22),
    1 + 0.4 * np.sin((hour_of_day - 6) / 16 * np.pi),
    0.5,
)
load_kw = (3500 * seasonal * daily + np.random.normal(0, 200, HOURS)).clip(1000, 6500)

# PV: 8 MWp, seasonal + daily pattern
sun_elevation = np.maximum(0, np.sin((hour_of_day - 6) / 12 * np.pi))
seasonal_pv = 0.5 + 0.5 * np.sin(2 * np.pi * (day_of_year - 80) / 365)
cloud_factor = np.random.uniform(0.6, 1.0, HOURS)
pv_kw = (8000 * sun_elevation * seasonal_pv.clip(0.2, 1.0) * cloud_factor).clip(0)

# Prices: Tauron A23-like with ToU
peak_hours = (hour_of_day >= 7) & (hour_of_day <= 21)
buy_prices = np.where(peak_hours, 0.45, 0.25) + np.random.normal(0, 0.02, HOURS)
buy_prices = buy_prices.clip(0.15, 0.70)
sell_prices = buy_prices * 0.8


def test_btm_only():
    """Test 1: Existing dispatch — stacked mode (peak + PV surplus + arbitrage)."""
    print("=" * 70)
    print("TEST 1: BTM-ONLY DISPATCH (existing stacked mode)")
    print("=" * 70)

    payload = {
        "mode": "stacked",
        "battery_power_kw": BATTERY_POWER_KW,
        "battery_energy_kwh": BATTERY_ENERGY_KWH,
        "roundtrip_efficiency": EFFICIENCY,
        "soc_min": 0.05,
        "soc_max": 0.95,
        "load_kw": load_kw.tolist(),
        "pv_generation_kw": pv_kw.tolist(),
        "peak_limit_kw": 4500,
        "reserve_fraction": 0.3,
        "import_price_pln_mwh": 450.0,
        "export_price_pln_mwh": 0.0,
        "demand_charge_pln_kw_month": 30.0,
    }

    r = requests.post(f"{BASE_URL}/dispatch", json=payload, timeout=120)
    if r.status_code != 200:
        print(f"  ERROR: {r.status_code} — {r.text[:200]}")
        return None

    data = r.json()
    deg = data.get("degradation", {})
    result = {
        "total_load_mwh": data.get("total_load_kwh", 0) / 1000,
        "total_pv_mwh": data.get("total_pv_kwh", 0) / 1000,
        "self_consumption_pct": data.get("self_consumption_pct", 0),
        "peak_reduction_pct": data.get("peak_reduction_pct", 0),
        "total_savings_pln": data.get("annual_savings_pln", 0),
        "efc": deg.get("efc_total", 0),
        "baseline_cost_pln": data.get("baseline_cost_pln", 0),
        "project_cost_pln": data.get("project_cost_pln", 0),
    }

    print(f"  Load:              {result['total_load_mwh']:,.0f} MWh/year")
    print(f"  PV:                {result['total_pv_mwh']:,.0f} MWh/year")
    print(f"  Self-consumption:  {result['self_consumption_pct']:.1f}%")
    print(f"  Peak reduction:    {result['peak_reduction_pct']:.1f}%")
    print(f"  Baseline cost:     {result['baseline_cost_pln']:,.0f} PLN/year")
    print(f"  Project cost:      {result['project_cost_pln']:,.0f} PLN/year")
    print(f"  BTM savings:       {result['total_savings_pln']:,.0f} PLN/year")
    print(f"  EFC:               {result['efc']:.1f} cycles/year")
    return result


def test_ancillary_stacked():
    """Test 2: Ancillary services — LP co-optimization (our new module)."""
    print("\n" + "=" * 70)
    print("TEST 2: BTM + ANCILLARY SERVICES (LP co-optimization)")
    print("=" * 70)

    payload = {
        "battery_power_kw": BATTERY_POWER_KW,
        "battery_energy_kwh": BATTERY_ENERGY_KWH,
        "roundtrip_efficiency": EFFICIENCY,
        "load_kw": load_kw.tolist(),
        "pv_generation_kw": pv_kw.tolist(),
        "buy_prices_pln_kwh": buy_prices.tolist(),
        "sell_prices_pln_kwh": sell_prices.tolist(),
        "peak_limit_kw": 4500,
        "services_enabled": [
            "aFRR_up", "aFRR_down", "mFRR_up",
            "peak_shaving", "energy_arbitrage",
        ],
        "market_year": 2026,
        "aggregator_margin_pct": 20.0,
        "optimize_mode": "year",
        "dt_hours": 1.0,
    }

    r = requests.post(
        f"{BASE_URL}/api/bess-dispatch/ancillary-services/optimize",
        json=payload, timeout=600,
    )
    if r.status_code != 200:
        print(f"  ERROR: {r.status_code} — {r.text[:300]}")
        return None

    data = r.json()
    if data.get("status") != "optimal":
        print(f"  FAILED: {data.get('warnings', [])}")
        return None

    rev = data["revenue"]
    met = data["metrics"]
    alloc = data.get("allocation", {})
    stacked = data.get("stacked_total", {})

    result = {
        "btm_savings_pln": rev.get("btm_savings_pln", 0),
        "ancillary_gross_pln": rev.get("ancillary_gross_pln", 0),
        "ancillary_net_pln": rev.get("ancillary_net_pln", 0),
        "aggregator_fees_pln": rev.get("aggregator_fees_pln", 0),
        "degradation_cost_pln": rev.get("degradation_cost_pln", 0),
        "total_annual_pln": rev.get("total_annual_revenue_pln", 0),
        "total_efc": met.get("total_efc", 0),
        "services": rev.get("services", {}),
    }

    print(f"  BTM savings:         {result['btm_savings_pln']:>12,.0f} PLN/year")
    print(f"  Ancillary (gross):   {result['ancillary_gross_pln']:>12,.0f} PLN/year")
    print(f"  Aggregator fees:     {result['aggregator_fees_pln']:>12,.0f} PLN/year")
    print(f"  Ancillary (net):     {result['ancillary_net_pln']:>12,.0f} PLN/year")
    print(f"  Degradation cost:    {result['degradation_cost_pln']:>12,.0f} PLN/year")
    print(f"  -----------------------------------------")
    print(f"  TOTAL ANNUAL:        {result['total_annual_pln']:>12,.0f} PLN/year")
    print(f"  Total EFC:           {result['total_efc']:>12.1f} cycles/year")

    print("\n  Revenue per service:")
    for svc, detail in result["services"].items():
        if isinstance(detail, dict):
            net = detail.get("net_pln", 0)
            gross = detail.get("gross_pln", 0)
            print(f"    {svc:20s} gross={gross:>10,.0f}  net={net:>10,.0f} PLN")

    print(f"\n  Allocation:")
    for svc, detail in alloc.items():
        if isinstance(detail, dict):
            rev_pln = detail.get("revenue_pln", 0)
            share = detail.get("share_pct", 0)
            print(f"    {svc:20s} {rev_pln:>10,.0f} PLN ({share:.1f}%)")

    return result


def compare_results(btm, stacked):
    """Print comparison table."""
    print("\n" + "=" * 70)
    print("COMPARISON: BTM-only vs BTM + Ancillary Stacked")
    print("=" * 70)

    btm_rev = btm["total_savings_pln"]
    stacked_rev = stacked["total_annual_pln"]
    uplift = stacked_rev - btm_rev
    uplift_pct = (uplift / btm_rev * 100) if btm_rev > 0 else float("inf")

    print(f"""
  +------------------------------+--------------+--------------+
  | Metric                       |   BTM-only   |  BTM+Ancil   |
  +------------------------------+--------------+--------------|
  | BTM savings [PLN/year]       | {btm_rev:>12,.0f} | {stacked['btm_savings_pln']:>12,.0f} |
  | Ancillary net [PLN/year]     |            0 | {stacked['ancillary_net_pln']:>12,.0f} |
  | Total revenue [PLN/year]     | {btm_rev:>12,.0f} | {stacked_rev:>12,.0f} |
  | Revenue uplift [PLN/year]    |            — | {uplift:>+12,.0f} |
  | Revenue uplift [%]           |            — | {uplift_pct:>+11.0f}% |
  | EFC [cycles/year]            | {btm['efc']:>12.1f} | {stacked['total_efc']:>12.1f} |
  +------------------------------+--------------+--------------+
""")

    print("  KEY INSIGHT:")
    if uplift > 0:
        print(f"  Ancillary services add {uplift:,.0f} PLN/year (+{uplift_pct:.0f}%) to BTM-only revenue.")
        print(f"  This is the value of battery virtualization and LP co-optimization.")
    else:
        print(f"  BTM-only is already optimal for this configuration.")

    # pagra-galileo comparison
    print(f"\n  vs pagra-galileo (fixed allocation):")
    print(f"  Our LP dynamically re-allocates capacity every hour,")
    print(f"  while pagra-galileo uses fixed MWh quotas per service.")
    print(f"  This dynamic allocation is the key competitive advantage.")


if __name__ == "__main__":
    print("ANALIZATOR PV — Revenue Stacking Comparison Test")
    print(f"Battery: {BATTERY_POWER_KW/1000:.0f} MW / {BATTERY_ENERGY_KWH/1000:.0f} MWh, eff={EFFICIENCY*100:.0f}%")
    print(f"PV: 8 MWp, Load: ~3.5-6 MW industrial, Year: 8760h")
    print()

    btm_result = test_btm_only()
    stacked_result = test_ancillary_stacked()

    if btm_result and stacked_result:
        compare_results(btm_result, stacked_result)
    else:
        print("\n  Some tests failed. Check errors above.")
        sys.exit(1)
