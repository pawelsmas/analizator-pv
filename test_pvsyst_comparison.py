"""
Porównanie obliczeń PVGIS/pvlib z PVsyst dla projektu Dębienko.

PVsyst dane referencyjne:
- Lokalizacja: 52.30°N, 16.72°E, 69m (Dębno)
- Dane pogodowe: Meteonorm 8.2 (2001-2020)
- Moc DC: 1115 kWp
- Moc AC: 1000 kWac
- DC:AC ratio: 1.115
- Orientacja: E-W tracking (20°/90° i 20°/-90°)
- Produkcja P50: 1073.8 MWh/rok
- Produkcja specyficzna: 963 kWh/kWp/rok
- PR: 88.94%
"""

import requests
import json

# Konfiguracja
PVGIS_API = "https://re.jrc.ec.europa.eu/api/v5_3"
PVCALC_SERVICE = "http://localhost:8002"
PVGIS_PROXY = "http://localhost:8020"

# Parametry projektu Dębienko
LAT = 52.30
LON = 16.72
ELEV = 69

# PVsyst reference values
PVSYST_P50 = 1073.8  # MWh/rok
PVSYST_SPECIFIC = 963  # kWh/kWp/rok
PVSYST_PR = 88.94  # %
PVSYST_DC_KWP = 1115

