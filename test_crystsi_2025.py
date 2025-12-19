"""
Test porównania crystSi vs crystSi2025 w PVGIS API.
Nowa opcja crystSi2025 lepiej odwzorowuje nowoczesne moduły Si.
"""

import requests

PVGIS_API = "https://re.jrc.ec.europa.eu/api/v5_3"

# Lokalizacja: Debno (z PVsyst)
LAT = 52.30
LON = 16.72

def test_pvtech_comparison():
    """Porównanie różnych technologii PV w PVGIS"""
    print("="*60)
    print(f"Porównanie technologii PV dla {LAT}°N, {LON}°E")
    print("="*60)

    technologies = [
        ("crystSi", "Krzemowy krystaliczny (stary model)"),
        ("crystSi2025", "Krzemowy krystaliczny 2025 (nowy model)"),
        ("CIS", "CIS"),
        ("CdTe", "CdTe"),
    ]

    results = {}

    for tech_id, tech_name in technologies:
        params = {
            "lat": LAT,
            "lon": LON,
            "peakpower": 1,
            "loss": 14,
            "pvtechchoice": tech_id,
            "mountingplace": "free",
            "raddatabase": "PVGIS-SARAH3",
            "outputformat": "json",
            "angle": 20,
            "aspect": 0  # South
        }

        try:
            response = requests.get(f"{PVGIS_API}/PVcalc", params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                e_y = data["outputs"]["totals"]["fixed"]["E_y"]
                results[tech_id] = e_y
                print(f"\n{tech_name}:")
                print(f"  E_y = {e_y:.1f} kWh/kWp/rok")
            else:
                print(f"\n{tech_name}: BŁĄD {response.status_code}")
                print(f"  {response.text[:200]}")
        except Exception as e:
            print(f"\n{tech_name}: BŁĄD - {e}")

    # Porównanie
    if "crystSi" in results and "crystSi2025" in results:
        diff = results["crystSi2025"] - results["crystSi"]
        diff_pct = diff / results["crystSi"] * 100
        print("\n" + "="*60)
        print("PODSUMOWANIE:")
        print(f"  crystSi:      {results['crystSi']:.1f} kWh/kWp/rok")
        print(f"  crystSi2025: {results['crystSi2025']:.1f} kWh/kWp/rok")
        print(f"  Różnica:      {diff:+.1f} kWh ({diff_pct:+.2f}%)")
        print("="*60)


def test_ew_orientation():
    """Test dla orientacji E-W z crystSi2025"""
    print("\n" + "="*60)
    print("Test orientacji E-W z crystSi2025")
    print("="*60)

    orientations = [
        ("South (20°)", 20, 0),
        ("East (20°)", 20, -90),
        ("West (20°)", 20, 90),
    ]

    for name, angle, aspect in orientations:
        params = {
            "lat": LAT,
            "lon": LON,
            "peakpower": 1,
            "loss": 14,
            "pvtechchoice": "crystSi2025",
            "mountingplace": "free",
            "raddatabase": "PVGIS-SARAH3",
            "outputformat": "json",
            "angle": angle,
            "aspect": aspect
        }

        try:
            response = requests.get(f"{PVGIS_API}/PVcalc", params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                e_y = data["outputs"]["totals"]["fixed"]["E_y"]
                print(f"{name}: {e_y:.1f} kWh/kWp/rok")
        except Exception as e:
            print(f"{name}: BŁĄD - {e}")

    # Średnia E-W
    params_e = {
        "lat": LAT, "lon": LON, "peakpower": 1, "loss": 14,
        "pvtechchoice": "crystSi2025", "mountingplace": "free",
        "raddatabase": "PVGIS-SARAH3", "outputformat": "json",
        "angle": 20, "aspect": -90
    }
    params_w = params_e.copy()
    params_w["aspect"] = 90

    try:
        resp_e = requests.get(f"{PVGIS_API}/PVcalc", params=params_e, timeout=30)
        resp_w = requests.get(f"{PVGIS_API}/PVcalc", params=params_w, timeout=30)

        if resp_e.status_code == 200 and resp_w.status_code == 200:
            e_y_e = resp_e.json()["outputs"]["totals"]["fixed"]["E_y"]
            e_y_w = resp_w.json()["outputs"]["totals"]["fixed"]["E_y"]
            e_y_avg = (e_y_e + e_y_w) / 2

            print(f"\nŚrednia E-W (crystSi2025): {e_y_avg:.1f} kWh/kWp/rok")
            print(f"PVsyst reference (E-W):     963 kWh/kWp/rok")
            diff_pct = (e_y_avg - 963) / 963 * 100
            print(f"Różnica vs PVsyst:          {diff_pct:+.1f}%")
    except Exception as e:
        print(f"Błąd: {e}")


if __name__ == "__main__":
    test_pvtech_comparison()
    test_ew_orientation()
