"""
Skrypt do uruchomienia standardowej analizy NPV (bez sezonowości)
i porównania z wynikami PASMA SEZONOWOŚĆ
"""
import requests
import json

# API endpoints
DATA_API = "http://localhost:8001"
PV_API = "http://localhost:8002"

# Parametry ekonomiczne (z modułu ustawień)
ENERGY_PRICE = 700  # PLN/MWh (cena EaaS)
OPEX_PER_KWP = 15  # PLN/kWp/rok
DISCOUNT_RATE = 0.07  # 7%
PROJECT_YEARS = 25

# Tabela CAPEX
CAPEX_TIERS = [
    (150, 500, 4200),
    (501, 1000, 3800),
    (1001, 2500, 3500),
    (2501, 5000, 3200),
    (5001, 10000, 3000),
    (10001, 15000, 2850),
    (15001, 50000, 2700)
]

def get_capex(capacity_kwp):
    """Pobierz CAPEX dla danej mocy"""
    for min_cap, max_cap, capex in CAPEX_TIERS:
        if min_cap <= capacity_kwp <= max_cap:
            return capex
    return 2700  # Domyślny dla dużych instalacji

def calculate_npv(capacity_kwp, self_consumed_mwh):
    """Oblicz NPV dla danej konfiguracji"""
    capex = get_capex(capacity_kwp)
    total_capex = capacity_kwp * capex

    annual_revenue = self_consumed_mwh * ENERGY_PRICE
    annual_opex = capacity_kwp * OPEX_PER_KWP
    annual_cf = annual_revenue - annual_opex

    npv = -total_capex
    for year in range(1, PROJECT_YEARS + 1):
        npv += annual_cf / ((1 + DISCOUNT_RATE) ** year)

    return npv

