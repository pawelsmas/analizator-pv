"""
Multi-scenario comparison test for ANALIZATOR PV (bess-dispatch).

Scenarios:
  A) PV + BESS sizing  — oversized PV, find optimal battery
  B) Peak shaving      — industrial load, reduce demand charges
  C) Arbitrage         — pure energy trading on price spreads
  D) Stacked (all)     — PV surplus + peak shaving + arbitrage combined
  E) Load-only BESS    — no PV, battery for peak + arbitrage

Each scenario runs dispatch + sizing and prints comparable metrics.
"""

import json
import math
import sys
import time
import numpy as np
import requests

API_URL = "http://localhost:8031"
HOURS = 8760

# ── Profile generators ──────────────────────────────────────────

def generate_load(peak_kw=6000, base_frac=0.40, hours=HOURS):
    t = np.arange(hours)
    hod, doy = t % 24, t // 24
    base = peak_kw * base_frac
    daily = np.zeros(hours)
    for h in range(24):
        if 6 <= h < 8:   daily[hod == h] = 0.3 * (h - 6) / 2
        elif 8 <= h < 17: daily[hod == h] = 0.3
        elif 17 <= h < 20: daily[hod == h] = 0.3 * (20 - h) / 3
    weekday = (doy % 7) < 5
    seasonal = 1.0 + 0.15 * np.cos(2 * np.pi * (doy - 15) / 365)
    load = (base + peak_kw * daily) * np.where(weekday, 1.0, 0.6)[t] * seasonal
    load += np.random.normal(0, peak_kw * 0.02, hours)
    return np.clip(load, peak_kw * 0.08, peak_kw)


def generate_pv(panel_kw=8000, inverter_kw=None, hours=HOURS):
    if inverter_kw is None:
        inverter_kw = panel_kw * 0.75
    t = np.arange(hours)
    hod, doy = t % 24, t // 24
    pv = np.zeros(hours)
    for i in range(hours):
        decl = 23.45 * math.sin(math.radians(360 / 365 * (doy[i] - 81)))
        ha = (hod[i] - 12) * 15
        elev = math.degrees(math.asin(
            math.sin(math.radians(50)) * math.sin(math.radians(decl)) +
            math.cos(math.radians(50)) * math.cos(math.radians(decl)) * math.cos(math.radians(ha))
        ))
        if elev > 0:
            am = min(1.0 / (math.sin(math.radians(elev)) + 0.50572 * (elev + 6.07995) ** -1.6364), 40)
            dni = 1361 * 0.7 ** (am ** 0.678)
            cos_inc = (math.sin(math.radians(elev)) * math.cos(math.radians(20)) +
                       math.cos(math.radians(elev)) * math.sin(math.radians(20)) * math.cos(math.radians(ha)))
            pv[i] = panel_kw * (max(cos_inc, 0) * dni / 1000) * 0.85 * 0.97
    pv *= np.random.uniform(0.5, 1.0, hours)
    return np.clip(pv, 0, inverter_kw)


def generate_prices(hours=HOURS):
    t = np.arange(hours)
    hod, doy = t % 24, t // 24
    shape = {0:-80,1:-100,2:-110,3:-115,4:-100,5:-60,6:-20,7:30,
             8:60,9:80,10:90,11:85,12:70,13:60,14:50,15:55,16:70,
             17:100,18:120,19:110,20:80,21:40,22:0,23:-40}
    prices = np.array([350.0 + shape[h % 24] for h in range(hours)], dtype=float)
    prices *= 1.0 + 0.2 * np.cos(2 * np.pi * (doy - 15) / 365)
    weekday = (doy % 7) < 5
    prices *= np.where(weekday, 1.0, 0.75)
    prices += np.random.normal(0, 30, hours)
    return np.clip(prices, 50, 800)


def make_buy_sell(rdn_mwh, surcharges_mwh=281.92, sell_margin_pct=0.05):
    buy = (rdn_mwh + surcharges_mwh) / 1000
    sell = (rdn_mwh * (1 - sell_margin_pct) - 4) / 1000
    return buy, sell


# ── Scenario definitions ────────────────────────────────────────

