"""
Diagnostyka optymalizacji sezonowej NPV
Z RZECZYWISTYMI danymi z API (HIGH = lato)
"""
import requests
import numpy as np
import pandas as pd

DATA_API = "http://localhost:8001"
PV_API = "http://localhost:8002"

# Parametry ekonomiczne
ENERGY_PRICE = 700  # PLN/MWh
OPEX_PER_KWP = 15   # PLN/kWp/rok
DISCOUNT_RATE = 0.07
PROJECT_YEARS = 25

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
    for min_cap, max_cap, capex in CAPEX_TIERS:
        if min_cap <= capacity_kwp <= max_cap:
            return capex
    return 2700

def calculate_npv(capacity_kwp, self_consumed_mwh):
    """NPV z pelnym kosztem i danym przychodem"""
    capex = get_capex(capacity_kwp)
    total_capex = capacity_kwp * capex

    annual_revenue = self_consumed_mwh * ENERGY_PRICE
    annual_opex = capacity_kwp * OPEX_PER_KWP
    annual_cf = annual_revenue - annual_opex

    npv = -total_capex
    for year in range(1, PROJECT_YEARS + 1):
        npv += annual_cf / ((1 + DISCOUNT_RATE) ** year)

    return npv, total_capex, annual_revenue, annual_opex, annual_cf