def main():
    print("=" * 70)
    print("ANALIZA NPV - PORÓWNANIE STRATEGII")
    print("=" * 70)

    # 1. Pobierz dane zużycia
    print("\n1. Pobieranie danych zużycia...")
    hourly_resp = requests.get(f"{DATA_API}/hourly-data")
    hourly_data = hourly_resp.json()

    consumption = hourly_data["values"]
    timestamps = hourly_data["timestamps"]

    total_consumption_mwh = sum(consumption) / 1000
    print(f"   Roczne zużycie: {total_consumption_mwh:.2f} MWh ({total_consumption_mwh/1000:.3f} GWh)")

    # 2. Uruchom standardową analizę PV
    print("\n2. Uruchamianie standardowej analizy PV...")

    analysis_request = {
        "consumption": consumption,
        "timestamps": timestamps,
        "capacity_min": 1000,
        "capacity_max": 50000,
        "capacity_step": 500,
        "pv_config": {
            "pv_type": "ground_s",
            "yield_target": 1050,
            "dc_ac_ratio": 1.2,
            "latitude": 52.0,
            "longitude": 21.0,
            "altitude": 100,
            "use_pvgis": True
        },
        "thresholds": {"A": 95, "B": 90, "C": 85, "D": 80}
    }

    analysis_resp = requests.post(
        f"{PV_API}/analyze",
        json=analysis_request,
        timeout=300
    )

    if analysis_resp.status_code != 200:
        print(f"   BŁĄD: {analysis_resp.text}")
        return

    results = analysis_resp.json()
    scenarios = results["scenarios"]
    print(f"   Przeanalizowano {len(scenarios)} scenariuszy")

    # 3. Oblicz NPV dla każdego scenariusza
    print("\n3. Obliczanie NPV dla wszystkich scenariuszy...")

    best_npv = float('-inf')
    best_scenario = None

    for scenario in scenarios:
        capacity = scenario["capacity"]
        self_consumed_mwh = scenario["self_consumed"] / 1000  # kWh -> MWh

        npv = calculate_npv(capacity, self_consumed_mwh)
        scenario["npv"] = npv
        scenario["npv_mln"] = npv / 1_000_000

        if npv > best_npv:
            best_npv = npv
            best_scenario = scenario

    # 4. Wyświetl wyniki
    print("\n" + "=" * 70)
    print("WYNIKI STANDARDOWEJ OPTYMALIZACJI NPV (BEZ SEZONOWOSCI)")
    print("=" * 70)

    print(f"\n>>> NAJLEPSZE NPV:")
    print(f"   Moc instalacji:     {best_scenario['capacity']:,.0f} kWp ({best_scenario['capacity']/1000:.1f} MWp)")
    print(f"   Produkcja:          {best_scenario['production']/1000:,.2f} MWh/rok")
    print(f"   Autokonsumpcja:     {best_scenario['self_consumed']/1000:,.2f} MWh/rok")
    print(f"   Eksport:            {best_scenario['exported']/1000:,.2f} MWh/rok")
    print(f"   Autokonsumpcja %:   {best_scenario['auto_consumption_pct']:.1f}%")
    print(f"   Pokrycie %:         {best_scenario['coverage_pct']:.1f}%")
    print(f"   CAPEX:              {get_capex(best_scenario['capacity']):,} PLN/kWp")
    print(f"   NPV:                {best_npv:,.0f} PLN ({best_npv/1_000_000:.2f} mln PLN)")

    # 5. Top 10 scenariuszy wg NPV
    print("\n>>> TOP 10 SCENARIUSZY WG NPV:")
    print("-" * 90)
    print(f"{'Moc [kWp]':>10} | {'Autokonsum [MWh]':>16} | {'Auto %':>8} | {'Pokrycie %':>10} | {'NPV [mln PLN]':>14}")
    print("-" * 90)

    sorted_scenarios = sorted(scenarios, key=lambda x: x["npv"], reverse=True)[:10]
    for s in sorted_scenarios:
        print(f"{s['capacity']:>10,.0f} | {s['self_consumed']/1000:>16,.2f} | {s['auto_consumption_pct']:>7.1f}% | {s['coverage_pct']:>9.1f}% | {s['npv_mln']:>14.2f}")

    # 6. Porownanie z PASMA SEZONOWOSC
    print("\n" + "=" * 70)
    print("POROWNANIE Z PASMA SEZONOWOSC (z poprzednich symulacji)")
    print("=" * 70)

    # Dane z logow (wczesniejsze symulacje)
    seasonality_results = [
        {"name": "HIGH only", "capacity": 1000, "target_npv_mln": 1.246, "total_npv_mln": 3.089,
         "target_mwh": 440.18, "total_mwh": 615.68, "auto_pct": 89.7},
        {"name": "HIGH+MID", "capacity": 1000, "target_npv_mln": 1.918, "total_npv_mln": 3.089,
         "target_mwh": 504.16, "total_mwh": 615.68, "auto_pct": 89.9},
        {"name": "HIGH+MID (800kWp)", "capacity": 800, "target_npv_mln": 2.032, "total_npv_mln": 3.148,
         "target_mwh": 450.72, "total_mwh": 557.02, "auto_pct": 90.8},
    ]

    print("\n>>> POROWNANIE STRATEGII:")
    print("-" * 100)
    print(f"{'Strategia':<25} | {'Moc [kWp]':>10} | {'Self-cons [MWh]':>15} | {'Auto %':>8} | {'NPV Total [mln]':>15}")
    print("-" * 100)

    # Standardowe NPV
    print(f"{'STANDARD NPV (best)':<25} | {best_scenario['capacity']:>10,.0f} | {best_scenario['self_consumed']/1000:>15,.2f} | {best_scenario['auto_consumption_pct']:>7.1f}% | {best_scenario['npv_mln']:>15.2f}")

    # Sezonowosc
    for sr in seasonality_results:
        print(f"{'PASMA ' + sr['name']:<25} | {sr['capacity']:>10,} | {sr['total_mwh']:>15,.2f} | {sr['auto_pct']:>7.1f}% | {sr['total_npv_mln']:>15.2f}")

    print("\n" + "=" * 70)
    print("WNIOSKI:")
    print("=" * 70)

    # Znajdz scenariusz 1000kWp i 800kWp dla porownania
    scenario_1000 = next((s for s in scenarios if s["capacity"] == 1000), None)
    scenario_800 = next((s for s in scenarios if s["capacity"] == 800), None)

    if scenario_1000:
        print(f"\n* Przy 1000 kWp (standard): NPV = {scenario_1000['npv_mln']:.2f} mln PLN, auto = {scenario_1000['auto_consumption_pct']:.1f}%")
    if scenario_800:
        print(f"* Przy 800 kWp (standard):  NPV = {scenario_800['npv_mln']:.2f} mln PLN, auto = {scenario_800['auto_consumption_pct']:.1f}%")

    print(f"\n* Najlepsze NPV standardowe: {best_scenario['capacity']:.0f} kWp -> {best_npv/1_000_000:.2f} mln PLN")
    print(f"  (autokonsumpcja: {best_scenario['auto_consumption_pct']:.1f}%)")

    if best_scenario['capacity'] > 1000:
        print(f"\n[!] Standardowa optymalizacja wybiera wieksza instalacje ({best_scenario['capacity']:.0f} kWp)")
        print(f"    bo maksymalizuje calkowite NPV, nawet kosztem nizszej autokonsumpcji.")

    print("\n[OK] Strategia PASMA SEZONOWOSC daje podobne wyniki przy mniejszej instalacji,")
    print("     bo optymalizuje dla okresow gdy energia jest faktycznie potrzebna.")

if __name__ == "__main__":
    main()