SCENARIOS = {
    "A": {
        "name": "PV surplus (oversized PV)",
        "desc": "Przewymiarowane PV 10 MWp vs load 3 MW — magazyn buforuje nadwyżki",
        "pv_kw": 10000,
        "inverter_kw": 8000,
        "load_peak_kw": 3000,
        "batt_power_kw": 2000,
        "batt_energy_kwh": 4000,
        "mode": "pv_surplus",
        "peak_limit_kw": None,
        "durations_h": [1, 2, 4],
        "sizing_power_kw": 2000,
    },
    "B": {
        "name": "Peak Shaving (load-only)",
        "desc": "Zakład 6 MW, moc umowna 4 MW, magazyn tnie szczyty",
        "pv_kw": 0,
        "load_peak_kw": 6000,
        "batt_power_kw": 3000,
        "batt_energy_kwh": 6000,
        "mode": "peak_shaving",
        "peak_limit_kw": 4000,
        "durations_h": [1, 2, 4],
        "sizing_power_kw": 3000,
        "topology": "load_only",
    },
    "C": {
        "name": "Arbitrage + PV + Peak",
        "desc": "PV 5 MWp + load 4 MW + peak 3.5 MW + arbitraż cenowy (stacked)",
        "pv_kw": 5000,
        "inverter_kw": 4000,
        "load_peak_kw": 4000,
        "load_base_frac": 0.50,
        "batt_power_kw": 3000,
        "batt_energy_kwh": 6000,
        "mode": "stacked",
        "peak_limit_kw": 3500,
        "durations_h": [1, 2, 4],
        "sizing_power_kw": 3000,
    },
    "D": {
        "name": "Stacked full (pagra-galileo)",
        "desc": "PV 8 MWp + peak 6.5 MW + arbitraż — odwzorowanie pagra-galileo",
        "pv_kw": 8000,
        "inverter_kw": 6000,
        "load_peak_kw": 6000,
        "batt_power_kw": 6000,
        "batt_energy_kwh": 12000,
        "mode": "stacked",
        "peak_limit_kw": 6500,
        "durations_h": [1, 2, 4],
        "sizing_power_kw": 6000,
    },
    "E": {
        "name": "Load-only BESS (biurowiec)",
        "desc": "Biurowiec 1 MW, bez PV, peak shaving do 700 kW",
        "pv_kw": 0,
        "load_peak_kw": 1000,
        "load_base_frac": 0.35,
        "batt_power_kw": 500,
        "batt_energy_kwh": 1000,
        "mode": "peak_shaving",
        "peak_limit_kw": 700,
        "durations_h": [1, 2, 4],
        "sizing_power_kw": 500,
        "topology": "load_only",
    },
}

FINANCE = {
    "capex_per_kwh": 1200,
    "capex_per_kw": 200,
    "opex_pct": 2.0,
    "discount_rate": 8.0,
    "project_lifetime_years": 15,
    "bess_lifetime_years": 15,
    "bess_degradation_pct_per_year": 2.5,
}


# ── Run helpers ──────────────────────────────────────────────────

def run_dispatch(scenario, pv, load, buy, sell):
    s = scenario
    req = {
        "load_kw": load.tolist(),
        "interval_minutes": 60,
        "battery_power_kw": s["batt_power_kw"],
        "battery_energy_kwh": s["batt_energy_kwh"],
        "roundtrip_efficiency": 0.90,
        "soc_min": 0.10,
        "soc_max": 0.90,
        "soc_initial": 0.5,
        "mode": s["mode"],
        "start_date": "2025-01-01",
    }
    topo = s.get("topology", "pv_load" if s["pv_kw"] > 0 else "load_only")
    req["topology"] = topo
    if s["pv_kw"] > 0:
        req["pv_generation_kw"] = pv.tolist()

    if s["peak_limit_kw"]:
        req["peak_limit_kw"] = s["peak_limit_kw"]

    # Arbitrage config only for stacked mode
    if s["mode"] == "stacked":
        req["arbitrage_config"] = {
            "buy_price": buy.tolist(),
            "sell_price": sell.tolist(),
        }

    resp = requests.post(f"{API_URL}/dispatch", json=req, timeout=300)
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
    return resp.json(), None


