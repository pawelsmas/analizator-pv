"""
Debug: sprawdzenie NPV dla różnych mocy
"""
import requests
import json

DATA_API = "http://localhost:8001"
PV_API = "http://localhost:8002"

def main():
    print("=" * 80)
    print("DEBUG: Porównanie NPV dla różnych mocy")
    print("=" * 80)

    # Pobierz dane
    hourly_resp = requests.get(f"{DATA_API}/hourly-data")
    hourly_data = hourly_resp.json()
    consumption = hourly_data["values"]
    timestamps = hourly_data["timestamps"]

    seasonality_resp = requests.get(f"{DATA_API}/seasonality")
    seasonality = seasonality_resp.json()
    monthly_bands = seasonality.get('monthly_bands', [])
    band_powers = seasonality.get('band_powers', [])

    # Test różnych mocy
    for capacity in [500, 1000, 1100, 1500, 2000]:
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
            "capacity_min": capacity,
            "capacity_max": capacity,  # Tylko ta moc
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

        resp = requests.post(f"{PV_API}/optimize-seasonality", json=request_data, timeout=120)

        if resp.status_code == 200:
            r = resp.json()
            print(f"\n{capacity} kWp:")
            print(f"   NPV: {r['npv']:,.0f} PLN")
            print(f"   Auto%: {r['autoconsumption_pct']:.1f}%")
            print(f"   Self-consumed: {r['annual_self_consumed_mwh']:.1f} MWh")
            print(f"   Eksport: {r['annual_exported_mwh']:.1f} MWh")
        else:
            print(f"\n{capacity} kWp: BŁĄD {resp.status_code}")

if __name__ == "__main__":
    main()