def main():
    print("=" * 90)
    print("DIAGNOSTYKA OPTYMALIZACJI SEZONOWEJ NPV - RZECZYWISTE DANE")
    print("=" * 90)

    # Pobierz dane z API
    print("\n1. Pobieranie danych z API...")

    # Dane godzinowe
    hourly_resp = requests.get(f"{DATA_API}/hourly-data")
    hourly_data = hourly_resp.json()
    consumption = np.array(hourly_data["values"])
    timestamps = hourly_data["timestamps"]

    print(f"   Punkty danych: {len(consumption)}")
    print(f"   Zuzycie calkowite: {consumption.sum()/1000:.1f} MWh")

    # Sezonowosc
    seasonality_resp = requests.get(f"{DATA_API}/seasonality")
    seasonality = seasonality_resp.json()

    print(f"\n2. Analiza sezonowosci:")
    print(f"   Wykryto sezonowosc: {seasonality.get('seasonality_detected', False)}")

    # Wyswietl miesiace wg pasm
    monthly_bands = seasonality.get('monthly_bands', [])
    print(f"\n   Miesiace wg pasm:")
    for mb in monthly_bands:
        print(f"      {mb['month']}: {mb['dominant_band']}")

    # Stworz maske sezonow
    parsed_times = pd.to_datetime(timestamps)
    month_band_map = {item['month']: item['dominant_band'] for item in monthly_bands}

    high_mask = np.array([month_band_map.get(ts.strftime('%Y-%m'), 'Mid') == 'High' for ts in parsed_times])
    mid_mask = np.array([month_band_map.get(ts.strftime('%Y-%m'), 'Mid') == 'Mid' for ts in parsed_times])
    low_mask = np.array([month_band_map.get(ts.strftime('%Y-%m'), 'Mid') == 'Low' for ts in parsed_times])

    print(f"\n>>> ZUZYCIE ENERGII WG SEZONOW:")
    print(f"   HIGH: {consumption[high_mask].sum()/1000:.1f} MWh ({sum(high_mask)} godz, {sum(high_mask)/len(consumption)*100:.1f}%)")
    print(f"   MID:  {consumption[mid_mask].sum()/1000:.1f} MWh ({sum(mid_mask)} godz)")
    print(f"   LOW:  {consumption[low_mask].sum()/1000:.1f} MWh ({sum(low_mask)} godz)")

    # Generuj syntetyczny profil PV (1050 kWh/kWp/rok)
    print("\n3. Generowanie profilu PV...")

    # Profil PV - produkcja tylko w godz 6-20, szczyt 10-14
    # Z sezonowoscia: lato 1.3x, zima 0.4x
    pv_profile = []
    for day in range(365):
        # Miesiac 0-11
        month = int((day / 365) * 12)

        # Sezonowosc PV - wiecej latem
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
    # Normalizuj do ~1050 kWh/kWp/rok
    annual_yield = pv_profile.sum()
    pv_profile = pv_profile * (1050 / annual_yield)

    # Dopasuj dlugosc profilu PV do zuzycia
    if len(pv_profile) != len(consumption):
        print(f"   Rozna dlugosc danych: PV={len(pv_profile)}, consumption={len(consumption)}")
        # Uzyj krotszej
        min_len = min(len(pv_profile), len(consumption))
        pv_profile = pv_profile[:min_len]
        consumption = consumption[:min_len]
        high_mask = high_mask[:min_len]
        mid_mask = mid_mask[:min_len]
        low_mask = low_mask[:min_len]

    print(f"   Roczny uzysk: {pv_profile.sum():.0f} kWh/kWp")
    print(f"   Produkcja HIGH: {pv_profile[high_mask].sum():.0f} kWh/kWp ({pv_profile[high_mask].sum()/pv_profile.sum()*100:.1f}%)")
    print(f"   Produkcja MID:  {pv_profile[mid_mask].sum():.0f} kWh/kWp")
    print(f"   Produkcja LOW:  {pv_profile[low_mask].sum():.0f} kWh/kWp")

    # Symulacja dla roznych mocy
    print("\n" + "=" * 90)
    print("SYMULACJA NPV DLA ROZNYCH MOCY")
    print("=" * 90)

    results = []

    print(f"\n{'Moc':>8} | {'HIGH MWh':>10} | {'TOTAL MWh':>10} | {'HIGH NPV':>14} | {'TOTAL NPV':>14} | {'CAPEX/kWp':>10}")
    print("-" * 82)

    for capacity in range(500, 10001, 500):
        # Produkcja PV
        production_dc = pv_profile * capacity
        ac_capacity = capacity / 1.2
        production_ac = np.minimum(production_dc, ac_capacity)

        # 0-export
        self_consumed = np.minimum(production_ac, consumption)

        # Metryki HIGH only
        high_self_mwh = self_consumed[high_mask].sum() / 1000
        high_npv, capex, _, _, _ = calculate_npv(capacity, high_self_mwh)

        # Metryki TOTAL
        total_self_mwh = self_consumed.sum() / 1000
        total_npv, _, _, _, _ = calculate_npv(capacity, total_self_mwh)

        results.append({
            'capacity': capacity,
            'high_mwh': high_self_mwh,
            'total_mwh': total_self_mwh,
            'high_npv': high_npv,
            'total_npv': total_npv,
            'capex_per_kwp': get_capex(capacity)
        })

        print(f"{capacity:>8,} | {high_self_mwh:>10.2f} | {total_self_mwh:>10.2f} | {high_npv/1_000_000:>14.3f} | {total_npv/1_000_000:>14.3f} | {get_capex(capacity):>10,}")

    # Znajdz optima
    best_high = max(results, key=lambda x: x['high_npv'])
    best_total = max(results, key=lambda x: x['total_npv'])

    print("\n" + "=" * 90)
    print("WYNIKI OPTYMALIZACJI:")
    print("=" * 90)
    print(f"\n>>> Najlepsze NPV dla sezonu HIGH:")
    print(f"   Moc: {best_high['capacity']:,} kWp")
    print(f"   HIGH self-consumed: {best_high['high_mwh']:.2f} MWh")
    print(f"   HIGH NPV: {best_high['high_npv']/1_000_000:.3f} mln PLN")

    print(f"\n>>> Najlepsze NPV dla CALEGO ROKU:")
    print(f"   Moc: {best_total['capacity']:,} kWp")
    print(f"   Total self-consumed: {best_total['total_mwh']:.2f} MWh")
    print(f"   Total NPV: {best_total['total_npv']/1_000_000:.3f} mln PLN")

    # Analiza marginalnego NPV
    print("\n" + "=" * 90)
    print("ANALIZA MARGINALNEGO NPV")
    print("=" * 90)

    # Znajdz punkty zwrotne (gdzie marginalny NPV staje sie ujemny)
    print("\n>>> Marginalny NPV przy zwiekszaniu mocy o 500 kWp:")
    print(f"{'Od':>8} | {'Do':>8} | {'dMWh HIGH':>12} | {'dMWh TOTAL':>12} | {'marg NPV HIGH':>15} | {'marg NPV TOTAL':>15}")
    print("-" * 90)

    pv_factor = sum(1 / ((1 + DISCOUNT_RATE) ** year) for year in range(1, PROJECT_YEARS + 1))

    for i in range(1, len(results)):
        r1 = results[i-1]
        r2 = results[i]

        delta_cap = r2['capacity'] - r1['capacity']
        delta_mwh_high = r2['high_mwh'] - r1['high_mwh']
        delta_mwh_total = r2['total_mwh'] - r1['total_mwh']

        delta_capex = (r2['capacity'] * get_capex(r2['capacity'])) - (r1['capacity'] * get_capex(r1['capacity']))
        delta_opex = delta_cap * OPEX_PER_KWP

        marg_npv_high = -delta_capex + (delta_mwh_high * ENERGY_PRICE - delta_opex) * pv_factor
        marg_npv_total = -delta_capex + (delta_mwh_total * ENERGY_PRICE - delta_opex) * pv_factor

        marker_high = " <-- ZERO" if marg_npv_high < 0 and results[i-1]['high_npv'] > 0 else ""
        marker_total = " <-- ZERO" if marg_npv_total < 0 and results[i-1]['total_npv'] > 0 else ""

        print(f"{r1['capacity']:>8,} | {r2['capacity']:>8,} | {delta_mwh_high:>12.2f} | {delta_mwh_total:>12.2f} | {marg_npv_high/1000:>15,.0f}k{marker_high} | {marg_npv_total/1000:>15,.0f}k{marker_total}")

    # Wnioski
    print("\n" + "=" * 90)
    print("WNIOSKI:")
    print("=" * 90)

    if best_high['capacity'] < best_total['capacity']:
        print(f"""
   [!] Optymalizacja HIGH wybiera MNIEJSZA instalacje ({best_high['capacity']:,} kWp)
       niz optymalizacja calego roku ({best_total['capacity']:,} kWp).

   DLACZEGO?
   ---------
   Mimo ze HIGH = lato (duzo slonca), to:
   1. Przychod liczymy TYLKO z sezonu HIGH
   2. Ale koszty (CAPEX + OPEX) sa PELNE - za caly rok
   3. Wieksza instalacja produkuje wiecej, ale w sezonie HIGH jest LIMIT zuzycia
   4. Po przekroczeniu zuzycia HIGH, dodatkowa produkcja idzie na eksport = 0 PLN
   5. Wiec dodatkowe kWp daja coraz mniej przychodu, ale koszty rosna liniowo
""")
    else:
        print(f"""
   [OK] Optymalizacja HIGH wybiera taka sama lub WIEKSZA instalacje ({best_high['capacity']:,} kWp)
        jak optymalizacja calego roku ({best_total['capacity']:,} kWp).

   To znaczy ze zuzycie w sezonie HIGH jest na tyle duze,
   ze uzasadnia pelna instalacje.
""")

    # Dodatkowa analiza: HIGH+MID
    print("\n" + "=" * 90)
    print("DODATKOWA ANALIZA: HIGH + MID")
    print("=" * 90)

    high_mid_mask = high_mask | mid_mask

    best_high_mid = []
    for capacity in range(500, 10001, 500):
        production_dc = pv_profile * capacity
        ac_capacity = capacity / 1.2
        production_ac = np.minimum(production_dc, ac_capacity)
        self_consumed = np.minimum(production_ac, consumption)

        high_mid_mwh = self_consumed[high_mid_mask].sum() / 1000
        high_mid_npv, _, _, _, _ = calculate_npv(capacity, high_mid_mwh)
        best_high_mid.append({'capacity': capacity, 'mwh': high_mid_mwh, 'npv': high_mid_npv})

    best_hm = max(best_high_mid, key=lambda x: x['npv'])

    print(f"\n>>> Najlepsze NPV dla HIGH+MID: {best_hm['capacity']:,} kWp -> {best_hm['npv']/1_000_000:.3f} mln PLN")
    print(f">>> Najlepsze NPV dla HIGH only: {best_high['capacity']:,} kWp -> {best_high['high_npv']/1_000_000:.3f} mln PLN")
    print(f">>> Najlepsze NPV dla TOTAL:     {best_total['capacity']:,} kWp -> {best_total['total_npv']/1_000_000:.3f} mln PLN")

if __name__ == "__main__":
    main()