def run_sizing(scenario, pv, load, buy, sell):
    s = scenario
    req = {
        "load_kw": load.tolist(),
        "interval_minutes": 60,
        "battery_power_kw": s["sizing_power_kw"],
        "roundtrip_efficiency": 0.90,
        "soc_min": 0.10,
        "soc_max": 0.90,
        "mode": s["mode"],
        "durations_h": s["durations_h"],
        "finance": FINANCE,
        "start_date": "2025-01-01",
    }
    topo = s.get("topology", "pv_load" if s["pv_kw"] > 0 else "load_only")
    req["topology"] = topo
    # sizing API always requires pv_generation_kw
    req["pv_generation_kw"] = pv.tolist()

    if s["peak_limit_kw"]:
        req["peak_limit_kw"] = s["peak_limit_kw"]

    # Arbitrage config only for stacked mode
    if s["mode"] == "stacked":
        req["arbitrage_config"] = {
            "buy_price": buy.tolist(),
            "sell_price": sell.tolist(),
        }

    resp = requests.post(f"{API_URL}/sizing", json=req, timeout=600)
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
    return resp.json(), None


# ── Result formatting ────────────────────────────────────────────

def fmt(val, unit="", precision=1):
    if val is None:
        return "N/A"
    if isinstance(val, float):
        return f"{val:.{precision}f}{unit}"
    return f"{val}{unit}"


def print_dispatch(r, label):
    charge = r.get('total_charge_kwh', 0)
    discharge = r.get('total_discharge_kwh', 0)
    energy = r.get('battery_energy_kwh', 1)
    efc = (charge + discharge) / 2 / energy if energy > 0 else 0

    print(f"  Load:       {r.get('total_load_kwh',0)/1000:>8.1f} MWh")
    print(f"  PV:         {r.get('total_pv_kwh',0)/1000:>8.1f} MWh")
    print(f"  Grid imp:   {r.get('total_grid_import_kwh',0)/1000:>8.1f} MWh")
    print(f"  Grid exp:   {r.get('total_grid_export_kwh',0)/1000:>8.1f} MWh")
    print(f"  Charge:     {charge/1000:>8.1f} MWh")
    print(f"  Discharge:  {discharge/1000:>8.1f} MWh")
    print(f"  EFC:        {efc:>8.0f} cycles")
    print(f"  Peak orig:  {r.get('original_peak_kw',0):>8.0f} kW")
    print(f"  Peak new:   {r.get('new_peak_kw',0):>8.0f} kW")
    print(f"  Peak cut:   {r.get('peak_reduction_kw',0):>8.0f} kW ({r.get('peak_reduction_pct',0):.1f}%)")
    print(f"  Base cost:  {r.get('baseline_cost_pln',0)/1000:>8.1f} k PLN")
    print(f"  Proj cost:  {r.get('project_cost_pln',0)/1000:>8.1f} k PLN")
    print(f"  Savings:    {r.get('annual_savings_pln',0)/1000:>8.1f} k PLN/yr")

    bd = r.get("savings_breakdown", {})
    es = bd.get("energy_savings_pln", 0)
    arb = bd.get("arbitrage_savings_pln", 0)
    cap = bd.get("capacity_fee_savings_pln", 0)
    dem = bd.get("demand_charge_savings_pln", 0)
    exp_rev = bd.get("export_revenue_pln", 0)
    if es: print(f"    energy:   {es/1000:>8.1f} k PLN")
    if arb: print(f"    arbitrage:{arb/1000:>8.1f} k PLN")
    if cap: print(f"    cap fee:  {cap/1000:>8.1f} k PLN")
    if dem: print(f"    demand:   {dem/1000:>8.1f} k PLN")
    if exp_rev: print(f"    export:   {exp_rev/1000:>8.1f} k PLN")


