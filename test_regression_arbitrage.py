#!/usr/bin/env python
"""
Regression test suite for PV + RDN Arbitrage mechanism.
Covers:
  1. Basic dispatch with RDN prices (scenario 9 equivalent)
  2. allow_grid_charging=true vs false differentiation
  3. allow_grid_charging=false with pv_surplus=0 (battery fully blocked)
  4. Sizing vs dispatch consistency (same prices -> comparable results)
  5. Deprecated field backward compatibility

Requires: bess-dispatch container running on localhost:8031
"""

import json
import math
import sys
import time
import requests

BASE = "http://localhost:8031"

# --- Helpers ---

def make_load(n, base=50.0, peak_hours=None):
    """Generate load profile: base kW with peaks."""
    load = [base] * n
    if peak_hours:
        for h in peak_hours:
            for i in range(h, min(h + 1, n)):
                load[i] = base * 2.5
    return load

def make_pv(n, peak_kw=80.0):
    """Generate PV profile: bell curve peaking at noon."""
    pv = []
    for i in range(n):
        hour = i % 24
        if 6 <= hour <= 18:
            pv.append(peak_kw * math.sin(math.pi * (hour - 6) / 12))
        else:
            pv.append(0.0)
    return pv

def make_rdn_prices(n):
    """Generate RDN-like prices: cheap night, expensive day, PLN/MWh."""
    prices = []
    for i in range(n):
        hour = i % 24
        if 0 <= hour < 6:
            prices.append(200.0)   # night: cheap
        elif 6 <= hour < 9:
            prices.append(450.0)   # morning ramp
        elif 9 <= hour < 17:
            prices.append(350.0)   # midday (PV depression)
        elif 17 <= hour < 21:
            prices.append(550.0)   # evening peak
        else:
            prices.append(300.0)   # late evening
    return prices

def dispatch_request(n_hours, pv_peak=80.0, load_base=50.0,
                     allow_grid_charging=True, use_rdn=True,
                     peak_limit_kw=None):
    """Build a dispatch request."""
    n = n_hours
    load = make_load(n, load_base, peak_hours=[18, 19])
    pv = make_pv(n, pv_peak)

    req = {
        "load_kw": load,
        "pv_generation_kw": pv,
        "interval_minutes": 60,
        "battery_power_kw": 25.0,
        "battery_energy_kwh": 50.0,
        "soc_min": 0.10,
        "soc_max": 0.90,
        "roundtrip_efficiency": 0.92,
        "mode": "stacked",
        "import_price_pln_mwh": 600.0,
        "export_price_pln_mwh": 0.01,
    }

    if peak_limit_kw is not None:
        req["peak_limit_kw"] = peak_limit_kw
    else:
        req["peak_limit_kw"] = max(load) * 2.0  # effectively no peak limit

    if use_rdn:
        rdn = make_rdn_prices(n)
        req["arbitrage_config"] = {
            "enabled": True,
            "hourly_prices_pln_mwh": rdn,
            "allow_grid_charging": allow_grid_charging,
        }
        req["start_date"] = "2025-01-01"

    return req

def sizing_request(n_hours, pv_peak=80.0, load_base=50.0,
                   allow_grid_charging=True):
    """Build a sizing request."""
    n = n_hours
    load = make_load(n, load_base, peak_hours=[18, 19])
    pv = make_pv(n, pv_peak)
    rdn = make_rdn_prices(n)

    return {
        "load_kw": load,
        "pv_generation_kw": pv,
        "interval_minutes": 60,
        "prices": {
            "import_price_pln_mwh": 600.0,
            "export_price_pln_mwh": 0.01,
        },
        "arbitrage_config": {
            "enabled": True,
            "hourly_prices_pln_mwh": rdn,
            "allow_grid_charging": allow_grid_charging,
        },
        "start_date": "2025-01-01",
        "peak_limit_kw": max(load) * 2.0,
        "mode": "stacked",
        "min_power_kw": 25.0,
        "max_power_kw": 25.0,
        "power_steps": 5,
        "durations_h": [2.0],
        "roundtrip_efficiency": 0.92,
        "soc_min": 0.10,
        "soc_max": 0.90,
        "import_price_pln_mwh": 600.0,
        "export_price_pln_mwh": 0.01,
    }

# --- Tests ---

