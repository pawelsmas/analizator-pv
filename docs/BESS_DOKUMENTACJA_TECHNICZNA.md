# Dokumentacja Techniczna Modułu BESS
## Battery Energy Storage System - Magazyn Energii

**Wersja:** 3.2
**Data:** 2025-12-21
**Autor:** Analizator PV

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
    annual_discharge = simulate_quick_dispatch(power, energy)
    annual_savings = annual_discharge * energy_price
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
annuity_factor = (r × (1+r)^n) / ((1+r)^n - 1)

gdzie:
  r = stopa dyskontowa (np. 7%)
  n = okres analizy (np. 15 lat)

annual_savings = annual_discharge × energy_price
annual_cost = CAPEX × annuity_factor
NPV = (annual_savings - annual_cost) / annuity_factor
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
NPV = Σ(t=1 to n) [(savings_t - opex_t) / (1+r)^t] - CAPEX

gdzie:
  savings_t = annual_discharge × energy_price × degradation_factor(t)
  r = stopa dyskontowa
  n = okres analizy
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

Dla Power = 75 kW, Energy = 150 kWh:
  - Roczne rozładowanie: ~180 MWh
  - Roczne oszczędności: 180 × 0.8 = 144 000 PLN
  - CAPEX: 150 × 1500 + 75 × 300 = 247 500 PLN
  - Annuity factor (7%, 15 lat): 0.1098
  - Roczny koszt: 247 500 × 0.1098 = 27 175 PLN
  - NPV: (144 000 - 27 175) / 0.1098 = 1 064 000 PLN

Optymalny dobór: 75 kW / 150 kWh
```

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

*Dokument wygenerowany automatycznie przez Analizator PV*