def print_sizing(result):
    rec = result.get("recommended_variant", "?")
    rec_p = result.get("recommended_power_kw", 0)
    rec_e = result.get("recommended_energy_kwh", 0)
    print(f"  Recommended: {rec} ({rec_p/1000:.1f} MW / {rec_e/1000:.1f} MWh)")

    for v in result.get("variants", []):
        label = v.get("variant_label", v.get("variant", "?"))
        p = v.get("power_kw", 0)
        e = v.get("energy_kwh", 0)
        capex = v.get("capex_pln", 0)
        sav = v.get("annual_savings_pln", 0)
        npv = v.get("npv_pln", 0)
        irr = v.get("irr_pct")
        pb = v.get("simple_payback_years")
        deg = v.get("degradation", {})
        efc = deg.get("efc_total", 0)

        irr_s = f"{irr:.1f}%" if irr else "N/A"
        pb_s = f"{pb:.1f}y" if pb and pb < 100 else "N/A"

        print(f"  {label:20s} | {p/1000:5.1f} MW {e/1000:6.1f} MWh | "
              f"CAPEX {capex/1000:>6.0f}k | sav {sav/1000:>6.1f}k/yr | "
              f"NPV {npv/1000:>7.0f}k | IRR {irr_s:>6s} | PB {pb_s:>5s} | "
              f"EFC {efc:>4.0f}")


# ── Summary table ────────────────────────────────────────────────

def print_summary_table(results):
    print("\n" + "=" * 100)
    print("SUMMARY TABLE — all scenarios compared")
    print("=" * 100)

    hdr = (f"{'Scenario':30s} | {'Load':>7s} | {'PV':>7s} | {'Batt':>10s} | "
           f"{'EFC':>4s} | {'Peak%':>6s} | {'Savings':>8s} | {'NPV':>8s} | {'IRR':>5s} | {'PB':>5s}")
    print(hdr)
    print("-" * len(hdr))

    for key, data in results.items():
        sc = SCENARIOS[key]
        dr = data.get("dispatch")
        sr = data.get("sizing")

        # Dispatch metrics
        if dr:
            total_load = dr.get('total_load_kwh', 0) / 1000
            total_pv = dr.get('total_pv_kwh', 0) / 1000
            batt = f"{sc['batt_energy_kwh']/1000:.0f}MWh"
            charge = dr.get('total_charge_kwh', 0)
            discharge = dr.get('total_discharge_kwh', 0)
            efc = int((charge + discharge) / 2 / sc['batt_energy_kwh']) if sc['batt_energy_kwh'] > 0 else 0
            peak_pct = dr.get('peak_reduction_pct', 0)
            savings = dr.get('annual_savings_pln', 0) / 1000
        else:
            total_load = total_pv = 0
            batt = "ERR"
            efc = 0
            peak_pct = 0
            savings = 0

        # Sizing best variant
        if sr:
            variants = sr.get("variants", [])
            best = max(variants, key=lambda v: v.get("npv_pln", float("-inf"))) if variants else {}
            npv = best.get("npv_pln", 0) / 1000
            irr = best.get("irr_pct")
            pb = best.get("simple_payback_years")
            irr_s = f"{irr:.1f}%" if irr else "N/A"
            pb_s = f"{pb:.1f}y" if pb and pb < 100 else "N/A"
        else:
            npv = 0
            irr_s = "ERR"
            pb_s = "ERR"

        name = f"{key}) {sc['name']}"
        print(f"{name:30s} | {total_load:>6.0f}M | {total_pv:>6.0f}M | {batt:>10s} | "
              f"{efc:>4d} | {peak_pct:>5.1f}% | {savings:>7.0f}k | {npv:>7.0f}k | {irr_s:>5s} | {pb_s:>5s}")


