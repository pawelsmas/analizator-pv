"""
Test nowej logiki NPV z ekstrapolacją HIGH
"""
import requests
import json

DATA_API = "http://localhost:8001"
PV_API = "http://localhost:8002"

def main():
    print("=" * 80)
    print("TEST NOWEJ LOGIKI NPV Z EKSTRAPOLACJĄ HIGH")
    print("=" * 80)

    # 1. Pobierz dane
    print("\n1. Pobieranie danych...")
    hourly_resp = requests.get(f"{DATA_API}/hourly-data")
    hourly_data = hourly_resp.json()
    consumption = hourly_data["values"]
    timestamps = hourly_data["timestamps"]
    print(f"   Punkty danych: {len(consumption)}")

    # 2. Pobierz sezonowość
    seasonality_resp = requests.get(f"{DATA_API}/seasonality")
    seasonality = seasonality_resp.json()
    monthly_bands = seasonality.get('monthly_bands', [])
    band_powers = seasonality.get('band_powers', [])

    print(f"\n2. Sezonowość:")
    for mb in monthly_bands:
        print(f"   {mb['month']}: {mb['dominant_band']}")

    # 3. Wywołaj optymalizację MAX_NPV
    print("\n3. Optymalizacja MAX_NPV (z ekstrapolacją)...")

    request_data = {
        "pv_config": {
            "pv_type": "ground_s",
            "latitude": 52.0,
            "longitude": 21.0,
            "altitude": 100.0,
            "dc_ac_ratio": 1.2,
            "use_pvgis": True
        },
        "consumption": consumption,
        "timestamps": timestamps,
        "band_powers": band_powers,
        "monthly_bands": monthly_bands,
        "capacity_min": 500,
        "capacity_max": 5000,
        "capacity_step": 100,
        "capex_per_kwp": 3500,
        "opex_per_kwp_year": 50,
        "energy_price_import": 800,
        "energy_price_esco": 700,
        "discount_rate": 0.08,
        "project_years": 15,
        "mode": "MAX_NPV",
        "target_seasons": ["High"],
        "autoconsumption_thresholds": {"A": 95, "B": 90, "C": 85, "D": 80}
    }

    resp = requests.post(f"{PV_API}/optimize-seasonality", json=request_data, timeout=300)

    if resp.status_code != 200:
        print(f"   BŁĄD: {resp.status_code}")
        print(resp.text)
        return

    result = resp.json()

    print(f"\n{'='*80}")
    print("WYNIKI OPTYMALIZACJI MAX_NPV")
    print(f"{'='*80}")
    print(f"\n   Optymalna moc: {result['best_capacity_kwp']:.0f} kWp")
    print(f"   DC/AC ratio: {result['best_dcac_ratio']:.2f}")
    print(f"\n   NPV (rzeczywiste): {result['npv']:,.0f} PLN")
    print(f"   IRR: {result['irr']:.1f}%" if result.get('irr') else "   IRR: N/A")
    print(f"   Payback: {result['payback_years']:.1f} lat" if result.get('payback_years') else "   Payback: N/A")
    print(f"\n   Autokonsumpcja: {result['autoconsumption_pct']:.1f}%")
    print(f"   Pokrycie: {result['coverage_pct']:.1f}%")
    print(f"   Produkcja roczna: {result['annual_production_mwh']:.2f} MWh")
    print(f"   Self-consumed: {result['annual_self_consumed_mwh']:.2f} MWh")
    print(f"   Eksport: {result['annual_exported_mwh']:.2f} MWh")

    print(f"\n   Target seasons: {result.get('target_seasons')}")
    print(f"   Target self-consumed: {result.get('target_self_consumed_mwh', 0):.2f} MWh")
    print(f"   Target auto%: {result.get('target_autoconsumption_pct', 0):.1f}%")

    # 4. Dla porównania - MAX_AUTOCONSUMPTION
    print(f"\n{'='*80}")
    print("DLA PORÓWNANIA: MAX_AUTOCONSUMPTION")
    print(f"{'='*80}")

    request_data["mode"] = "MAX_AUTOCONSUMPTION"
    resp2 = requests.post(f"{PV_API}/optimize-seasonality", json=request_data, timeout=300)

    if resp2.status_code == 200:
        result2 = resp2.json()
        print(f"\n   Optymalna moc: {result2['best_capacity_kwp']:.0f} kWp")
        print(f"   NPV: {result2['npv']:,.0f} PLN")
        print(f"   Autokonsumpcja: {result2['autoconsumption_pct']:.1f}%")
        print(f"   Self-consumed: {result2['annual_self_consumed_mwh']:.2f} MWh")

if __name__ == "__main__":
    main()