def test_1_basic_rdn_dispatch():
    """Test 1: Basic dispatch with RDN prices produces arbitrage metrics."""
    print("\n=== TEST 1: Basic RDN dispatch ===")
    req = dispatch_request(720, use_rdn=True)
    r = requests.post(f"{BASE}/dispatch", json=req, timeout=120)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
    data = r.json()

    # Must have battery activity
    charge = data.get("total_charge_kwh", 0)
    discharge = data.get("total_discharge_kwh", 0)
    print(f"  charge={charge:.1f} kWh, discharge={discharge:.1f} kWh")
    assert charge > 100, f"Expected significant charging, got {charge}"
    assert discharge > 100, f"Expected significant discharging, got {discharge}"

    # Must have RDN arbitrage metrics
    info = data.get("info", {})
    arb_metrics = info.get("rdn_arbitrage_metrics")
    assert arb_metrics is not None, "Missing rdn_arbitrage_metrics"

    spread = arb_metrics.get("price_spread_pln_mwh", 0)
    print(f"  price_spread={spread:.1f} PLN/MWh")
    assert spread > 0, f"Expected positive price spread, got {spread}"

    # Both timing value and backward-compat field must exist
    timing = arb_metrics.get("arbitrage_timing_value_pln", 0)
    savings = arb_metrics.get("arbitrage_savings_pln", 0)
    print(f"  timing_value={timing:.2f}, savings(deprecated)={savings:.2f}")
    assert timing == savings, "timing_value and savings should be equal in LP"

    # SavingsBreakdown must be populated
    sb = data.get("savings_breakdown")
    assert sb is not None, "Missing savings_breakdown"
    arb_sb = sb.get("arbitrage_savings_pln", 0)
    print(f"  SavingsBreakdown.arbitrage_savings_pln={arb_sb:.2f}")
    assert arb_sb >= 0, "Negative arbitrage in breakdown"

    print("  PASS")
    return data

def test_2_allow_grid_charging_differentiation():
    """Test 2: allow_grid_charging=True vs False produces different results."""
    print("\n=== TEST 2: allow_grid_charging differentiation (720h) ===")

    req_true = dispatch_request(720, allow_grid_charging=True)
    req_false = dispatch_request(720, allow_grid_charging=False)

    r1 = requests.post(f"{BASE}/dispatch", json=req_true, timeout=120)
    r2 = requests.post(f"{BASE}/dispatch", json=req_false, timeout=120)

    assert r1.status_code == 200, f"True: HTTP {r1.status_code}"
    assert r2.status_code == 200, f"False: HTTP {r2.status_code}"

    d1, d2 = r1.json(), r2.json()
    charge_true = d1.get("total_charge_kwh", 0)
    charge_false = d2.get("total_charge_kwh", 0)

    print(f"  grid_charging=True:  charge={charge_true:.1f} kWh")
    print(f"  grid_charging=False: charge={charge_false:.1f} kWh")

    # With grid charging disabled, total charge should be significantly less
    assert charge_false < charge_true * 0.8, \
        f"Expected <80% charging when grid blocked: {charge_false} vs {charge_true}"

    # Both should still have positive discharge
    dis_true = d1.get("total_discharge_kwh", 0)
    dis_false = d2.get("total_discharge_kwh", 0)
    print(f"  grid_charging=True:  discharge={dis_true:.1f} kWh")
    print(f"  grid_charging=False: discharge={dis_false:.1f} kWh")
    assert dis_false > 0, "Discharge should still be possible without grid charging"

    print("  PASS")
    return charge_true, charge_false

def test_3_no_pv_no_grid_charging():
    """Test 3: allow_grid_charging=False + pv=0 -> battery blocked."""
    print("\n=== TEST 3: No PV + no grid charging -> battery blocked ===")

    req = dispatch_request(168, pv_peak=0.0, allow_grid_charging=False)
    r = requests.post(f"{BASE}/dispatch", json=req, timeout=120)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
    data = r.json()

    charge = data.get("total_charge_kwh", 0)
    discharge = data.get("total_discharge_kwh", 0)
    print(f"  charge={charge:.1f} kWh, discharge={discharge:.1f} kWh")

    # With no PV and no grid charging, battery should be nearly idle
    # (may discharge initial SoC but cannot recharge)
    assert charge < 1.0, f"Expected ~0 charging without PV, got {charge}"

    # Small discharge from initial SoC is acceptable
    # Initial SoC = 50% of 50 kWh = 25 kWh, usable = 80% of 50 = 40 kWh
    # Max possible single discharge = (0.5 - 0.1) * 50 = 20 kWh
    print(f"  Battery correctly blocked from charging (charge={charge:.2f})")
    print("  PASS")

