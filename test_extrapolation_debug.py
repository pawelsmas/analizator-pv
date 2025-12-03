"""
Debug: sprawdzenie NPV na EKSTRAPOLOWANYM zużyciu dla różnych mocy
"""
import requests
import numpy as np

DATA_API = "http://localhost:8001"
PV_API = "http://localhost:8002"

# Parametry ekonomiczne (takie same jak w test)
CAPEX_PER_KWP = 3500
OPEX_PER_KWP_YEAR = 50
ENERGY_PRICE = 700
DISCOUNT_RATE = 0.08
PROJECT_YEARS = 15

def calculate_npv(capacity_kwp, self_consumed_mwh):
    """Proste obliczenie NPV"""
    capex = capacity_kwp * CAPEX_PER_KWP
    annual_revenue = self_consumed_mwh * ENERGY_PRICE
    annual_opex = capacity_kwp * OPEX_PER_KWP_YEAR
    annual_cf = annual_revenue - annual_opex

    npv = -capex
    for year in range(1, PROJECT_YEARS + 1):
        npv += annual_cf / ((1 + DISCOUNT_RATE) ** year)

    return npv

def main():
    print("=" * 90)
    print("DEBUG: NPV na EKSTRAPOLOWANYM zużyciu")
    print("=" * 90)

    # Pobierz dane
    hourly_resp = requests.get(f"{DATA_API}/hourly-data")
    hourly_data = hourly_resp.json()
    consumption = np.array(hourly_data["values"])

    seasonality_resp = requests.get(f"{DATA_API}/seasonality")
    seasonality = seasonality_resp.json()
    monthly_bands = seasonality.get('monthly_bands', [])

    # Znajdź miesiące HIGH
    month_band_map = {item['month']: item['dominant_band'] for item in monthly_bands}
    high_months = [m for m, b in month_band_map.items() if b == 'High']

    print(f"\nMiesiące HIGH: {high_months}")
    print(f"Zużycie oryginalne: {consumption.sum()/1000:.1f} MWh/rok")

    # Ekstrapolacja (taka sama jak w kodzie)
    import pandas as pd
    timestamps = hourly_data["timestamps"]
    parsed_times = pd.to_datetime(timestamps)

    monthly_consumption = {}
    for i, ts in enumerate(parsed_times):
        month_key = ts.strftime('%Y-%m')
        if month_key not in monthly_consumption:
            monthly_consumption[month_key] = 0
        monthly_consumption[month_key] += consumption[i]

    high_monthly_values = [monthly_consumption[m] for m in high_months if m in monthly_consumption]
    median_high = np.median(high_monthly_values)

    print(f"Zużycie miesięczne HIGH: {[f'{v/1000:.0f}' for v in high_monthly_values]} MWh")
    print(f"Mediana HIGH: {median_high/1000:.1f} MWh/miesiąc")

    # Ekstrapolacja
    extrapolated = consumption.copy()
    for month_key, band in month_band_map.items():
        if band != 'High' and month_key in monthly_consumption:
            scale = median_high / monthly_consumption[month_key]
            for i, ts in enumerate(parsed_times):
                if ts.strftime('%Y-%m') == month_key:
                    extrapolated[i] = consumption[i] * scale

    print(f"Zużycie ekstrapolowane: {extrapolated.sum()/1000:.1f} MWh/rok")
    print(f"Współczynnik: {extrapolated.sum()/consumption.sum():.2f}x")

    # Generuj prosty profil PV (1098 kWh/kWp jak PVGIS)
    # Z sezonowością: lato więcej, zima mniej
    pv_profile = []
    for day in range(365):
        month = int((day / 365) * 12)
        # Sezonowość PV
        if month in [5, 6, 7]:  # cze-sie
            pv_factor = 1.4
        elif month in [4, 8]:  # maj, wrz
            pv_factor = 1.1
        elif month in [3, 9]:  # kwi, paz
            pv_factor = 0.8
        else:  # zima
            pv_factor = 0.4

        for hour in range(24):
            if 6 <= hour <= 19:
                peak_hour = 12
                sigma = 3
                val = pv_factor * np.exp(-((hour - peak_hour)**2) / (2 * sigma**2))
            else:
                val = 0
            pv_profile.append(val)

    pv_profile = np.array(pv_profile)
    pv_profile = pv_profile * (1098 / pv_profile.sum())  # Normalizuj do 1098 kWh/kWp

    print(f"\nProfil PV: {pv_profile.sum():.0f} kWh/kWp/rok")

    # Symulacja dla różnych mocy
    print(f"\n{'Moc':>8} | {'Self(orig)':>12} | {'Self(ekstr)':>12} | {'NPV(orig)':>14} | {'NPV(ekstr)':>14}")
    print("-" * 75)

    for capacity in range(500, 5001, 500):
        # Produkcja AC
        production = pv_profile * capacity
        ac_capacity = capacity / 1.2
        production = np.minimum(production, ac_capacity)

        # Self-consumed na oryginalnym zużyciu
        self_orig = np.minimum(production, consumption).sum() / 1000
        npv_orig = calculate_npv(capacity, self_orig)

        # Self-consumed na ekstrapolowanym zużyciu
        self_extr = np.minimum(production, extrapolated).sum() / 1000
        npv_extr = calculate_npv(capacity, self_extr)

        print(f"{capacity:>8} | {self_orig:>12.1f} | {self_extr:>12.1f} | {npv_orig/1e6:>14.3f} | {npv_extr/1e6:>14.3f}")

    print("\n" + "=" * 90)
    print("WNIOSEK:")
    print("  - NPV(ekstr) powinno być WYŻSZE dla większych mocy jeśli ekstrapolacja działa")
    print("  - Jeśli NPV(ekstr) osiąga max wcześniej niż NPV(orig) - jest problem")
    print("=" * 90)

if __name__ == "__main__":
    main()
