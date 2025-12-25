# Dokumentacja Techniczna Modułu BESS
## Battery Energy Storage System - Magazyn Energii

**Wersja:** 3.9
**Data:** 2025-12-23
**Autor:** Analizator PV
**Engine Version:** 1.2.0
**Service Version:** 1.1.0
**Frontend Version:** 3.14

---

## Spis Treści

1. [Przegląd Systemu](#1-przegląd-systemu)
2. [Tryby Pracy BESS](#2-tryby-pracy-bess)
3. [Algorytmy Doboru Pojemności](#3-algorytmy-doboru-pojemności)
4. [Symulacja Dispatch (Sterowanie)](#4-symulacja-dispatch-sterowanie)
5. [Obliczenia Ekonomiczne](#5-obliczenia-ekonomiczne)
6. [Parametry Techniczne](#6-parametry-techniczne)
7. [API i Endpointy](#7-api-i-endpointy)
8. [Przykłady Obliczeń](#8-przykłady-obliczeń)
9. [Do Rozwoju - Strategie Rozładowywania](#9-do-rozwoju---strategie-rozładowywania-bess)
10. [Szczegółowy Opis Algorytmów](#10-szczegółowy-opis-algorytmów)
11. [Nowe Funkcjonalności v3.7-3.14](#11-nowe-funkcjonalności-v37)

---

## 1. Przegląd Systemu

### 1.1 Architektura Modułu BESS

System BESS składa się z następujących komponentów:

```
┌─────────────────────────────────────────────────────────────────┐
│                     MODUŁY BESS                                  │
├─────────────────┬─────────────────┬─────────────────────────────┤
│  pv-calculation │    economics    │      profile-analysis       │
│  (auto_size_    │ (bess_optimizer │   (simulate_bess_universal) │
│   bess_lite)    │    .py)         │                             │
├─────────────────┼─────────────────┼─────────────────────────────┤
│  LIGHT Mode     │  Peak Shaving   │   Autokonsumpcja +          │
│  Autokonsumpcja │  PyPSA+HiGHS    │   Peak Shaving +            │
│                 │                 │   Arbitraż Cenowy           │
└─────────────────┴─────────────────┴─────────────────────────────┘
```

### 1.2 Główne Funkcje

| Funkcja | Moduł | Opis |
|---------|-------|------|
| `auto_size_bess_lite()` | pv-calculation | Dobór BESS do autokonsumpcji (LIGHT mode) |
| `optimize_bess()` | economics | Dobór BESS do peak shaving (LP/MIP) |
| `simulate_pv_system_with_bess()` | pv-calculation | Symulacja godzinowa PV+BESS |
| `simulate_bess_universal()` | profile-analysis | Symulacja z peak shaving i arbitrażem |

---

## 2. Tryby Pracy BESS

### 2.1 Tryb LIGHT (Autokonsumpcja)

**Cel:** Maksymalizacja autokonsumpcji energii z PV w modelu 0-Export.

**Działanie:**
- Nadwyżka PV → ładowanie baterii
- Deficyt energii → rozładowanie baterii
- Bateria pełna + nadwyżka → curtailment (strata)
- Deficyt > pojemność BESS → import z sieci

**Algorytm doboru (iteracyjny NPV):**

```python
# Zakres testowanych mocy: 10% do 100% percentyla 75 nadwyżki
p_max_candidate = percentile(surplus, 75)
power_steps = linspace(p_max_candidate * 0.1, p_max_candidate, 10)

for each power in power_steps:
    energy = power * duration_hours
    dispatch = simulate_quick_dispatch(power, energy)

    # Poprawny wzór: baseline vs project
    baseline_cost = sum(max(0, load - pv) * dt) * price  # bez BESS
    project_cost = dispatch.grid_import_kwh * price       # z BESS
    annual_savings = baseline_cost - project_cost

    capex = power * capex_per_kw + energy * capex_per_kwh
    annual_cost = capex * annuity_factor
    npv = (annual_savings - annual_cost) / annuity_factor

    if npv > best_npv:
        best_power, best_energy = power, energy
```

### 2.2 Tryb PRO (Optymalizacja LP/MIP)

**Cel:** Optymalny dobór BESS przy użyciu solverów optymalizacyjnych.

**Biblioteki:**
- **PyPSA** (Python for Power System Analysis) v0.27.1
- **HiGHS** (High-performance LP/MIP solver) v1.7.1

**Model optymalizacji:**

```
Minimalizuj: CAPEX = E * capex_per_kwh + P * capex_per_kw

Ograniczenia:
  SOC(t) = SOC(t-1) + charge(t) × η - discharge(t) / η
  SOC_min ≤ SOC(t) ≤ SOC_max
  charge(t) ≤ P
  discharge(t) ≤ P
  discharge(t) ≥ excess(t)   dla każdej godziny przekroczenia
  SOC(0) = SOC(T)            (cykliczność)
```

### 2.3 Peak Shaving

**Cel:** Redukcja szczytów mocy w celu zmniejszenia opłat mocowych.

**Parametry:**
- `peak_shaving_threshold_kw` - próg mocy [kW]
- `power_charge_pln_per_kw_month` - opłata mocowa [PLN/kW/miesiąc]

**Algorytm grupowania bloków przekroczenia:**

```python
def group_exceedance_blocks(load_profile, threshold):
    blocks = []
    current_block = None

    for i, power in enumerate(load_profile):
        excess = power - threshold

        if excess > 0:
            if current_block is None:
                current_block = {'start': i, 'powers': [], 'excesses': []}
            current_block['powers'].append(power)
            current_block['excesses'].append(excess)
        else:
            if current_block is not None:
                # Zamknij blok
                block = BESSBlock(
                    duration_hours = len(current_block['powers']),
                    total_energy_kwh = sum(excesses) * hours_per_interval,
                    max_excess_kw = max(excesses)
                )
                blocks.append(block)
                current_block = None

    return blocks
```

**Heurystyka doboru:**

```
Pojemność = (energia największego bloku / sprawność) / DOD × margines
Moc = max_deficyt × margines
```

### 2.4 Arbitraż Cenowy

**Cel:** Kupowanie energii gdy tania, sprzedawanie gdy droga.

**Parametry:**
- `buy_threshold_pln_mwh` - próg kupna (np. 300 PLN/MWh)
- `sell_threshold_pln_mwh` - próg sprzedaży (np. 600 PLN/MWh)

**Logika:**
```
if cena < buy_threshold AND soc < soc_max:
    ładuj z sieci
elif cena > sell_threshold AND soc > soc_min:
    rozładowuj do sieci (lub obciążenia)
```

---

## 3. Algorytmy Doboru Pojemności

### 3.1 Metoda Heurystyczna (LIGHT)

**Lokalizacja:** `pv-calculation/app.py` → `auto_size_bess_lite()`

**Kroki:**
1. Oblicz profil nadwyżki: `surplus = PV_production - direct_consumption`
2. Określ zakres testowanych mocy: `10% - 100%` percentyla 75 nadwyżki
3. Dla każdej mocy testowej:
   - Oblicz pojemność: `energy = power × duration`
   - Symuluj dispatch i oblicz roczne rozładowanie
   - Oblicz NPV
4. Wybierz konfigurację z najwyższym NPV

**Wzór NPV:**

```
Poprawny wzór (baseline vs project):
  annual_savings = baseline_cost - project_cost
  gdzie:
    baseline_cost = Σ max(0, load - pv) × Δt × price  (bez BESS)
    project_cost = Σ grid_import × Δt × price        (z BESS)

Uproszczenie (przybliżone):
  annual_savings ≈ annual_discharge × energy_price
  (niedokładne - ignoruje straty sprawności i interakcje PV/Load)

NPV = Σ(t=1..n) [(savings - opex) / (1+r)^t] - CAPEX
```

### 3.2 Metoda PyPSA+HiGHS (PRO)

**Lokalizacja:** `economics/bess_optimizer.py` → `optimize_bess_pypsa()`

**Model PyPSA:**

```python
network = pypsa.Network()
network.set_snapshots(range(n_hours))

# Magistrala
network.add("Bus", "main_bus")

# Obciążenie (nadwyżka ponad próg)
network.add("Load", "peak_excess",
            bus="main_bus",
            p_set=excess)

# Magazyn energii z optymalizowaną pojemnością
network.add("Store", "bess",
            bus="main_bus",
            e_nom_extendable=True,      # Optymalizuj pojemność
            e_nom_min=0,
            e_nom_max=1e6,
            e_min_pu=soc_min,           # Min SOC
            e_max_pu=soc_max,           # Max SOC
            e_cyclic=True,              # SOC(0) = SOC(T)
            capital_cost=capex_per_kwh)

# Rozwiąż optymalizację
status = network.optimize(solver_name="highs")
optimal_capacity = network.stores.loc["bess", "e_nom_opt"]
```

### 3.3 Porównanie Metod

| Aspekt | Heurystyka | LP (PyPSA) | MIP (PyPSA) |
|--------|------------|------------|-------------|
| Czas obliczeń | <1 ms | 10-100 ms | 100 ms - 1 s |
| Dokładność | Dobra | Optymalna | Najwyższa |
| Wymagania | Brak | PyPSA+HiGHS | PyPSA+HiGHS |
| Zastosowanie | Szybkie szacunki | Produkcja | Finalne projekty |

---

## 4. Symulacja Dispatch (Sterowanie)

### 4.1 Algorytm Zachłanny (Greedy)

**Lokalizacja:** `pv-calculation/app.py` → `simulate_pv_system_with_bess()`

**Pseudokod:**

```python
for each hour h:
    pv = production[h]
    load = consumption[h]

    # Krok 1: Bezpośrednia autokonsumpcja
    direct = min(pv, load)
    surplus = pv - direct
    deficit = load - direct

    # Krok 2: Obsługa nadwyżki (ładowanie lub curtailment)
    if surplus > 0:
        charge_power = min(surplus, bess_power_kw)
        available_space = soc_max_kwh - soc
        charge_energy = min(charge_power * η, available_space)

        soc += charge_energy
        curtailed = surplus - (charge_energy / η)

    # Krok 3: Obsługa deficytu (rozładowanie lub import)
    if deficit > 0:
        discharge_power = min(deficit, bess_power_kw)
        available_energy = soc - soc_min_kwh
        discharge_from_soc = min(discharge_power / η, available_energy)
        discharge_delivered = discharge_from_soc * η

        soc -= discharge_from_soc
        grid_import = deficit - discharge_delivered
```

### 4.2 Sprawność Ładowania/Rozładowania

**Sprawność jednorazowa (one-way):**

```
η_one_way = √(η_roundtrip)

Przykład: η_roundtrip = 90% → η_one_way = 94.87%
```

**Straty energii:**
- Ładowanie: `E_stored = E_input × η_one_way`
- Rozładowanie: `E_output = E_stored × η_one_way`
- Łączne: `E_output = E_input × η_roundtrip`

### 4.3 Obliczanie Cykli

```python
# Cykle ekwiwalentne roczne
annual_cycles = total_discharged_kwh / usable_capacity_kwh

gdzie:
  usable_capacity = bess_energy_kwh × (soc_max - soc_min)
  usable_capacity = bess_energy_kwh × (0.9 - 0.1) = 0.8 × bess_energy_kwh
```

---

## 5. Obliczenia Ekonomiczne

### 5.1 CAPEX (Nakład Inwestycyjny)

```
CAPEX = (pojemność × capex_per_kwh) + (moc × capex_per_kw)

Domyślne wartości:
  capex_per_kwh = 1500 PLN/kWh
  capex_per_kw = 300 PLN/kW

Przykład: 100 kW / 200 kWh
  CAPEX = 200 × 1500 + 100 × 300 = 330 000 PLN
```

### 5.2 OPEX (Koszty Operacyjne)

```
OPEX_annual = CAPEX × opex_pct_per_year

Domyślnie: opex_pct_per_year = 1.5%

Przykład:
  OPEX = 330 000 × 0.015 = 4 950 PLN/rok
```

### 5.3 NPV (Wartość Bieżąca Netto)

```
NPV = Σ(t=1..n) [(savings_t - opex_t) / (1+r)^t] - CAPEX

gdzie:
  savings_t = baseline_cost_t - project_cost_t

  baseline_cost_t = Σ(h) max(0, load[h] - pv[h]) × Δt × energy_price
                  (koszt zakupu energii BEZ magazynu)

  project_cost_t = Σ(h) grid_import[h] × Δt × energy_price
                 (koszt zakupu energii Z magazynem)

  r = stopa dyskontowa
  n = okres analizy

UWAGA: Uproszczenie "savings = discharge × price" jest niedokładne!
       Poprawny wzór porównuje koszty baseline vs project.
```

**Kod źródłowy (dispatch_engine.py):**
```python
# Baseline: bez magazynu
baseline_import = np.maximum(load_kw - pv_kw, 0)
baseline_cost = np.sum(baseline_import * dt_hours) * import_price

# Project: z magazynem
project_cost = total_grid_import_kwh * import_price

# Oszczędności
annual_savings = baseline_cost - project_cost
```

### 5.4 Prosty Okres Zwrotu (Payback)

```
Payback = CAPEX / annual_savings

Przykład:
  CAPEX = 330 000 PLN
  annual_savings = 50 000 PLN/rok
  Payback = 330 000 / 50 000 = 6.6 lat
```

### 5.5 LCOE BESS (Levelized Cost of Energy)

```
LCOE = (CAPEX + Σ OPEX_discounted) / (Σ Energy_discharged_discounted)

Jednostka: PLN/MWh
```

### 5.6 Oszczędności z Peak Shaving

```
monthly_savings = peak_reduction_kw × power_charge_pln_per_kw
annual_savings = monthly_savings × 12

gdzie:
  peak_reduction_kw = original_peak - new_peak
  power_charge_pln_per_kw = opłata mocowa (np. 50 PLN/kW/miesiąc)
```

---

## 6. Parametry Techniczne

### 6.1 Parametry SOC (State of Charge)

| Parametr | Domyślna | Zakres | Opis |
|----------|----------|--------|------|
| `soc_min` | 10% | 0-50% | Minimalna głębokość rozładowania |
| `soc_max` | 90% | 50-100% | Maksymalny stan naładowania |
| `soc_initial` | 50% | 10-90% | Początkowy stan naładowania |
| `DOD` | 80% | 50-100% | Głębokość rozładowania (soc_max - soc_min) |

### 6.2 Parametry Sprawności

| Parametr | Domyślna | Zakres | Opis |
|----------|----------|--------|------|
| `roundtrip_efficiency` | 90% | 70-98% | Sprawność cyklu ładowanie→rozładowanie |
| `standing_loss` | 0.01% | 0-1% | Straty postojowe na godzinę |
| `auxiliary_loss_pct_per_day` | 0.1% | 0-1% | Straty pomocnicze dziennie |

### 6.3 Parametry Żywotności

| Parametr | Domyślna | Zakres | Opis |
|----------|----------|--------|------|
| `cycle_life` | 6000 | 1000-10000 | Żywotność cyklowa |
| `calendar_life_years` | 15 | 5-25 | Żywotność kalendarzowa |
| `degradation_year1_pct` | 3.0% | 0-10% | Degradacja w pierwszym roku |
| `degradation_pct_per_year` | 1.5% | 0-5% | Degradacja roczna (kolejne lata) |

### 6.4 Parametry C-Rate

```
C-rate = Power_kW / Capacity_kWh

Przykłady:
  C-rate = 1.0  → 100 kW / 100 kWh → pełne rozładowanie w 1h
  C-rate = 0.5  → 50 kW / 100 kWh → pełne rozładowanie w 2h
  C-rate = 2.0  → 200 kW / 100 kWh → pełne rozładowanie w 0.5h
```

| Duration | C-rate | Zastosowanie |
|----------|--------|--------------|
| 1h | 1.0 | Peak shaving |
| 2h | 0.5 | Autokonsumpcja (standard) |
| 4h | 0.25 | Arbitraż cenowy, backup |

---

## 7. API i Endpointy

### 7.1 Endpoint: `/bess/optimize`

**Metoda:** POST
**Moduł:** economics

**Request:**
```json
{
  "load_profile_kw": [100, 120, 150, ...],
  "timestamps": ["2024-01-01T00:00:00", ...],
  "interval_minutes": 60,
  "peak_shaving_threshold_kw": 500,
  "bess_capex_per_kwh": 1500,
  "bess_capex_per_kw": 300,
  "depth_of_discharge": 0.8,
  "round_trip_efficiency": 0.90,
  "max_c_rate": 1.0,
  "method": "lp_relaxed"
}
```

**Response:**
```json
{
  "optimal_capacity_kwh": 200.0,
  "optimal_power_kw": 100.0,
  "capex_total_pln": 330000,
  "annual_opex_pln": 4950,
  "usable_capacity_kwh": 160.0,
  "total_annual_cycles": 250,
  "expected_lifetime_years": 15,
  "sizing_rationale": "PyPSA+HiGHS LP: optymalna pojemność 200 kWh...",
  "warnings": []
}
```

### 7.2 Endpoint: `/analyze` (z BESS)

**Metoda:** POST
**Moduł:** pv-calculation

**Request z BESS LIGHT:**
```json
{
  "consumption": [50, 60, 70, ...],
  "timestamps": ["2024-01-01T00:00:00", ...],
  "pv_config": {...},
  "bess_config": {
    "enabled": true,
    "mode": "light",
    "duration": "2",
    "roundtrip_efficiency": 0.90,
    "soc_min": 0.10,
    "soc_max": 0.90,
    "capex_per_kwh": 1500,
    "capex_per_kw": 300
  }
}
```

### 7.3 Endpoint: `/bess/methods`

**Metoda:** GET
**Moduł:** economics

**Response:**
```json
{
  "heuristic": {
    "name": "Heurystyka",
    "description": "Szybka metoda bazująca na największym bloku przeciążenia",
    "pros": ["Bardzo szybka (<1ms)", "Nie wymaga solvera"],
    "cons": ["Może dawać przewymiarowane wyniki"]
  },
  "lp_relaxed": {
    "name": "LP (PyPSA+HiGHS)",
    "description": "Optymalizacja liniowa z PyPSA i solverem HiGHS",
    "pros": ["Optymalne rozwiązanie", "Szybka (10-100ms)"]
  },
  "mip_full": {
    "name": "MIP (PyPSA+HiGHS)",
    "description": "Pełna optymalizacja mieszana całkowitoliczbowa"
  }
}
```

---

## 8. Przykłady Obliczeń

### 8.1 Przykład: Dobór BESS do Autokonsumpcji

**Dane wejściowe:**
- Roczna produkcja PV: 1 200 MWh
- Roczne zużycie: 1 000 MWh
- Autokonsumpcja bez BESS: 600 MWh (50%)
- Nadwyżka PV: 600 MWh
- Cena energii: 800 PLN/MWh

**Obliczenia:**
```
1. Percentyl 75 nadwyżki godzinowej: 150 kW
2. Zakres testowy: 15 kW - 150 kW (10 kroków)
3. Duration: 2h → Energy = Power × 2

Dla Power = 75 kW, Energy = 150 kWh (η_rt = 90%):

  Scenariusz baseline (bez BESS):
  - Import z sieci: 400 MWh (= zużycie 1000 - autokonsumpcja 600)
  - baseline_cost = 400 MWh × 800 PLN/MWh = 320 000 PLN

  Scenariusz project (z BESS):
  - Roczne rozładowanie: ~180 MWh
  - Straty roundtrip: 180 × (1 - 0.9) = 18 MWh
  - Dodatkowa autokonsumpcja: 180 - 18 = 162 MWh
  - Import z sieci: 400 - 162 = 238 MWh
  - project_cost = 238 MWh × 800 PLN/MWh = 190 400 PLN

  Roczne oszczędności (poprawny wzór):
  - annual_savings = baseline_cost - project_cost
  - annual_savings = 320 000 - 190 400 = 129 600 PLN

  Ekonomika:
  - CAPEX: 150 × 1500 + 75 × 300 = 247 500 PLN
  - Annuity factor (7%, 15 lat): 0.1098
  - Roczny koszt: 247 500 × 0.1098 = 27 175 PLN
  - NPV: (129 600 - 27 175) / 0.1098 = 933 000 PLN
  - EFC/rok: 180 MWh / (150 kWh × 0.8) = 1500 cykli/rok

Optymalny dobór: 75 kW / 150 kWh
```

> **Uwaga:** Uproszczony wzór `180 × 0.8 = 144 000 PLN` zawyża oszczędności,
> ponieważ ignoruje straty sprawności (10%) i interakcje profili PV/load.

### 8.2 Przykład: Peak Shaving

**Dane wejściowe:**
- Moc szczytowa: 1 200 kW
- Próg peak shaving: 1 000 kW
- Opłata mocowa: 50 PLN/kW/miesiąc

**Analiza bloków przekroczenia:**
```
Blok 1: 14:00-16:00, max 1150 kW, energia 250 kWh
Blok 2: 18:00-19:00, max 1100 kW, energia 80 kWh
Blok 3: 10:00-11:00, max 1080 kW, energia 60 kWh

Największy blok: 250 kWh, max excess: 150 kW
```

**Dobór BESS (heurystyka):**
```
Pojemność = (250 / 0.90) / 0.8 × 1.2 = 416 kWh
Moc = 150 × 1.2 = 180 kW

Sprawdzenie C-rate: 180 / 416 = 0.43 < 1.0 ✓
```

**Oszczędności:**
```
Redukcja szczytu: 1200 - 1000 = 200 kW
Miesięczne oszczędności: 200 × 50 = 10 000 PLN
Roczne oszczędności: 120 000 PLN
```

### 8.3 Przykład: Model Degradacji

**Parametry:**
- Pojemność początkowa: 200 kWh
- Degradacja rok 1: 3%
- Degradacja kolejne lata: 1.5%/rok
- Okres analizy: 15 lat

**Obliczenia pojemności:**
```
Rok 0:  200.0 kWh (100%)
Rok 1:  194.0 kWh (97%)
Rok 2:  191.1 kWh (95.5%)
Rok 5:  182.5 kWh (91.2%)
Rok 10: 169.0 kWh (84.5%)
Rok 15: 156.3 kWh (78.1%)
```

**Wpływ na energię roczną:**
```
Rok 1:  energia × 0.97
Rok 5:  energia × 0.912
Rok 10: energia × 0.845
Rok 15: energia × 0.781
```

---

## Załączniki

### A. Struktura Plików

```
services/
├── pv-calculation/
│   └── app.py
│       ├── auto_size_bess_lite()      # Dobór LIGHT
│       ├── simulate_pv_system_with_bess()  # Symulacja
│       └── BESSConfigLite             # Model konfiguracji
│
├── economics/
│   ├── app.py
│   │   ├── /bess/optimize             # Endpoint optymalizacji
│   │   └── /bess/methods              # Endpoint metod
│   └── bess_optimizer.py
│       ├── optimize_bess()            # Główna funkcja
│       ├── optimize_bess_heuristic()  # Metoda heurystyczna
│       ├── optimize_bess_pypsa()      # Metoda LP/MIP
│       └── group_exceedance_blocks()  # Grupowanie bloków
│
├── profile-analysis/
│   └── app.py
│       ├── simulate_bess_universal()  # Symulacja uniwersalna
│       └── calculate_bess_recommendations()
│
└── frontend-bess/
    ├── bess.js                        # Logika UI
    ├── index.html                     # Interfejs
    └── styles.css                     # Style
```

### B. Zależności

```
PyPSA==0.27.1          # Modelowanie systemów energetycznych
highspy==1.7.1         # Solver LP/MIP
numpy>=1.26.2          # Obliczenia numeryczne
pandas>=2.1.3          # Obsługa danych
```

### C. Słownik Terminów

| Termin | Opis |
|--------|------|
| **SOC** | State of Charge - stan naładowania baterii (0-100%) |
| **DOD** | Depth of Discharge - głębokość rozładowania |
| **C-rate** | Stosunek mocy do pojemności |
| **Curtailment** | Energia stracona (nie mogła być wykorzystana) |
| **Peak Shaving** | Redukcja szczytów mocy |
| **Arbitraż** | Kupowanie taniej, sprzedawanie drogo |
| **Roundtrip Efficiency** | Sprawność pełnego cyklu ładowanie→rozładowanie |
| **CAPEX** | Capital Expenditure - nakład inwestycyjny |
| **OPEX** | Operating Expenditure - koszty operacyjne |
| **NPV** | Net Present Value - wartość bieżąca netto |
| **LCOE** | Levelized Cost of Energy - uśredniony koszt energii |

---

## 9. Do Rozwoju - Strategie Rozładowywania BESS

### 9.1 Obecna Strategia (Reaktywna)

Aktualnie system używa **strategii reaktywnej (greedy)**:

```
1. Ładuj magazyn gdy jest nadwyżka PV (surplus = PV - Load > 0)
2. Rozładuj magazyn gdy jest deficyt (deficit = Load - PV > 0)
3. Rozładowanie następuje natychmiast po wykryciu deficytu
4. Nie ma "czekania" na osiągnięcie SOC 90% przed rozładowaniem
```

**Zalety:**
- Prosta implementacja
- Natychmiastowa reakcja na deficyt
- Maksymalizacja autokonsumpcji w danym momencie

**Wady:**
- Brak optymalizacji globalnej (dziennej/tygodniowej)
- Może rozładować magazyn przed wieczornym szczytem
- Nie uwzględnia predykcji profilu dnia

### 9.2 Strategia Predykcyjna (Predictive Dispatch)

**Koncepcja:** Znając profil PV i zużycia z góry (lub prognozę), optymalizujemy rozładowanie na cały dzień.

```python
def predictive_dispatch(pv_forecast, load_forecast, battery):
    """
    Optymalizacja rozładowania z wyprzedzeniem.

    1. Oblicz całkowity deficyt na dzień: total_deficit = Σ max(0, load - pv)
    2. Oblicz dostępną energię BESS: available_energy = (soc_max - soc_min) × capacity
    3. Ustal równomierny poziom rozładowania lub skup na godzinach szczytowych
    """
    daily_deficit_hours = get_deficit_hours(pv_forecast, load_forecast)
    energy_per_hour = min(
        available_energy / len(daily_deficit_hours),
        battery.power_kw
    )

    discharge_schedule = {}
    for hour in daily_deficit_hours:
        discharge_schedule[hour] = energy_per_hour

    return discharge_schedule
```

**Wymagania:**
- Prognoza PV (może być z danych historycznych PVGIS)
- Prognoza zużycia (profil typowego dnia)
- Solver optymalizacyjny lub heurystyka

**Zastosowanie:**
- Systemy z dostępem do prognoz pogodowych
- Instalacje przemysłowe ze stabilnym profilem zużycia

### 9.3 Wyższy Próg Rozładowania (Threshold-Based Discharge)

**Koncepcja:** Nie rozładowuj magazynu przy małych deficytach - zachowaj energię na większe szczyty.

```python
def threshold_dispatch(pv, load, battery, min_deficit_threshold_kw=10):
    """
    Rozładowanie tylko gdy deficyt przekracza próg.

    Parametry:
    - min_deficit_threshold_kw: minimalny deficyt do rozładowania

    Efekt:
    - Małe deficyty pokrywane z sieci (tani import)
    - Duże deficyty pokrywane z magazynu
    """
    deficit = load - pv

    if deficit > min_deficit_threshold_kw:
        # Rozładuj do pokrycia deficytu
        discharge = min(deficit, battery.power_kw, available_soc)
    else:
        # Mały deficyt - import z sieci
        discharge = 0
        grid_import = deficit

    return discharge, grid_import
```

**Parametry do konfiguracji:**
- `min_deficit_threshold_kw` - próg minimalnego deficytu (np. 10 kW)
- `priority_hours` - godziny priorytetowe do rozładowania (np. 17:00-21:00)

**Zastosowanie:**
- Systemy z opłatą mocową (peak shaving)
- Sytuacje gdy mały import z sieci jest tańszy niż zużycie cykli BESS

### 9.4 Równomierne Rozłożenie Discharge (Even Distribution)

**Koncepcja:** Rozładowuj magazyn równomiernie przez wszystkie godziny deficytowe, zamiast reaktywnie.

```python
def even_distribution_dispatch(pv_day, load_day, battery):
    """
    Rozłóż rozładowanie równomiernie przez dzień.

    Krok 1: Zidentyfikuj godziny deficytowe (load > pv)
    Krok 2: Oblicz sumę deficytów
    Krok 3: Ustal stałą moc rozładowania = min(total_deficit, capacity) / deficit_hours
    """
    deficit_hours = []
    total_deficit = 0

    for h in range(24):
        if load_day[h] > pv_day[h]:
            deficit_hours.append(h)
            total_deficit += load_day[h] - pv_day[h]

    # Energia do dystrybucji
    available_energy = (battery.soc_max - battery.soc_min) * battery.energy_kwh
    energy_to_distribute = min(total_deficit, available_energy)

    # Równomierna moc na godzinę
    if len(deficit_hours) > 0:
        power_per_hour = energy_to_distribute / len(deficit_hours)
        power_per_hour = min(power_per_hour, battery.power_kw)
    else:
        power_per_hour = 0

    # Schedule
    discharge_schedule = {h: power_per_hour for h in deficit_hours}
    return discharge_schedule
```

**Zalety:**
- Przewidywalne zachowanie magazynu
- Lepsza ochrona przed głębokim rozładowaniem
- Możliwość rezerwacji energii na wieczorne szczyty

**Wady:**
- Wymaga znajomości profilu całego dnia z góry
- Może nie w pełni wykorzystać pojemności

### 9.5 Priorytetyzacja Godzin Wieczornych (Evening Priority)

**Koncepcja:** Zachowaj większość energii na godziny wieczorne (17:00-21:00), gdy PV nie produkuje.

```python
def evening_priority_dispatch(pv, load, hour, battery, soc_current):
    """
    Priorytet rozładowania na godziny wieczorne.

    Zasady:
    - Przed 17:00: rozładuj tylko 30% dostępnej energii
    - 17:00-21:00: rozładuj bez ograniczeń
    - Po 21:00: normalne rozładowanie
    """
    deficit = load - pv
    if deficit <= 0:
        return 0

    if hour < 17:
        # Przed wieczorem - ograniczone rozładowanie
        max_discharge_pct = 0.30
        reserved_soc = battery.soc_max * 0.7  # Rezerwuj 70% na wieczór
        available = max(0, soc_current - reserved_soc)
    elif 17 <= hour <= 21:
        # Godziny wieczorne - pełne rozładowanie
        max_discharge_pct = 1.0
        available = soc_current - battery.soc_min
    else:
        # Po wieczorze - normalne rozładowanie
        max_discharge_pct = 1.0
        available = soc_current - battery.soc_min

    discharge = min(deficit, battery.power_kw, available * max_discharge_pct)
    return discharge
```

**Parametry:**
- `evening_start_hour` - początek okna wieczornego (np. 17)
- `evening_end_hour` - koniec okna wieczornego (np. 21)
- `reserve_fraction` - frakcja pojemności do rezerwacji (np. 0.7)

### 9.6 Strategia Oparta o Ceny (Price-Based Dispatch)

**Koncepcja:** Rozładowuj gdy cena energii jest wysoka, ładuj gdy niska.

```python
def price_based_dispatch(pv, load, price, battery, soc):
    """
    Dispatch oparty o ceny energii (TOU - Time of Use).

    Progi cenowe:
    - price < low_threshold: ładuj z sieci (jeśli tani import)
    - price > high_threshold: rozładuj maksymalnie
    - pomiędzy: normalna autokonsumpcja
    """
    LOW_PRICE_THRESHOLD = 300   # PLN/MWh
    HIGH_PRICE_THRESHOLD = 800  # PLN/MWh

    surplus = pv - load
    deficit = load - pv

    if price < LOW_PRICE_THRESHOLD and surplus <= 0:
        # Tania energia - ładuj z sieci
        charge = min(battery.power_kw, (battery.soc_max - soc) * battery.energy_kwh)
        grid_import = deficit + charge
        return 0, charge, grid_import

    elif price > HIGH_PRICE_THRESHOLD and deficit > 0:
        # Droga energia - rozładuj maksymalnie
        discharge = min(deficit, battery.power_kw, (soc - battery.soc_min) * battery.energy_kwh)
        return discharge, 0, deficit - discharge

    else:
        # Normalna autokonsumpcja
        # ... standardowa logika greedy
        pass
```

**Zastosowanie:**
- Rynki z dynamicznymi cenami energii (RDN, TGE)
- Prosumenci z taryfą dynamiczną

### 9.7 Strategia Hybrydowa (STACKED z Rezerwą)

**Obecna implementacja w `dispatch_stacked()`:**

```python
def dispatch_stacked(pv, load, battery, params):
    """
    Tryb STACKED: PV surplus + Peak Shaving z rezerwą SOC.

    Zasady:
    1. Rezerwuj część pojemności (reserve_fraction) na peak shaving
    2. Reszta dostępna dla PV surplus
    3. Przy przekroczeniu peak_limit - użyj rezerwę
    """
    reserve_soc = battery.soc_min + (battery.soc_max - battery.soc_min) * params.reserve_fraction

    # Dla PV surplus: rozładuj tylko do reserve_soc
    # Dla Peak Shaving: rozładuj do soc_min
```

### 9.8 Porównanie Strategii

| Strategia | Złożoność | Wymagania | Najlepsze dla |
|-----------|-----------|-----------|---------------|
| Reaktywna (Greedy) | Niska | Brak | Proste instalacje |
| Predykcyjna | Wysoka | Prognozy PV/Load | Przemysł |
| Próg rozładowania | Niska | Parametr progu | Peak shaving |
| Równomierne | Średnia | Profil dnia | Stabilne zużycie |
| Priorytet wieczorny | Średnia | Okno czasowe | Domy, biura |
| Oparta o ceny | Średnia | Dane cenowe | Arbitraż |
| STACKED | Średnia | Próg peak + rezerwa | Kombinacja usług |

### 9.9 Plan Implementacji

**Faza 1: Parametryzacja strategii**
```python
class DispatchStrategy(Enum):
    GREEDY = "greedy"           # Obecna
    PREDICTIVE = "predictive"   # Przyszła
    THRESHOLD = "threshold"     # Przyszła
    EVENING = "evening"         # Przyszła
    PRICE_BASED = "price"       # Przyszła
    STACKED = "stacked"         # Obecna
```

**Faza 2: Interfejs wyboru strategii**
- Dropdown w ustawieniach BESS
- Parametry dla każdej strategii

**Faza 3: Wizualizacja porównawcza**
- Wykres porównujący różne strategie
- Metryki: autokonsumpcja, curtailment, cykle, NPV

---

## 10. Szczegółowy Opis Algorytmów

### 10.1 Źródła Danych Wejściowych

#### Profil produkcji PV
```
Źródło: PVGIS API (Photovoltaic Geographical Information System)
URL: https://re.jrc.ec.europa.eu/api/v5_2/
Parametry: lokalizacja (lat/lon), kąt nachylenia, azymut, technologia modułów
Dane: Typowy Rok Meteorologiczny (TMY) - 8760 wartości godzinowych [kWh]
```

#### Profil zużycia energii
```
Źródło: Użytkownik (upload CSV/Excel) lub profil standardowy
Format: 8760 wartości godzinowych [kWh] lub 35040 wartości 15-minutowych
Walidacja: suma roczna, min/max, brak wartości ujemnych
```

#### Ceny energii
```
Źródła:
- TGE (Towarowa Giełda Energii) - ceny RDN/RDB
- Taryfy dystrybucyjne (G11, G12, C11, C21, B21)
- Ceny umowne użytkownika
Format: stała cena [PLN/MWh] lub profil godzinowy
```

### 10.2 Algorytm Grid Search (Iteracyjna Optymalizacja NPV)

**Lokalizacja:** `services/bess-optimizer/app.py` → `run_grid_search_optimization()`

> **Uwaga:** Nazwa funkcji była wcześniej `run_pypsa_optimization()` - zmieniona
> w wersji 1.2.0 dla lepszego odzwierciedlenia faktycznie używanego algorytmu
> (grid search z greedy dispatch, nie LP/MIP z PyPSA).

#### Schemat działania

```
┌─────────────────────────────────────────────────────────────────┐
│                    GRID SEARCH OPTIMIZER                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  DANE WEJŚCIOWE:                                                │
│  ├── pv_generation_kwh[8760]  ← Profil produkcji PV            │
│  ├── load_kwh[8760]           ← Profil zużycia                 │
│  ├── min/max_power_kw         ← Ograniczenia mocy              │
│  ├── min/max_energy_kwh       ← Ograniczenia pojemności        │
│  ├── duration_min/max_h       ← Ograniczenia E/P ratio         │
│  ├── capex_per_kw/kwh         ← Koszty inwestycyjne            │
│  ├── energy_price_plnmwh      ← Cena energii                   │
│  └── discount_rate            ← Stopa dyskontowa               │
│                                                                 │
│  OBLICZENIA WSTĘPNE:                                            │
│  ├── net_load = load - pv     ← Bilans energetyczny            │
│  ├── surplus = max(-net, 0)   ← Nadwyżka PV do ładowania       │
│  └── deficit = max(net, 0)    ← Deficyt do rozładowania        │
│                                                                 │
│  SIATKA PRZESZUKIWANIA:                                         │
│  ├── power_range = linspace(min_power, max_power, 15)          │
│  └── duration_options = [min_h, (min+max)/2, max_h]            │
│                                                                 │
│  DLA KAŻDEJ KOMBINACJI (power, duration):                       │
│  │   energy = power × duration                                  │
│  │   IF energy w zakresie [min_energy, max_energy]:             │
│  │   │                                                          │
│  │   │   SYMULACJA DISPATCH (8760 kroków):                     │
│  │   │   └── dispatch = simulate_bess_dispatch(...)            │
│  │   │                                                          │
│  │   │   OBLICZENIE EKONOMICZNE:                                │
│  │   │   ├── baseline_cost = Σ max(0, load-pv) × price         │
│  │   │   ├── project_cost = Σ grid_import × price              │
│  │   │   ├── annual_savings = baseline_cost - project_cost     │
│  │   │   ├── capex = power×cost_kw + energy×cost_kwh           │
│  │   │   ├── annual_opex = capex × opex_pct                    │
│  │   │   └── npv = NPV(capex, savings-opex, rate, years)       │
│  │   │                                                          │
│  │   │   IF npv > best_npv:                                     │
│  │   │       best_config = (power, energy, dispatch)            │
│  │                                                              │
│  WYNIK:                                                         │
│  ├── optimal_power_kw                                           │
│  ├── optimal_energy_kwh                                         │
│  ├── npv_bess_pln                                               │
│  ├── payback_years                                              │
│  ├── annual_cycles                                              │
│  └── hourly_soc[8760]                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Zmienne decyzyjne

| Zmienna | Jednostka | Opis | Zakres typowy |
|---------|-----------|------|---------------|
| `power_kw` | kW | Moc nominalna BESS (ładowanie/rozładowanie) | 50 - 10 000 |
| `energy_kwh` | kWh | Pojemność nominalna BESS | 100 - 50 000 |
| `duration_h` | h | Stosunek E/P (czas pełnego rozładowania) | 1 - 4 |

#### Ograniczenia

```python
# Ograniczenia mocy i pojemności
min_power_kw <= power_kw <= max_power_kw
min_energy_kwh <= energy_kwh <= max_energy_kwh

# Ograniczenie duration (E/P ratio)
duration_min_h <= energy_kwh / power_kw <= duration_max_h

# Ograniczenia SOC w każdym kroku czasowym
soc_min × energy_kwh <= soc[t] <= soc_max × energy_kwh

# Ograniczenie mocy ładowania/rozładowania
charge[t] <= power_kw
discharge[t] <= power_kw
```

### 10.3 Algorytm Dispatch (Symulacja Sterowania)

**Lokalizacja:** `services/bess-dispatch/dispatch_engine.py`

#### 10.3.1 Algorytm PV-Surplus (Autokonsumpcja)

```
┌─────────────────────────────────────────────────────────────────┐
│              DISPATCH PV-SURPLUS (GREEDY)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  DLA KAŻDEGO KROKU CZASOWEGO t = 0..8759:                       │
│                                                                 │
│  ┌─ KROK 1: Bezpośrednia autokonsumpcja ─────────────────────┐ │
│  │  direct_pv[t] = min(pv[t], load[t])                       │ │
│  │  surplus = pv[t] - direct_pv[t]                           │ │
│  │  deficit = load[t] - direct_pv[t]                         │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ KROK 2: Obsługa nadwyżki PV (ładowanie) ─────────────────┐ │
│  │  IF surplus > 0:                                          │ │
│  │    charge_limit = min(surplus, P_max)                     │ │
│  │    space_available = SOC_max - SOC[t]                     │ │
│  │    charge_energy = min(charge_limit × η_ch × Δt, space)   │ │
│  │    charge[t] = charge_energy / (η_ch × Δt)                │ │
│  │    SOC[t+1] = SOC[t] + charge_energy                      │ │
│  │    curtailment[t] = surplus - charge[t]                   │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ KROK 3: Obsługa deficytu (rozładowanie) ─────────────────┐ │
│  │  IF deficit > 0:                                          │ │
│  │    discharge_limit = min(deficit, P_max)                  │ │
│  │    energy_available = SOC[t] - SOC_min                    │ │
│  │    max_from_soc = discharge_limit / η_dis × Δt            │ │
│  │                                                           │ │
│  │    IF max_from_soc > energy_available:                    │ │
│  │      actual_from_soc = energy_available                   │ │
│  │      discharge[t] = actual_from_soc × η_dis / Δt          │ │
│  │    ELSE:                                                  │ │
│  │      discharge[t] = discharge_limit                       │ │
│  │      actual_from_soc = max_from_soc                       │ │
│  │                                                           │ │
│  │    SOC[t+1] = SOC[t] - actual_from_soc                    │ │
│  │    grid_import[t] = deficit - discharge[t]                │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 10.3.2 Algorytm Peak Shaving

```
┌─────────────────────────────────────────────────────────────────┐
│                  DISPATCH PEAK SHAVING                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  PARAMETR: peak_limit_kw ← Próg mocy szczytowej                │
│                                                                 │
│  DLA KAŻDEGO KROKU CZASOWEGO t:                                 │
│                                                                 │
│    net_load[t] = load[t] - pv[t]                               │
│                                                                 │
│    ┌─ PRZYPADEK 1: Przekroczenie progu ────────────────────┐   │
│    │  IF net_load[t] > peak_limit_kw:                      │   │
│    │    required_discharge = net_load[t] - peak_limit_kw   │   │
│    │    discharge[t] = min(required, P_max, available_soc) │   │
│    │    grid_import[t] = net_load[t] - discharge[t]        │   │
│    │    new_peak = max(new_peak, grid_import[t])           │   │
│    └────────────────────────────────────────────────────────┘   │
│                                                                 │
│    ┌─ PRZYPADEK 2: Poniżej progu, ładowanie ───────────────┐   │
│    │  IF 0 < net_load[t] <= peak_limit_kw:                 │   │
│    │    headroom = peak_limit_kw - net_load[t]             │   │
│    │    IF headroom > 0 AND SOC < SOC_max:                 │   │
│    │      charge[t] = min(headroom, P_max, space)          │   │
│    │      grid_import[t] = net_load[t] + charge[t]         │   │
│    └────────────────────────────────────────────────────────┘   │
│                                                                 │
│    ┌─ PRZYPADEK 3: Nadwyżka PV ────────────────────────────┐   │
│    │  IF net_load[t] <= 0:                                 │   │
│    │    surplus = -net_load[t]                             │   │
│    │    curtailment[t] = surplus  (model 0-export)         │   │
│    └────────────────────────────────────────────────────────┘   │
│                                                                 │
│  WYNIKI:                                                        │
│  ├── original_peak_kw = max(net_load > 0)                      │
│  ├── new_peak_kw = max(grid_import)                            │
│  └── peak_reduction_pct = (original - new) / original × 100    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 10.3.3 Algorytm STACKED (Hybrydowy)

```
┌─────────────────────────────────────────────────────────────────┐
│              DISPATCH STACKED (PV + PEAK SHAVING)               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  PARAMETRY:                                                     │
│  ├── peak_limit_kw     ← Próg peak shaving                     │
│  └── reserve_fraction  ← Frakcja SOC rezerwowana dla peak      │
│                                                                 │
│  OBLICZENIE SOC REZERWY:                                        │
│  reserve_soc = energy_kwh × reserve_fraction                    │
│  pv_soc_min = max(soc_min × energy, reserve_soc)               │
│                                                                 │
│  DLA KAŻDEGO KROKU CZASOWEGO t:                                 │
│                                                                 │
│    ┌─ PRIORYTET 1: Peak Shaving ───────────────────────────┐   │
│    │  IF net_load[t] > peak_limit_kw:                      │   │
│    │    // Użyj PEŁNY SOC (włącznie z rezerwą)            │   │
│    │    energy_available = SOC[t] - soc_min × energy       │   │
│    │    discharge_peak[t] = min(required, P_max, avail)    │   │
│    │    SOC[t+1] = SOC[t] - discharge_peak[t] / η          │   │
│    └────────────────────────────────────────────────────────┘   │
│                                                                 │
│    ┌─ PRIORYTET 2: PV Shifting (nadwyżka) ─────────────────┐   │
│    │  ELIF surplus > 0:                                    │   │
│    │    // Ładuj do SOC_max                                │   │
│    │    charge_from_pv[t] = min(surplus, P_max, space)     │   │
│    │    SOC[t+1] = SOC[t] + charge × η                     │   │
│    │    curtailment[t] = surplus - charge                  │   │
│    └────────────────────────────────────────────────────────┘   │
│                                                                 │
│    ┌─ PRIORYTET 3: PV Shifting (deficyt) ──────────────────┐   │
│    │  ELIF deficit > 0:                                    │   │
│    │    // Użyj tylko SOC PONAD rezerwę                    │   │
│    │    energy_above_reserve = SOC[t] - pv_soc_min         │   │
│    │    IF energy_above_reserve > 0:                       │   │
│    │      discharge_pv[t] = min(deficit, available)        │   │
│    │    grid_import[t] = deficit - discharge_pv[t]         │   │
│    └────────────────────────────────────────────────────────┘   │
│                                                                 │
│  METRYKI DEGRADACJI:                                            │
│  ├── throughput_peak_mwh  ← Energia dla peak shaving           │
│  ├── throughput_pv_mwh    ← Energia dla PV shifting            │
│  ├── efc_peak             ← Cykle dla peak shaving             │
│  ├── efc_pv               ← Cykle dla PV shifting              │
│  ├── peak_events_count    ← Liczba zdarzeń peak shaving        │
│  └── charge_pv_pct        ← % ładowania z PV vs sieć           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 10.4 Wzory Matematyczne

#### 10.4.1 Bilans energetyczny

```
net_load(t) = load(t) - pv(t)

gdzie:
  net_load(t) > 0  →  deficyt (potrzeba energii z BESS/sieci)
  net_load(t) < 0  →  nadwyżka PV (można ładować BESS)
  net_load(t) = 0  →  bilans zerowy
```

#### 10.4.2 Sprawność ładowania/rozładowania

```
Sprawność roundtrip:     η_rt = η_charge × η_discharge

Typowo dla Li-ion:       η_rt = 0.90 (90%)
                         η_charge = √0.90 ≈ 0.9487 (94.87%)
                         η_discharge = √0.90 ≈ 0.9487 (94.87%)

Energia zmagazynowana:   E_stored = E_input × η_charge
Energia wydana:          E_output = E_stored × η_discharge
Straty roundtrip:        E_loss = E_input × (1 - η_rt)
```

#### 10.4.3 Stan naładowania (SOC)

```
Ładowanie:
  SOC(t+1) = SOC(t) + P_charge(t) × η_charge × Δt

Rozładowanie:
  SOC(t+1) = SOC(t) - P_discharge(t) / η_discharge × Δt

Ograniczenia:
  SOC_min × E_nom ≤ SOC(t) ≤ SOC_max × E_nom

Pojemność użytkowa:
  E_usable = E_nom × (SOC_max - SOC_min)
  E_usable = E_nom × (0.90 - 0.10) = 0.80 × E_nom
```

#### 10.4.4 Cykle ekwiwalentne (EFC)

```
EFC = Σ discharge(t) / E_usable

Przykład:
  E_nom = 200 kWh
  E_usable = 200 × 0.80 = 160 kWh
  Roczne rozładowanie = 40 000 kWh
  EFC = 40 000 / 160 = 250 cykli/rok
```

#### 10.4.5 NPV (Net Present Value)

```
NPV = Σ(t=1..n) [CF(t) / (1+r)^t] - CAPEX

gdzie:
  CF(t) = annual_savings - annual_opex

  POPRAWNY WZÓR (baseline vs project):
  annual_savings = baseline_cost - project_cost
  baseline_cost  = Σ max(0, load[t] - pv[t]) × Δt × price  (bez BESS)
  project_cost   = Σ grid_import[t] × Δt × price           (z BESS)

  UPROSZCZENIE (przybliżone, niedokładne):
  annual_savings ≈ annual_discharge × energy_price
  (ignoruje straty sprawności i interakcje PV/load)

  annual_opex = CAPEX × opex_pct
  r = discount_rate (np. 0.07 = 7%)
  n = analysis_period (np. 25 lat)

Alternatywnie z PV factor:
  PV_factor = (1 - (1+r)^(-n)) / r
  NPV = CF × PV_factor - CAPEX
```

#### 10.4.6 Payback Period

```
Simple Payback = CAPEX / annual_net_savings

gdzie:
  annual_net_savings = annual_savings × (1 - opex_pct)

Przykład:
  CAPEX = 330 000 PLN
  annual_savings = 50 000 PLN
  opex_pct = 1.5%
  annual_net_savings = 50 000 × 0.985 = 49 250 PLN
  Payback = 330 000 / 49 250 = 6.7 lat
```

### 10.5 Parametry Wejściowe i Ich Wpływ

| Parametr | Symbol | Wpływ na wynik |
|----------|--------|----------------|
| Moc BESS | P_max | ↑ moc → ↑ szybkość ładowania/rozładowania, ↑ koszt |
| Pojemność | E_nom | ↑ pojemność → ↑ magazynowanie energii, ↑ koszt |
| Duration (E/P) | D | ↑ duration → dłuższe rozładowanie, mniej cykli/dzień |
| SOC min/max | SOC_min, SOC_max | Węższy zakres → dłuższa żywotność, mniej energii użytkowej |
| Sprawność | η_rt | ↑ sprawność → mniej strat, wyższe oszczędności |
| CAPEX/kWh | c_e | ↑ koszt → dłuższy payback, niższe NPV |
| CAPEX/kW | c_p | ↑ koszt → dłuższy payback, niższe NPV |
| Cena energii | p_e | ↑ cena → wyższe oszczędności, lepsze NPV |
| Stopa dyskontowa | r | ↑ stopa → niższe NPV, krótszy optymalny horyzont |

### 10.6 Diagram Przepływu Danych

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         PRZEPŁYW DANYCH BESS                             │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  UŻYTKOWNIK                                                              │
│      │                                                                   │
│      ├─► Lokalizacja (lat/lon) ─────────────────────────────────────┐    │
│      │                                                              │    │
│      ├─► Profil zużycia (CSV) ──────────────────────────────────┐   │    │
│      │                                                          │   │    │
│      └─► Parametry BESS ────────────────────────────────────┐   │   │    │
│          (moc, pojemność, sprawność, ceny)                  │   │   │    │
│                                                             │   │   │    │
│                                                             ▼   ▼   ▼    │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────────┐  │
│  │   PVGIS     │    │   CSV/XLS   │    │      FRONTEND-BESS          │  │
│  │   API       │    │   Parser    │    │   (parametry użytkownika)   │  │
│  └──────┬──────┘    └──────┬──────┘    └──────────────┬──────────────┘  │
│         │                  │                          │                  │
│         ▼                  ▼                          ▼                  │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                     PV-CALCULATION SERVICE                        │   │
│  │  ┌────────────────────────────────────────────────────────────┐  │   │
│  │  │  Generowanie profilu produkcji PV (8760h)                  │  │   │
│  │  │  pv_generation[t] = pvlib.simulate(irradiance, temp, ...)  │  │   │
│  │  └────────────────────────────────────────────────────────────┘  │   │
│  └───────────────────────────────┬──────────────────────────────────┘   │
│                                  │                                       │
│                                  ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                     BESS-OPTIMIZER SERVICE                        │   │
│  │  ┌────────────────────────────────────────────────────────────┐  │   │
│  │  │  Grid Search: testuj kombinacje (power, energy)            │  │   │
│  │  │  Dla każdej: symuluj dispatch → oblicz NPV                 │  │   │
│  │  │  Wybierz konfigurację z najwyższym NPV                     │  │   │
│  │  └────────────────────────────────────────────────────────────┘  │   │
│  └───────────────────────────────┬──────────────────────────────────┘   │
│                                  │                                       │
│                                  ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                     BESS-DISPATCH SERVICE                         │   │
│  │  ┌────────────────────────────────────────────────────────────┐  │   │
│  │  │  Symulacja godzinowa (8760 kroków):                        │  │   │
│  │  │  - PV-Surplus: autokonsumpcja                              │  │   │
│  │  │  - Peak Shaving: redukcja szczytów                         │  │   │
│  │  │  - STACKED: kombinacja usług                               │  │   │
│  │  └────────────────────────────────────────────────────────────┘  │   │
│  └───────────────────────────────┬──────────────────────────────────┘   │
│                                  │                                       │
│                                  ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                        WYNIKI                                     │   │
│  │  ├── Optymalna moc: 100 kW                                       │   │
│  │  ├── Optymalna pojemność: 200 kWh                                │   │
│  │  ├── CAPEX: 330 000 PLN                                          │   │
│  │  ├── NPV (25 lat): 450 000 PLN                                   │   │
│  │  ├── Payback: 6.7 lat                                            │   │
│  │  ├── Roczne cykle: 250                                           │   │
│  │  ├── Autokonsumpcja: 85% → 95%                                   │   │
│  │  └── Profil SOC[8760], charge[8760], discharge[8760]             │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### 10.7 Audytowalność i Reprodukowalność

#### 10.7.1 Audit Metadata

Od wersji 1.2.0, każdy wynik dispatch zawiera metadane audytowe w polu `info.audit`:

```python
class AuditMetadata:
    engine_version: str       # np. "1.2.0"
    profile_unit: ProfileUnit # np. "kW_avg"
    interval_minutes: int     # np. 60
    resampling_method: str    # np. "none", "repeat", "linear"
    source_interval_minutes: Optional[int]  # jeśli resampling zastosowany
```

#### 10.7.2 Jednostki Profili (ProfileUnit)

Wszystkie profile wejściowe muszą być w `kW_avg` (średnia moc w interwale).

```python
class ProfileUnit(str, Enum):
    KW_AVG = "kW_avg"    # Standard - średnia moc [kW]
    KW_PEAK = "kW_peak"  # Moc szczytowa (wymaga konwersji)
    KWH = "kWh"          # Energia (wymaga konwersji: kW = kWh / dt_hours)
```

**Konwersja:**
```python
from models import convert_profile_to_kw_avg, ProfileUnit

# Przykład: dane w kWh na interwał 15-min
data_kwh = [25, 30, 28, ...]  # kWh per 15-min
data_kw_avg = convert_profile_to_kw_avg(data_kwh, ProfileUnit.KWH, 15)
# Wynik: [100, 120, 112, ...] kW_avg
```

#### 10.7.3 Resampling (Zmiana Rozdzielczości)

Funkcje do zmiany rozdzielczości czasowej z zachowaniem energii:

```python
from models import resample_hourly_to_15min, resample_15min_to_hourly

# 8760 hourly → 35040 quarter-hourly
data_15min = resample_hourly_to_15min(data_1h, method="repeat")

# Weryfikacja zachowania energii:
energy_1h = sum(data_1h) * 1.0        # kWh
energy_15min = sum(data_15min) * 0.25  # kWh
assert abs(energy_1h - energy_15min) < 0.001  # Energia zachowana
```

#### 10.7.4 Progi Ostrzeżeń Degradacji

```
Próg 80%:  INFO      - Wczesne ostrzeżenie informacyjne
Próg 90%:  WARNING   - Zbliżanie się do limitu budżetowego
Próg 100%: EXCEEDED  - Przekroczenie budżetu degradacji
```

---

## 11. Nowe Funkcjonalności (v3.7-3.14)

### 11.1 Analiza Wrażliwości (Tornado Chart)

#### 11.1.1 Przegląd

Moduł analizy wrażliwości pozwala na ocenę ryzyka inwestycyjnego poprzez badanie wpływu zmian poszczególnych parametrów na NPV. Wyniki prezentowane są w formie wykresu "tornado".

**Endpoint:** `POST /sensitivity`

**Parametry analizowane:**
| Parametr | Zakres domyślny | Wpływ |
|----------|-----------------|-------|
| Cena energii | ±20% | Bezpośredni na oszczędności |
| CAPEX/kWh | ±20% | Bezpośredni na CAPEX |
| CAPEX/kW | ±20% | Bezpośredni na CAPEX |
| Stopa dyskontowa | ±20% | Wpływ na PV factor |
| Sprawność roundtrip | ±20% | Wpływ na dispatch |
| OPEX %/rok | ±20% | Wpływ na roczne koszty |

#### 11.1.2 Algorytm

```
DLA KAŻDEGO PARAMETRU:
    1. Oblicz wartość bazową (base_value)
    2. Oblicz NPV dla wartości niskiej (base × 0.8)
    3. Oblicz NPV dla wartości wysokiej (base × 1.2)
    4. Oblicz swing = |NPV_high - NPV_low|

POSORTUJ PARAMETRY wg swing (malejąco)

WYKRES TORNADO:
- Oś Y: parametry (posortowane)
- Oś X: zmiana NPV względem bazowego
- Słupek czerwony: spadek NPV (wartość niska/wysoka parametru)
- Słupek zielony: wzrost NPV
```

#### 11.1.3 Interpretacja Wyników

- **Najbardziej wrażliwy parametr**: wymaga szczególnej uwagi przy planowaniu
- **Najmniej wrażliwy parametr**: stabilny wpływ, mniejsze ryzyko
- **Scenariusze breakeven**: pokazują przy jakich odchyleniach NPV staje się ujemne

### 11.2 Topologia LOAD_ONLY (Stand-alone BESS)

#### 11.2.1 Przegląd

Nowa topologia `LOAD_ONLY` umożliwia modelowanie systemów BESS bez instalacji PV. Przypadki użycia:

- Zakłady przemysłowe z opłatami mocowymi
- Arbitraż cenowy z taryf time-of-use
- Rezerwowe zasilanie z możliwością peak shaving

#### 11.2.2 Topologie Systemów

```python
class TopologyType(str, Enum):
    PV_LOAD = "pv_load"      # Standard: PV + Load + BESS
    LOAD_ONLY = "load_only"  # No PV: Load + BESS only
```

#### 11.2.3 Algorytm dispatch_load_only

```
┌─────────────────────────────────────────────────────────────────┐
│                    DISPATCH LOAD_ONLY                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  PARAMETR: peak_limit_kw ← Próg mocy szczytowej                │
│                                                                 │
│  DLA KAŻDEGO KROKU CZASOWEGO t:                                 │
│                                                                 │
│    IF load[t] > peak_limit_kw:                                 │
│      // Rozładuj do redukcji szczytu                           │
│      discharge[t] = min(load[t] - peak_limit, P_max, SOC_avail)│
│      grid_import[t] = load[t] - discharge[t]                   │
│                                                                 │
│    ELSE:                                                       │
│      // Ładuj z sieci (headroom charging)                      │
│      headroom = peak_limit_kw - load[t]                        │
│      charge[t] = min(headroom, P_max, SOC_space)               │
│      grid_import[t] = load[t] + charge[t]                      │
│                                                                 │
│  EKONOMIKA:                                                     │
│  baseline_cost = total_load × price      (bez BESS)            │
│  project_cost = grid_import × price      (z BESS - mniej!)     │
│  savings = baseline_cost - project_cost                         │
│                                                                 │
│  METRYKI:                                                       │
│  - charge_from_grid = 100%  (brak PV)                          │
│  - peak_reduction_pct                                           │
│  - EFC (wszystko przypisane do peak shaving)                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 11.2.4 Użycie API

```json
POST /dispatch
{
  "topology": "load_only",
  "mode": "load_only",
  "load_kw": [100, 150, 200, ...],
  "pv_generation_kw": [],
  "peak_limit_kw": 180,
  "battery_power_kw": 50,
  "battery_energy_kwh": 100,
  ...
}
```

### 11.3 Multi-Objective Optimization (Cele i Ograniczenia)

#### 11.3.1 Przegląd

System pozwala na wybór różnych celów optymalizacji i definiowanie ograniczeń (twardych lub miękkich).

#### 11.3.2 Dostępne Cele Optymalizacji

```python
class OptimizationObjective(str, Enum):
    NPV = "npv"                        # Maksymalizuj NPV (domyślne)
    PAYBACK = "payback"                # Minimalizuj payback
    SELF_CONSUMPTION = "self_consumption"  # Maksymalizuj autokonsumpcję
    PEAK_REDUCTION = "peak_reduction"  # Maksymalizuj redukcję szczytów
    EFC_UTILIZATION = "efc_utilization"   # Maksymalizuj wykorzystanie cykli
```

#### 11.3.3 Dostępne Ograniczenia

```python
class ConstraintType(str, Enum):
    MAX_CAPEX = "max_capex"                  # Limit budżetu [PLN]
    MAX_PAYBACK = "max_payback"              # Max payback [lata]
    MIN_NPV = "min_npv"                      # Min NPV [PLN]
    MAX_EFC = "max_efc"                      # Max cykli/rok
    MIN_SELF_CONSUMPTION = "min_self_consumption"  # Min autokonsumpcja [%]
```

#### 11.3.4 Ograniczenia Twarde vs Miękkie

| Typ | Zachowanie | Przykład |
|-----|------------|----------|
| **Hard** | Odrzuca konfiguracje naruszające | "Budżet max 500k PLN" |
| **Soft** | Penalizuje w funkcji celu | "Preferuj payback < 7 lat" |

#### 11.3.5 Przykład Konfiguracji

```json
POST /sizing
{
  "optimization": {
    "objective": "npv",
    "constraints": [
      {
        "constraint_type": "max_capex",
        "value": 500000,
        "hard": true
      },
      {
        "constraint_type": "max_payback",
        "value": 7.0,
        "hard": false
      },
      {
        "constraint_type": "min_self_consumption",
        "value": 80.0,
        "hard": false
      }
    ],
    "constraint_penalty_weight": 0.3
  },
  ...
}
```

#### 11.3.6 Algorytm Ewaluacji

```python
def evaluate_configuration(config, request):
    # 1. Symuluj dispatch
    result = run_dispatch(config)

    # 2. Oblicz metryki ekonomiczne
    capex, npv, payback = calculate_economics(result)

    # 3. Sprawdź ograniczenia twarde
    for constraint in hard_constraints:
        if violated(constraint):
            return REJECT  # Pomiń konfigurację

    # 4. Oblicz score dla celu
    score = calculate_objective_score(objective, result, npv, payback)

    # 5. Penalizuj za naruszenie ograniczeń miękkich
    for constraint in soft_constraints:
        if violated(constraint):
            penalty = violation_amount / constraint.value
            score -= score * penalty * penalty_weight

    return score
```

### 11.4 Podsumowanie Nowych Endpointów

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/sensitivity` | POST | Analiza wrażliwości (tornado chart) |
| `/dispatch` | POST | Dispatch z nową topologią LOAD_ONLY |
| `/sizing` | POST | Sizing z multi-objective optimization |

### 11.5 Interfejs Użytkownika (Frontend BESS v3.12)

#### 11.5.1 Nowa Sekcja: Konfiguracja Zaawansowana

W wersji 3.12 dodano sekcję "Konfiguracja Zaawansowana BESS" umożliwiającą:

1. **Wybór Topologii Systemu**
   - `PV + BESS + Load` - standardowa konfiguracja z instalacją PV
   - `BESS + Load (bez PV)` - magazyn energii bez PV (peak shaving/arbitraż)
   - `Tylko PV (bez BESS)` - scenariusz bazowy tylko z instalacją PV

2. **Wybór Celu Optymalizacji**
   - Maksymalizuj NPV (domyślne)
   - Minimalizuj Payback
   - Maksymalizuj Autokonsumpcję
   - Maksymalizuj Redukcję Szczytów
   - Optymalizuj Wykorzystanie Cykli

3. **Edytor Ograniczeń (Constraints)**
   - Max CAPEX [PLN] - limit budżetu inwestycyjnego
   - Max Payback [lat] - maksymalny okres zwrotu
   - Min NPV [PLN] - minimalna wartość NPV
   - Max EFC/rok [cykli] - limit cykli rocznych
   - Min Autokonsumpcja [%] - wymagana autokonsumpcja

Każde ograniczenie może być:
- **Twarde** - konfiguracja naruszająca jest odrzucana
- **Miękkie** - konfiguracja naruszająca jest penalizowana w rankingu

#### 11.5.2 Analiza Wrażliwości w UI

Sekcja Tornado Chart jest teraz zawsze widoczna dla wariantów z BESS. Funkcjonalności:

- **Podsumowanie bazowe**: NPV, Payback, CAPEX
- **Wykres Tornado**: wizualizacja wpływu parametrów na NPV
- **Tabela szczegółowa**: wartości dla każdego parametru
- **Ostrzeżenia breakeven**: scenariusze gdzie NPV staje się ujemne

#### 11.5.3 Przepływ Użytkownika

```
┌─────────────────────────────────────────────────────────────────┐
│                    PRZEPŁYW UŻYTKOWNIKA                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Wybierz wariant instalacji (A/B/C/D)                       │
│                     ↓                                           │
│  2. [Opcjonalne] Skonfiguruj zaawansowane ustawienia:          │
│     ├── Wybierz topologię                                      │
│     ├── Wybierz cel optymalizacji                              │
│     └── Zdefiniuj ograniczenia                                 │
│                     ↓                                           │
│  3. Kliknij "Zastosuj konfigurację i przelicz"                │
│                     ↓                                           │
│  4. Przejrzyj wyniki:                                          │
│     ├── Metryki energetyczne                                   │
│     ├── Ekonomia BESS (NPV, Payback, ROI)                      │
│     ├── Warianty doboru (S/M/L)                                │
│     └── Analiza wrażliwości (tornado)                          │
│                     ↓                                           │
│  5. [Opcjonalne] Uruchom szczegółową analizę wrażliwości       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 11.5.4 Tryb Spójnych Obliczeń

System zapewnia spójność obliczeń dla wszystkich topologii:

| Scenariusz | Opis | Tryb Dispatch |
|------------|------|---------------|
| **PV solo** | Tylko instalacja PV | Brak BESS |
| **PV + BESS** | Standardowa konfiguracja | PV_SURPLUS lub STACKED |
| **BESS alone** | Magazyn bez PV | LOAD_ONLY |

Wszystkie scenariusze używają tego samego profilu obciążenia (load_kw) i parametrów ekonomicznych dla porównywalności wyników.

### 11.6 Panel Wyników Optymalizacji (v3.13)

W wersji 3.13 dodano panel "Wyniki Optymalizacji" wyświetlany bezpośrednio pod przyciskiem "Zastosuj konfigurację", eliminując konieczność przewijania strony.

#### 11.6.1 Metryki w Panelu

| Metryka | Opis |
|---------|------|
| **Rekomendowany wariant** | S/M/L z najwyższym score |
| **Moc / Pojemność** | np. "150 kW / 300 kWh" |
| **NPV** | Wartość bieżąca netto z kolorystycznym wskaźnikiem |
| **Payback** | Prosty okres zwrotu w latach |
| **CAPEX** | Całkowity koszt inwestycji |
| **EFC/rok** | Cykle ekwiwalentne na rok |

#### 11.6.2 Sekcja Naruszeń Ograniczeń

Jeśli którekolwiek z zdefiniowanych ograniczeń (constraints) zostanie naruszone, wyświetlana jest sekcja "Naruszenia Ograniczeń" z listą:

```
⚠️ Naruszenia Ograniczeń
──────────────────────────
🚫 Medium (2h): EFC 301 cykli > max 200 cykli
⚠️ Small (1h): Payback 8.5y > max 7.0y
```

**Ikony:**
- 🚫 - ograniczenie twarde (hard) - konfiguracja silnie penalizowana
- ⚠️ - ograniczenie miękkie (soft) - konfiguracja lekko penalizowana

### 11.7 Wyświetlanie Ostrzeżeń Constraints (v3.14)

#### 11.7.1 Zmiany w Zachowaniu Hard Constraints

W wersji 3.14 zmieniono logikę obsługi twardych ograniczeń:

**Poprzednie zachowanie (v3.12):**
- Konfiguracje naruszające hard constraints były pomijane
- Użytkownik nie widział ostrzeżeń o naruszeniach
- Wyniki pokazywały tylko "bezpieczne" konfiguracje

**Nowe zachowanie (v3.14):**
- Wszystkie konfiguracje są pokazywane
- Hard constraints nakładają **surową karę** na score (10x)
- Ostrzeżenia o naruszeniach są **zawsze widoczne** w panelu wyników
- Użytkownik widzi pełny obraz sytuacji i może świadomie zdecydować

#### 11.7.2 Format Ostrzeżeń z API

Backend zwraca ostrzeżenia w formacie:

```json
{
  "warnings": [
    "Small (1h): [TWARDE] CAPEX 850000 PLN > max 500000 PLN",
    "Medium (2h): [TWARDE] EFC 301 cykli > max 200 cykli",
    "Large (4h): [MIĘKKIE] Payback 9.2y > max 7.0y"
  ]
}
```

#### 11.7.3 Obsługiwane Typy Ostrzeżeń

| Ograniczenie | Komunikat naruszenia |
|--------------|---------------------|
| MAX_CAPEX | `CAPEX {actual} PLN > max {limit} PLN` |
| MAX_PAYBACK | `Payback {actual}y > max {limit}y` |
| MIN_NPV | `NPV {actual} PLN < min {limit} PLN` |
| MAX_EFC | `EFC {actual} cykli > max {limit} cykli` |
| MIN_SELF_CONSUMPTION | `Autokonsumpcja {actual}% < min {limit}%` |

#### 11.7.4 Algorytm Penalizacji

```python
def evaluate_with_constraints(config, constraints):
    score = calculate_base_score(config)

    for constraint in constraints:
        if violated(constraint):
            if constraint.hard:
                # Surowa kara - de facto eliminacja
                score -= abs(score) * 10.0
            else:
                # Proporcjonalna kara
                violation_ratio = violation_amount / constraint.value
                score -= abs(score) * violation_ratio * penalty_weight

    return score
```

### 11.8 Auto-Scroll do Wyników

Po kliknięciu "Zastosuj konfigurację" strona automatycznie przewija się do panelu wyników, zapewniając natychmiastowy feedback dla użytkownika.

```javascript
// Automatyczne przewinięcie do wyników
const summaryPanel = document.getElementById('configResultsSummary');
if (summaryPanel) {
  summaryPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
```

### 11.9 Wersjonowanie

| Komponent | Wersja |
|-----------|--------|
| Dokumentacja | 3.9 |
| Engine | 1.2.0 |
| Service | 1.1.0 |
| Frontend BESS | 3.14 |

---