# ── Main ─────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("MULTI-SCENARIO BESS COMPARISON TEST")
    print("=" * 80)

    # Health check
    try:
        r = requests.get(f"{API_URL}/health", timeout=5)
        print(f"bess-dispatch: {r.json()['status']}")
    except:
        print("ERROR: bess-dispatch not running at localhost:8031")
        sys.exit(1)

    # Generate base profiles (reused across scenarios)
    np.random.seed(42)
    rdn = generate_prices()

    all_results = {}

    for key in sorted(SCENARIOS.keys()):
        sc = SCENARIOS[key]
        np.random.seed(42)  # Reproducible per scenario

        print(f"\n{'=' * 80}")
        print(f"SCENARIO {key}: {sc['name']}")
        print(f"  {sc['desc']}")
        print(f"  PV={sc['pv_kw']/1000:.0f} MWp, Load={sc['load_peak_kw']/1000:.0f} MW, "
              f"BESS={sc['batt_energy_kwh']/1000:.0f} MWh/{sc['batt_power_kw']/1000:.0f} MW, "
              f"mode={sc['mode']}")
        if sc['peak_limit_kw']:
            print(f"  peak_limit={sc['peak_limit_kw']/1000:.1f} MW")
        print("=" * 80)

        # Profiles
        load = generate_load(
            peak_kw=sc["load_peak_kw"],
            base_frac=sc.get("load_base_frac", 0.40)
        )
        if sc["pv_kw"] > 0:
            pv = generate_pv(
                panel_kw=sc["pv_kw"],
                inverter_kw=sc.get("inverter_kw"),
            )
        else:
            pv = np.zeros(HOURS)

        buy, sell = make_buy_sell(rdn)

        print(f"  Load: mean={load.mean():.0f} kW, max={load.max():.0f} kW")
        if sc["pv_kw"] > 0:
            print(f"  PV:   mean={pv.mean():.0f} kW, max={pv.max():.0f} kW, yield={pv.sum()/1e6:.1f} GWh")
        print(f"  Buy:  mean={buy.mean():.4f} PLN/kWh")
        print(f"  Sell: mean={sell.mean():.4f} PLN/kWh")
        print(f"  Spread: mean={(buy.mean()-sell.mean())*1000:.1f} PLN/MWh")

        # Dispatch
        print(f"\n  --- DISPATCH ---")
        t0 = time.time()
        dr, err = run_dispatch(sc, pv, load, buy, sell)
        dt = time.time() - t0
        if err:
            print(f"  ERROR: {err}")
            all_results[key] = {"dispatch": None, "sizing": None, "error": err}
            continue
        print(f"  OK ({dt:.1f}s)")
        print_dispatch(dr, key)

        # Sizing
        print(f"\n  --- SIZING ---")
        t0 = time.time()
        sr, err = run_sizing(sc, pv, load, buy, sell)
        dt = time.time() - t0
        if err:
            print(f"  ERROR: {err}")
            all_results[key] = {"dispatch": dr, "sizing": None, "error": err}
            continue
        print(f"  OK ({dt:.1f}s)")
        print_sizing(sr)

        all_results[key] = {"dispatch": dr, "sizing": sr}

    # Summary
    print_summary_table(all_results)

    # Conclusions
    print("\n" + "=" * 80)
    print("WNIOSKI / CONCLUSIONS")
    print("=" * 80)
    for key, data in all_results.items():
        sc = SCENARIOS[key]
        dr = data.get("dispatch")
        sr = data.get("sizing")
        if not dr:
            print(f"  {key}) {sc['name']}: FAILED")
            continue

        savings = dr.get('annual_savings_pln', 0)
        baseline = dr.get('baseline_cost_pln', 1)
        sav_pct = savings / baseline * 100 if baseline > 0 else 0
        charge = dr.get('total_charge_kwh', 0)
        discharge = dr.get('total_discharge_kwh', 0)
        efc = (charge + discharge) / 2 / sc['batt_energy_kwh'] if sc['batt_energy_kwh'] > 0 else 0

        notes = []
        if sav_pct > 15:
            notes.append("wysoka rentownosc")
        elif sav_pct > 5:
            notes.append("umiarkowana rentownosc")
        else:
            notes.append("niska rentownosc")

        if efc > 400:
            notes.append("intensywne cyklowanie")
        elif efc < 100:
            notes.append("niskie wykorzystanie baterii")

        peak_red = abs(dr.get('peak_reduction_pct', 0))
        if peak_red > 20:
            notes.append(f"dobry peak shaving ({peak_red:.0f}%)")

        if sr:
            best = max(sr.get("variants", [{}]), key=lambda v: v.get("npv_pln", float("-inf")))
            irr = best.get("irr_pct")
            if irr and irr > 10:
                notes.append(f"atrakcyjne IRR ({irr:.1f}%)")
            elif irr and irr > 0:
                notes.append(f"dodatnie IRR ({irr:.1f}%)")

        print(f"  {key}) {sc['name']:30s} | savings {sav_pct:.1f}% | EFC {efc:.0f} | {', '.join(notes)}")


if __name__ == "__main__":
    main()