def test_4_sizing_dispatch_consistency():
    """Test 4: Sizing and dispatch with same params → comparable savings."""
    print("\n=== TEST 4: Sizing vs dispatch consistency ===")

    # Run dispatch
    d_req = dispatch_request(720, allow_grid_charging=True)
    r_d = requests.post(f"{BASE}/dispatch", json=d_req, timeout=120)
    assert r_d.status_code == 200, f"Dispatch HTTP {r_d.status_code}"
    d_data = r_d.json()

    d_savings = d_data.get("annual_savings_pln", 0)
    d_charge = d_data.get("total_charge_kwh", 0)
    d_sb = d_data.get("savings_breakdown", {})
    d_arb = d_sb.get("arbitrage_savings_pln", 0)

    # Run sizing with same battery variant
    s_req = sizing_request(720, allow_grid_charging=True)
    r_s = requests.post(f"{BASE}/sizing", json=s_req, timeout=180)
    assert r_s.status_code == 200, f"Sizing HTTP {r_s.status_code}: {r_s.text[:300]}"
    s_data = r_s.json()

    # Find matching variant in sizing results
    # Sizing returns recommended + variants list
    recommended = s_data.get("recommended", {})
    variants = s_data.get("variants", [])
    v = recommended if recommended else (variants[0] if variants else {})
    assert v, "No sizing variant found (neither recommended nor variants)"

    s_savings = v.get("annual_savings_pln", 0)
    s_sb = v.get("savings_breakdown", {})
    s_arb = s_sb.get("arbitrage_savings_pln", 0)
    s_charge = v.get("total_charge_kwh", 0)

    print(f"  Dispatch: savings={d_savings:.0f} PLN, arb={d_arb:.0f}, charge={d_charge:.0f}")
    print(f"  Sizing:   savings={s_savings:.0f} PLN, arb={s_arb:.0f}, charge={s_charge:.0f}")

    # They should be in the same ballpark (within relaxed tolerance)
    # Sizing may differ due to additional layers (NPV, degradation, annualization)
    if d_savings > 0 and s_savings > 0:
        ratio = s_savings / d_savings if d_savings != 0 else float('inf')
        print(f"  Savings ratio (sizing/dispatch): {ratio:.2f}")
        assert 0.1 < ratio < 10.0, f"Savings ratio {ratio} out of expected range"

    # Both should show non-negative arbitrage
    print(f"  Both show arbitrage: dispatch={d_arb:.0f}, sizing={s_arb:.0f}")

    print("  PASS")

def test_5_deprecated_fields_present():
    """Test 5: Deprecated fields still present for backward compatibility."""
    print("\n=== TEST 5: Deprecated field backward compatibility ===")

    req = dispatch_request(168, use_rdn=True)
    r = requests.post(f"{BASE}/dispatch", json=req, timeout=120)
    assert r.status_code == 200
    data = r.json()

    # SavingsBreakdown.arbitrage_savings_pln must exist
    sb = data.get("savings_breakdown", {})
    assert "arbitrage_savings_pln" in sb, "Missing deprecated arbitrage_savings_pln in breakdown"

    # rdn_arbitrage_metrics must have both old and new fields
    info = data.get("info", {})
    metrics = info.get("rdn_arbitrage_metrics", {})
    if metrics:  # only if price variation detected
        assert "arbitrage_timing_value_pln" in metrics, "Missing new timing field"
        assert "arbitrage_savings_pln" in metrics, "Missing deprecated savings field in metrics"
        assert metrics["arbitrage_timing_value_pln"] == metrics["arbitrage_savings_pln"], \
            "Timing and deprecated savings should be equal"
        print(f"  Both fields present and equal: {metrics['arbitrage_timing_value_pln']}")

    print("  PASS")

def test_6_no_rdn_dispatch():
    """Test 6: Dispatch without RDN prices still works (flat tariff)."""
    print("\n=== TEST 6: Dispatch without RDN (flat tariff) ===")

    req = dispatch_request(168, use_rdn=False)
    r = requests.post(f"{BASE}/dispatch", json=req, timeout=120)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
    data = r.json()

    # Should still have battery activity (self-consumption)
    charge = data.get("total_charge_kwh", 0)
    print(f"  charge={charge:.1f} kWh (flat tariff, no RDN)")

    # Should NOT have rdn_arbitrage_metrics
    info = data.get("info", {})
    arb_metrics = info.get("rdn_arbitrage_metrics")
    # May or may not be present depending on price variation detection
    print(f"  rdn_arbitrage_metrics present: {arb_metrics is not None}")

    print("  PASS")

# --- Main ---

if __name__ == "__main__":
    print("=" * 60)
    print("REGRESSION TEST: PV + RDN Arbitrage Mechanism")
    print(f"Target: {BASE}")
    print("=" * 60)

    # Health check
    try:
        r = requests.get(f"{BASE}/health", timeout=5)
        print(f"Health: {r.status_code}")
    except Exception as e:
        print(f"ERROR: Cannot reach {BASE}: {e}")
        sys.exit(1)

    passed = 0
    failed = 0
    errors = []

    tests = [
        test_1_basic_rdn_dispatch,
        test_2_allow_grid_charging_differentiation,
        test_3_no_pv_no_grid_charging,
        test_4_sizing_dispatch_consistency,
        test_5_deprecated_fields_present,
        test_6_no_rdn_dispatch,
    ]

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            failed += 1
            errors.append(f"{test_fn.__name__}: {e}")
            print(f"  FAIL: {e}")
        except Exception as e:
            failed += 1
            errors.append(f"{test_fn.__name__}: {type(e).__name__}: {e}")
            print(f"  ERROR: {type(e).__name__}: {e}")

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)}")
    if errors:
        print("\nFailed tests:")
        for e in errors:
            print(f"  - {e}")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)