def test_pvgis_direct():
    """Test 1: Bezpośrednie zapytanie do PVGIS API (PVcalc)"""
    print("\n" + "="*60)
    print("TEST 1: PVGIS API bezpośrednio (PVcalc)")
    print("="*60)

    # PVGIS PVcalc dla 1 kWp
    params = {
        "lat": LAT,
        "lon": LON,
        "peakpower": 1,
        "loss": 14,  # Standard loss
        "pvtechchoice": "crystSi",
        "mountingplace": "free",
        "raddatabase": "PVGIS-SARAH3",
        "outputformat": "json",
        "optimalangles": 1  # Optimal south-facing
    }

    try:
        response = requests.get(f"{PVGIS_API}/PVcalc", params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        outputs = data.get("outputs", {})
        totals = outputs.get("totals", {})
        fixed = totals.get("fixed", {})

        e_y = fixed.get("E_y", 0)  # kWh/kWp/rok
        sd_y = fixed.get("SD_y", 0)

        print(f"Lokalizacja: {LAT}°N, {LON}°E")
        print(f"Baza danych: PVGIS-SARAH3")
        print(f"Produkcja E_y: {e_y:.1f} kWh/kWp/rok (optymalny kąt)")
        print(f"Odchylenie SD_y: {sd_y:.1f} kWh")

        # Porównanie z PVsyst
        diff_pct = (e_y - PVSYST_SPECIFIC) / PVSYST_SPECIFIC * 100
        print(f"\nPVsyst specific: {PVSYST_SPECIFIC} kWh/kWp/rok")
        print(f"Różnica: {diff_pct:+.1f}%")

        return e_y

    except Exception as e:
        print(f"Błąd: {e}")
        return None


def test_pvgis_ew_orientation():
    """Test 2: PVGIS dla orientacji E-W (jak w PVsyst)"""
    print("\n" + "="*60)
    print("TEST 2: PVGIS API dla orientacji E-W")
    print("="*60)

    results = []

    # Orientacja wschód (azimut -90)
    params_east = {
        "lat": LAT,
        "lon": LON,
        "peakpower": 1,
        "loss": 14,
        "pvtechchoice": "crystSi",
        "mountingplace": "free",
        "raddatabase": "PVGIS-SARAH3",
        "outputformat": "json",
        "angle": 20,
        "aspect": -90  # East
    }

    # Orientacja zachód (azimut 90)
    params_west = {
        "lat": LAT,
        "lon": LON,
        "peakpower": 1,
        "loss": 14,
        "pvtechchoice": "crystSi",
        "mountingplace": "free",
        "raddatabase": "PVGIS-SARAH3",
        "outputformat": "json",
        "angle": 20,
        "aspect": 90  # West
    }

    try:
        # East
        response_e = requests.get(f"{PVGIS_API}/PVcalc", params=params_east, timeout=30)
        response_e.raise_for_status()
        data_e = response_e.json()
        e_y_east = data_e["outputs"]["totals"]["fixed"]["E_y"]

        # West
        response_w = requests.get(f"{PVGIS_API}/PVcalc", params=params_west, timeout=30)
        response_w.raise_for_status()
        data_w = response_w.json()
        e_y_west = data_w["outputs"]["totals"]["fixed"]["E_y"]

        # Średnia E-W (jak w PVsyst - 50% każda orientacja)
        e_y_avg = (e_y_east + e_y_west) / 2

        print(f"Orientacja E (20°, azymut -90°): {e_y_east:.1f} kWh/kWp/rok")
        print(f"Orientacja W (20°, azymut 90°): {e_y_west:.1f} kWh/kWp/rok")
        print(f"Średnia E-W: {e_y_avg:.1f} kWh/kWp/rok")

        # Porównanie z PVsyst
        diff_pct = (e_y_avg - PVSYST_SPECIFIC) / PVSYST_SPECIFIC * 100
        print(f"\nPVsyst specific (E-W): {PVSYST_SPECIFIC} kWh/kWp/rok")
        print(f"Różnica: {diff_pct:+.1f}%")

        return e_y_avg

    except Exception as e:
        print(f"Błąd: {e}")
        return None


def test_pvgis_tmy():
    """Test 3: PVGIS TMY data"""
    print("\n" + "="*60)
    print("TEST 3: PVGIS TMY (dane godzinowe)")
    print("="*60)

    params = {
        "lat": LAT,
        "lon": LON,
        "outputformat": "json"
    }

    try:
        response = requests.get(f"{PVGIS_API}/tmy", params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        hourly = data.get("outputs", {}).get("tmy_hourly", [])

        # Suma GHI rocznego
        ghi_sum = sum(h.get("G(h)", 0) for h in hourly) / 1000  # kWh/m²

        print(f"Liczba godzin TMY: {len(hourly)}")
        print(f"Suma GHI rocznego: {ghi_sum:.1f} kWh/m²/rok")

        # Szacunkowa produkcja przy PR=89%
        est_production = ghi_sum * 0.89
        print(f"Szacunkowa produkcja (PR=89%): {est_production:.0f} kWh/kWp/rok")

        return ghi_sum

    except Exception as e:
        print(f"Błąd: {e}")
        return None


def test_pvgis_seriescalc():
    """Test 4: PVGIS seriescalc (wieloletnie dane)"""
    print("\n" + "="*60)
    print("TEST 4: PVGIS Seriescalc (2005-2023)")
    print("="*60)

    # Test E-W orientation average
    for orientation, aspect in [("South (optimal)", 0), ("East", -90), ("West", 90)]:
        params = {
            "lat": LAT,
            "lon": LON,
            "peakpower": 1,
            "loss": 14,
            "pvtechchoice": "crystSi",
            "mountingplace": "free",
            "raddatabase": "PVGIS-SARAH3",
            "startyear": 2005,
            "endyear": 2023,
            "outputformat": "json",
            "pvcalculation": 1,
            "angle": 20 if aspect != 0 else None,
            "aspect": aspect
        }

        if params["angle"] is None:
            params["optimalangles"] = 1
            del params["angle"]

        try:
            response = requests.get(f"{PVGIS_API}/seriescalc", params=params, timeout=90)
            response.raise_for_status()
            data = response.json()

            hourly = data.get("outputs", {}).get("hourly", [])

            # Grupuj po latach
            yearly = {}
            for h in hourly:
                time_str = h.get("time", "")
                if len(time_str) >= 4:
                    year = int(time_str[:4])
                    power = h.get("P", 0)  # W
                    if year not in yearly:
                        yearly[year] = 0
                    yearly[year] += power / 1000  # kWh

            values = list(yearly.values())
            avg = sum(values) / len(values)

            print(f"\n{orientation}:")
            print(f"  Średnia roczna: {avg:.0f} kWh/kWp")
            print(f"  Min: {min(values):.0f}, Max: {max(values):.0f}")

        except Exception as e:
            print(f"Błąd dla {orientation}: {e}")


def test_our_pvcalc_service():
    """Test 5: Nasz serwis pv-calculation"""
    print("\n" + "="*60)
    print("TEST 5: Nasz serwis pv-calculation")
    print("="*60)

    try:
        # Test health
        health = requests.get(f"{PVCALC_SERVICE}/health", timeout=5)
        print(f"Serwis status: {health.json()}")

        # Test generowania profilu PV
        payload = {
            "pv_type": "ground_ew",  # E-W orientation
            "yield_target": 1050,
            "dc_ac_ratio": 1.115,
            "latitude": LAT,
            "longitude": LON,
            "use_pvgis": True,
            "albedo": 0.2,
            "soiling_loss": 0.02
        }

        response = requests.post(
            f"{PVCALC_SERVICE}/pv/generate-profile",
            json=payload,
            timeout=60
        )

        if response.status_code == 200:
            data = response.json()
            annual_yield = data.get("annual_yield", 0)
            peak_power = data.get("peak_power", 0)
            pvlib_used = data.get("pvlib_used", False)

            print(f"\nWynik generowania profilu:")
            print(f"  Annual yield: {annual_yield:.0f} kWh/kWp")
            print(f"  Peak power: {peak_power:.3f} kW/kWp")
            print(f"  PVLIB used: {pvlib_used}")

            diff_pct = (annual_yield - PVSYST_SPECIFIC) / PVSYST_SPECIFIC * 100
            print(f"\n  PVsyst reference: {PVSYST_SPECIFIC} kWh/kWp")
            print(f"  Różnica: {diff_pct:+.1f}%")

            return annual_yield
        else:
            print(f"Błąd: {response.status_code} - {response.text}")

    except requests.exceptions.ConnectionError:
        print("Serwis niedostępny (docker nie działa?)")
    except Exception as e:
        print(f"Błąd: {e}")

    return None


def test_pvgis_proxy_service():
    """Test 6: Nasz PVGIS proxy service"""
    print("\n" + "="*60)
    print("TEST 6: Nasz PVGIS Proxy Service")
    print("="*60)

    try:
        # Test pvcalc endpoint
        payload = {
            "lat": LAT,
            "lon": LON,
            "peakpower": 1.0,
            "loss": 14.0,
            "raddatabase": "PVGIS-SARAH3",
            "angle": 20,
            "aspect": 0  # South for comparison
        }

        response = requests.post(
            f"{PVGIS_PROXY}/pvgis/pvcalc",
            json=payload,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            print(f"E_y: {data.get('e_y_kwh', 0):.1f} kWh/kWp")
            print(f"P50 factor: {data.get('p50_factor', 0):.4f}")
            print(f"P75 factor: {data.get('p75_factor', 0):.4f}")
            print(f"P90 factor: {data.get('p90_factor', 0):.4f}")
            print(f"Method: {data.get('method', '')}")
        else:
            print(f"Błąd: {response.status_code}")

    except requests.exceptions.ConnectionError:
        print("Proxy niedostępny (docker nie działa?)")
    except Exception as e:
        print(f"Błąd: {e}")


def compare_databases():
    """Test 7: Porównanie baz danych PVGIS vs Meteonorm"""
    print("\n" + "="*60)
    print("TEST 7: Porównanie baz danych")
    print("="*60)

    databases = ["PVGIS-SARAH3", "PVGIS-SARAH2", "PVGIS-ERA5"]

    for db in databases:
        params = {
            "lat": LAT,
            "lon": LON,
            "peakpower": 1,
            "loss": 14,
            "pvtechchoice": "crystSi",
            "mountingplace": "free",
            "raddatabase": db,
            "outputformat": "json",
            "angle": 20,
            "aspect": 0
        }

        try:
            response = requests.get(f"{PVGIS_API}/PVcalc", params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                e_y = data["outputs"]["totals"]["fixed"]["E_y"]
                print(f"{db}: {e_y:.1f} kWh/kWp/rok")
            else:
                print(f"{db}: niedostępne ({response.status_code})")
        except Exception as e:
            print(f"{db}: błąd - {e}")

    print(f"\nPVsyst używa: Meteonorm 8.2 (2001-2020)")
    print(f"PVsyst specific: {PVSYST_SPECIFIC} kWh/kWp/rok")


def main():
    print("="*60)
    print("PORÓWNANIE PVGIS vs PVsyst")
    print("Projekt: Dębienko")
    print("="*60)
    print(f"\nParametry referencyjne PVsyst:")
    print(f"  Lokalizacja: {LAT}°N, {LON}°E, {ELEV}m")
    print(f"  Dane pogodowe: Meteonorm 8.2 (2001-2020)")
    print(f"  Orientacja: E-W (20°/-90° i 20°/90°)")
    print(f"  Produkcja P50: {PVSYST_P50} MWh/rok")
    print(f"  Produkcja specyficzna: {PVSYST_SPECIFIC} kWh/kWp/rok")
    print(f"  Performance Ratio: {PVSYST_PR}%")

    # Testy bezpośrednio do PVGIS
    test_pvgis_direct()
    test_pvgis_ew_orientation()
    test_pvgis_tmy()
    test_pvgis_seriescalc()
    compare_databases()

    # Testy naszych serwisów (wymagają działającego Dockera)
    test_our_pvcalc_service()
    test_pvgis_proxy_service()

    print("\n" + "="*60)
    print("PODSUMOWANIE")
    print("="*60)
    print("""
Główne różnice między PVGIS a PVsyst/Meteonorm:
1. Baza danych meteorologicznych:
   - PVGIS: SARAH3 (satelitarne, 2005-2023)
   - PVsyst: Meteonorm 8.2 (interpolowane, 2001-2020)

2. Model promieniowania:
   - PVGIS: własny model JRC
   - PVsyst: model Perez, Meteonorm

3. Straty systemowe:
   - PVGIS: uproszczone (jeden parametr loss%)
   - PVsyst: szczegółowe (IAM, temp, mismatch, okablowanie, etc.)

Oczekiwana różnica: 3-8% między PVGIS a Meteonorm dla Polski.
""")


if __name__ == "__main__":
    main()
