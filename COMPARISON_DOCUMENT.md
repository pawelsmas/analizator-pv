# Porównanie dwóch rozwiązań optymalizacji BESS
## Dokument referencyjny dla agenta rozstrzygającego

---

## SPIS TREŚCI
1. [Kontekst i cel dokumentu](#1-kontekst)
2. [ROZWIĄZANIE A: ANALIZATOR PV (Energy Studio Portal)](#2-rozwiazanie-a)
3. [ROZWIĄZANIE B: kalkulatorMEE (pagra-galileo / QuickerSim)](#3-rozwiazanie-b)
4. [Porównanie algorytmów optymalizacji LP](#4-porownanie-lp)
5. [Porównanie modeli cenowych i taryfowych](#5-porownanie-cen)
6. [Porównanie modeli baterii i degradacji](#6-porownanie-baterii)
7. [Porównanie analizy finansowej](#7-porownanie-finanse)
8. [Porównanie obsługi opłaty mocowej](#8-porownanie-oplata-mocowa)
9. [Porównanie architektury i UX](#9-porownanie-architektura)
10. [Podsumowanie mocnych i słabych stron](#10-podsumowanie)

---

## 1. KONTEKST I CEL DOKUMENTU {#1-kontekst}

### Co porównujemy
Dwa niezależne narzędzia do optymalizacji magazynów energii (BESS) na polskim rynku energii:

- **Rozwiązanie A** — „ANALIZATOR PV" (Energy Studio Portal): Webowy portal Docker z 37 mikroserwisami. Rozwijany wewnętrznie. Dostępny pod http://localhost.
- **Rozwiązanie B** — „kalkulatorMEE" (pagra-galileo): Desktopowa aplikacja PyInstaller (Python 3.11). Produkt firmy QuickerSim. Oparta na bibliotece `ozetoolbox`.

### Wspólny cel obu narzędzi
Dla danego profilu zużycia energii (load) i produkcji PV:
1. Zoptymalizować dispatch BESS (kiedy ładować, kiedy rozładowywać)
2. Obliczyć oszczędności (energia, opłata mocowa, peak shaving, arbitraż)
3. Dobrać optymalny rozmiar BESS (moc kW + pojemność kWh)
4. Wykonać analizę finansową (NPV, IRR, payback)

### Kontekst rynkowy — Polska
Oba narzędzia operują w kontekście polskiego rynku energii:
- 5 OSD (Operatorów Systemu Dystrybucyjnego): PGE, Tauron, Energa, Enea, Eon
- Taryfy wielostrefowe: C11, C12a, C12b, C22, C23, B11, B21, B22, B23
- Opłata mocowa (capacity fee): Ustawa o rynku mocy, klasy K1-K4
- Rynek Dnia Następnego (RDN): Ceny godzinowe z TGE/CSDAC
- Usługi bilansujące: aFRR, mFRR, FCR, DSR

---

## 2. ROZWIĄZANIE A: ANALIZATOR PV (Energy Studio Portal) {#2-rozwiazanie-a}

### 2.1 Architektura ogólna

**Typ:** Webowy portal oparty na Docker Compose (37 kontenerów)
**Język backend:** Python (FastAPI, port 8031 dla bess-dispatch)
**Język frontend:** Vanilla JavaScript (mikrofrontendy ładowane przez shell)
**Baza danych:** Prometheus (metryki), pliki JSON (konfiguracja)
**Routing:** Nginx reverse proxy (frontend-shell)

**Mikroserwisy:**
- `pv-data-analysis` (:8001) — analiza danych PV
- `pv-calculation` (:8002) — kalkulacje PV
- `pv-economics` (:8003) — ekonomika PV
- `bess-dispatch` (:8031) — **główny serwis optymalizacji BESS**
- `frontend-shell` (:80) — powłoka UI, routing nginx
- `frontend-bess` — UI konfiguracji i wyników BESS
- `frontend-economics` — UI analizy finansowej
- `frontend-consumption` — UI analizy zużycia + opłata mocowa
- `frontend-config` — UI konfiguracji systemu
- + ~28 innych serwisów pomocniczych (monitoring, storage, etc.)

### 2.2 Serwis bess-dispatch — Struktura modułów

```
services/bess-dispatch/
├── app.py                    # FastAPI, endpointy REST
├── models.py                 # Pydantic DTOs (BatteryParams, DispatchResult, SizingResult...)
├── dispatch_engine.py        # Algorytmy greedy (PV_SURPLUS, PEAK_SHAVING, STACKED)
├── lp_dispatch.py            # Solver LP (scipy.linprog + HiGHS backend)
├── sizing_runner.py          # Sizing: grid search + NPV/IRR + cashflow
├── economics_helper.py       # Unified cost calculation (ToU + capacity fee)
├── price_engine.py           # PriceBundle: import_total[t] + export_total[t]
├── money_ledger_helper.py    # MoneyLedger SSoT (baseline vs project)
├── energy_flows_helper.py    # EnergyFlows SSoT
├── price_timeseries_helper.py # Generacja serii cenowych
├── ledger_timeseries_helper.py # Ledger timeseries
├── determinism_helper.py     # Deterministyczny wybór wariantu
├── advisor_response.py       # Rekomendacje tekstowe
├── capacity_fee_pl/
│   ├── calculator.py         # compute_capacity_fee(), K-class classification
│   ├── models.py             # KClass, CapacityFeeConfig, CapacityFeeResult
│   └── calendar_pl.py        # is_workday(), PolishHolidayCalendar
├── osd_tariffs/
│   ├── models.py             # OsdTariff, ZoneId, Segment, ScheduleBlock
│   ├── compiler.py           # TariffCompiler — taryfa → seria cenowa
│   ├── presets/
│   │   ├── templates.py      # C11, C12a, C12b, C22, G12 factory functions
│   │   └── __init__.py       # Registry: 7 presetów (PGE/Tauron/Energa × 2025/2026)
│   └── validators.py         # Walidacja pokrycia 1440 minut
├── common/
│   ├── time_utils.py         # CET_FIXED, ClockMode
│   ├── calendar_pl.py        # DayType, święta polskie
│   └── versioning.py         # Wersjonowanie
├── observability/
│   ├── http_metrics.py       # Prometheus metryki HTTP
│   ├── finance_metrics.py    # Metryki NPV/IRR/cashflow
│   ├── constraint_metrics.py # Metryki grid constraints
│   └── ...                   # ~10 modułów metryk
└── middleware/
    └── request_size_limit.py # Limity requestów
```

### 2.3 Endpointy API (app.py)

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/dispatch` | POST | Pojedyncza symulacja dispatch |
| `/sizing` | POST | Sizing z wariantami S/M/L |
| `/sizing/quick` | POST | Szybki sizing (PV-surplus) |
| `/health` | GET | Health check |
| `/info` | GET | Informacje o serwisie |
| `/osd-tariffs/presets` | GET | Lista dostępnych taryf |
| `/batch` | POST | Batch sizing (wiele lokalizacji) |
| `/runs/*` | CRUD | Zarządzanie zapisanymi uruchomieniami |
| `/jobs/*` | CRUD | Asynchroniczne joby z SSE streaming |
| `/metrics` | GET | Prometheus metrics |

### 2.4 Algorytm LP (lp_dispatch.py) — SZCZEGÓŁOWO

#### Zmienne decyzyjne
- `SoC[0..n-1]` — znormalizowany stan naładowania (0-1)
- `t_aux[0..n-1]` — zmienne pomocnicze kosztu

Łącznie `2n` zmiennych, gdzie `n` = liczba kroków czasowych w oknie.

#### Funkcja celu
```
minimize: sum(t_aux[t] * capacity_kWh)  for t = 0..n-1
```
Minimalizacja sumarycznego kosztu energii. `t_aux[t]` reprezentuje koszt netto w kroku `t`, przeskalowany przez pojemność baterii.

**WAŻNE:** Funkcja celu zawiera TYLKO koszt energii (buy/sell price). NIE zawiera:
- Kary za nierównomierność profilu (brak flatness penalty)
- Opłaty mocowej (capacity fee)
- Demand charge (peak power fee)
- Kosztu degradacji baterii

#### Ograniczenia — Power (2n nierówności)
```
A_diff @ SoC <= ub_power     # dSoC/dt <= max charge rate (C-rate)
-A_diff @ SoC <= -lb_power   # dSoC/dt >= max discharge rate (-C-rate)
```
Gdzie `A_diff` to macierz różnicowa: `dSoC[t] = (SoC[t] - SoC[t-1]) / dt`

Dla PEAK_SHAVING: upper bound jest zaostrzany, by wymóc `grid_import <= peak_limit_kw`:
```python
headroom = peak_limit_kw - load_kw + pv_kw
peak_ub = where(headroom >= 0,
                headroom * eta_ch / cap,      # pod limitem: ogranicz ładowanie
                headroom / (cap * eta_dis))    # nad limitem: wymuś rozładowanie
```

#### Ograniczenia — Cost (4n nierówności, piecewise-linear)
4 kawałki modelują kombinacje:
- Ładowanie vs rozładowanie (efektywność η)
- Cena kupna vs sprzedaży

```
Piece 0: t_aux >= dSoC * η_ch  * sell_price - balance * dt * sell_price
Piece 1: t_aux >= dSoC / η_dis * sell_price - balance * dt * sell_price
Piece 2: t_aux >= dSoC * η_ch  * buy_price  - balance * dt * buy_price
Piece 3: t_aux >= dSoC / η_dis * buy_price  - balance * dt * buy_price
```
Gdzie `balance = (pv - load) / capacity` — znormalizowany bilans energetyczny.

#### Bounds na SoC
```
soc_min (default 0.10) <= SoC[t] <= soc_max (default 0.90)
```

#### Rolling Horizon
```python
forecast_hours = 34    # okno "patrzenia w przód"
keep_hours = 24        # ile godzin zachowujemy z rozwiązania
```
Algorytm przesuwa okno co `keep_hours` kroków, używając końcowego SoC jako początkowego dla następnego okna.

#### Progressive Relaxation (4 poziomy)
Gdy LP jest niewykonalny:
1. **Level 0:** Oryginalne ograniczenia
2. **Level 1:** Peak limit × 1.5
3. **Level 2:** Bez peak limit
4. **Level 3:** Bez peak limit + pełny SoC range (0-1)

Jeśli wszystkie 4 poziomy zawiodą → battery idle (hold SoC).

#### Solver backend
```python
scipy.optimize.linprog(method='highs', options={'time_limit': 30.0})
```
HiGHS — solver open-source, state-of-the-art dla LP.

#### Post-processing (SoC → Power Arrays)
```python
charging_mask = dsoc > 0
charge_kw[charging] = dsoc * cap / (eta_ch * dt)    # moc ładowania
discharge_kw[discharging] = -dsoc * cap * eta_dis / dt  # moc rozładowania
grid_power = load - pv + charge - discharge
grid_import = max(grid_power, 0)
grid_export = max(-grid_power, 0)
```

### 2.5 Algorytmy Greedy (dispatch_engine.py)

#### PV_SURPLUS (Autokonsumpcja)
Greedy per-timestep:
1. Direct PV → load (min(pv, load))
2. Surplus PV → charge battery (limited by C-rate, SoC_max)
3. Load deficit → discharge battery (limited by C-rate, SoC_min)
4. Remaining surplus → curtailment
5. Remaining deficit → grid import

**Nie ma eksportu** — model 0-export.

#### PEAK_SHAVING
Priority discharge na szczycie zużycia:
- Identyfikuje godziny z `grid_import > peak_limit`
- Rozładowuje baterię by utrzymać `grid_import <= peak_limit`
- Ładuje w godzinach niskiego zużycia

#### STACKED (PV + Peak)
Dual-service z rezerwą SoC:
- Peak shaving ma priorytet 1 (pełny zakres SoC)
- PV surplus ma priorytet 2
- Arbitraż (opcjonalnie) ma priorytet 3
- `reserve_fraction` (default 0.3) — rezerwa SoC na peak shaving

### 2.6 Model baterii (models.py: BatteryParams)

```python
class BatteryParams:
    power_kw: float           # Moc nominalna [kW]
    energy_kwh: float         # Pojemność nominalna [kWh]
    eta_charge: float = 0.9487    # Efektywność ładowania (one-way)
    eta_discharge: float = 0.9487 # Efektywność rozładowania (one-way)
    soc_min: float = 0.10    # Min SoC [0-1]
    soc_max: float = 0.90    # Max SoC [0-1]
    soc_initial: float = 0.50 # Początkowy SoC

    # Właściwości obliczane:
    usable_dod = soc_max - soc_min  # = 0.80
    roundtrip_efficiency = eta_ch * eta_dis  # = 0.90
    c_rate = power_kw / energy_kwh
```

**Degradacja** — uproszczona, liniowa %/rok:
```python
bess_degradation_pct_per_year: float = 2.0  # np. 2%/rok
pv_degradation_pct_per_year: float = 0.5    # np. 0.5%/rok

# W cashflow (sizing_runner.py):
bess_factor = (1 - bess_rate)^year
pv_factor = (1 - pv_rate)^year
degraded_savings = base_savings * bess_factor * pv_factor
```

NIE MA modelu degradacji opartego na cyklach (EFC-based SoH).

### 2.7 Opłata mocowa (capacity_fee_pl/)

#### Algorytm (calculator.py)
1. **Build selected hours mask**: Per-timestep boolean — `True` jeśli godzina jest w "godzinach wybranych" (default 7:00-22:00) na dzień roboczy
2. **Per-day K-class classification**: Na każdy dzień roboczy:
   - `ZS = sum(grid_import[selected_hours])` — energia w godz. wybranych
   - `ZPS = sum(grid_import[outside_hours])` — energia poza godz. wybranymi
   - `avg_s = ZS / n_selected`
   - `avg_ps = ZPS / n_outside`
   - `Δs = (avg_s / avg_ps - 1) × 100%`
   - Klasyfikacja K:
     - K1: Δs < -10% → A = 0.17
     - K2: Δs ∈ [-10%, 10%) → A = 0.50
     - K3: Δs ∈ [10%, 30%) → A = 0.83
     - K4: Δs ≥ 30% lub ZPS=0 → A = 1.00
3. **Fee per day**: `WOM_day = A × SOM × ZS`
   - SOM = 0.2194 PLN/kWh (2026, URE 58/2025)
4. **Aggregation**: Suma per miesiąc → suma roczna

#### Konfiguracja (models.py)
```python
class CapacityFeeConfig:
    year: int = 2026
    som_pln_per_kwh: float = 0.2194
    qualification_period: QualificationPeriod = DAILY  # od 2025+
    selected_windows_by_quarter: Dict = {
        "Q1": (7, 22), "Q2": (7, 22), "Q3": (7, 22), "Q4": (7, 22)
    }
```

#### KRYTYCZNY SZCZEGÓŁ: Opłata mocowa jest obliczana POST-FACTUM
Solver LP NIE WIE o opłacie mocowej. Dispatch jest optymalizowany wyłącznie pod kątem kosztu energii (buy/sell price). Dopiero po dispatchu, na gotowym profilu `grid_import`, obliczana jest opłata mocowa i porównywana ze scenariuszem bazowym (bez BESS).

To oznacza, że **solver nie aktywnie dąży do spłaszczenia profilu** — oszczędności z opłaty mocowej są "przypadkowe" (efekt uboczny optymalizacji kosztu energii).

### 2.8 Model cenowy (price_engine.py, economics_helper.py)

#### Struktura ceny
```
import_total[t] = OSD_variable[t] + energy[t] + OTHER + capacity_fee
```

Komponenty:
- **OSD_VARIABLE**: Składnik zmienny OSD — zone-based (PLN/kWh)
- **ENERGY**: Energia czynna — zone-based lub flat
- **OTHER**: OZE + kogeneracja + jakość + akcyza = ~451 PLN/MWh (flat)
- **CAPACITY_FEE**: Obliczana osobno, post-dispatch

#### Dostępne taryfy (osd_tariffs/presets/)
```python
ALL_PRESETS = {
    "pge_c12a_2025": PGE C12a 2025 (0.85/0.55 PLN/kWh peak/offpeak),
    "tauron_c12a_2025": Tauron C12a 2025 (0.82/0.52),
    "energa_g12_2025": Energa G12 2025 (0.78/0.48),
    "pge_c12a_2026": PGE C12a 2026 (0.75/0.45),
    "pge_c12b_2026": PGE C12b 2026 (0.85/0.40 - 3 strefy),
    "tauron_c12a_2026": Tauron C12a 2026 (0.72/0.42),
    "energa_c12a_2026": Energa C12a 2026 (0.70/0.40),
}
```
**7 presetów** (3 OSD × C12a/C12b/G12 × 2025-2026)

Brak: B11, B21, B22, B23, C11, C21, C22a, C22b, C23, Enea, Eon.

#### PriceBundle
```python
class PriceBundle:
    import_total: List[float]   # PLN/kWh per timestep
    export_total: List[float]   # PLN/kWh per timestep
    breakdown: List[PriceBreakdown]  # Komponent-level per timestep
```

**Brak integracji z cenami RDN** (Rynek Dnia Następnego). Price engine ma placeholder `RDN = "rdn"` w enum PriceComponent, ale nie ma implementacji `RDNPriceProvider`.

### 2.9 Analiza finansowa (sizing_runner.py)

#### NPV
```python
NPV = -CAPEX + sum(t=1..N) [(savings - opex) / (1+r)^t]
# opex = capex * opex_pct (domyślnie ~2%)
```

#### IRR
Newton-Raphson + bisection fallback. Szuka stopy `r` takiej że NPV=0.

#### Cashflow timeseries
Per-year cashflow z uwzględnieniem:
- Degradacji baterii (% per year, liniowo)
- Degradacji PV (% per year)
- Replacement baterii (w zadanym roku)
- OPEX jako % CAPEX

#### Sensitivity analysis
3 wymiary wrażliwości:
1. **Discount rate sensitivity**: NPV przy różnych stopach dyskonta
2. **Energy price sensitivity**: NPV przy różnych mnożnikach ceny energii
3. **CAPEX sensitivity**: NPV przy różnych mnożnikach CAPEX

#### Sizing grid search
- Testuje warianty S/M/L (różne duration: 1h, 2h, 4h)
- Per duration: grid search po power levels
- Wybiera wariant z najlepszym NPV
- Stacked decomposition (peak shaving + arbitrage components)

### 2.10 Obserwability i monitoring
- Prometheus metryki dla wszystkich operacji
- Debug events helper
- Battery trace timeseries
- Repro bundles (odtwarzalność wyników)
- Structured logging

---

## 3. ROZWIĄZANIE B: kalkulatorMEE (pagra-galileo / QuickerSim) {#3-rozwiazanie-b}

### 3.1 Architektura ogólna

**Typ:** Desktopowa aplikacja Windows (PyInstaller, Python 3.11)
**Biblioteka:** `ozetoolbox` — wewnętrzna biblioteka solverów
**GUI:** tkinter (prosty interfejs do uruchomienia obliczeń)
**I/O:** Excel (xlsx) — input i output
**Paralelizm:** multiprocessing.Pool (16 rdzeni)

**Uwaga:** Kod źródłowy nie jest dostępny. Analiza oparta na dekompilacji bytecode'u Pythona 3.11 (marshal + struct extraction z plików .pyc). Nazwy funkcji, zmiennych, klas i stałych są wiarygodne; dokładna logika jest rekonstrukcją.

### 3.2 Struktura modułów

```
pagra_galileo/
  gui/
    main_window.py        # tkinter GUI (uruchamia obliczenia)
    download_window.py    # Pobieranie danych PSE (CSDAC/CMBP), Open-Meteo weather
  runner.py               # Orkiestrator: readExcel → defineCases → runCalculation

core/
  io.py                   # readInputExcel, writeResultExcel, cartesianProduct
  runner.py               # prepareUserObject, runSingleCase, parallelFunc, aggregateResults
  postprocess.py          # balancingPotential

ozetoolbox/
  solver/
    _basics.py            # User, EnergyBank, BatteryAging, PowerMarket, DSR
    solver.py             # optimizeBankOverPeriod (rolling horizon)
    linear.py             # LP solver (scipy.linprog) ← GŁÓWNY SOLVER
    hourly.py             # NLP solver (trust-constr / COBYQA) ← alternatywny
    arithmetic.py         # Heurystyki (zero_export, arbitrage, peak_shaving, etc.)
    _constraints.py       # Macierze ograniczeń LP
    _metrics.py           # Funkcje kosztu i gradienty (dla NLP)
    JG.py                 # JG_M2 (Jednostka Grafikowa Modelu 2 — usługi bilansujące)
  preprocessing/
    price.py              # preparePriceWithOptionalFees, distribution cost from JSON
    pv.py                 # apply_irradiation (model PV)
    openmeteo.py          # Pobieranie danych pogodowych
    _taryfy_2025.py       # Baza danych taryf OSD (75+ taryf)
  postprocessing/
    summarize.py          # costRevenue, costWithOptionalFees
  utils/
    utils.py              # changeFreq, readLocalizedTimeDF
    calendar.py           # PolishHolidayCalendar, findPeakIndices
```

### 3.3 Data Flow

```
excel_pagra.xlsx (25 sheets)
    ↓
readInputExcel()
    ↓
cartesianProduct(_cases × _constants)
    → defined_cases (12-24 wariantów)
    ↓
parallelFunc(pool=16 cores)
    ↓ per wariant:
    prepareUserObject()
        → User(P_demand, P_production, price_kWh, EnergyBank)
    ↓
    optimizeBankOverPeriod()  ← rolling horizon LP
    ↓
    postprocessSingleCase()
        → costWithOptionalFees()
    ↓
aggregateResults()
    ↓
writeResultExcel()
    → excel_pagra_finished.xlsx
```

### 3.4 Klasy danych (_basics.py)

#### User
```python
class User:
    P_demand: np.ndarray        # Profil zużycia [kW], 35040 steps (15min)
    P_production: np.ndarray    # Profil produkcji PV [kW]
    price_kWh: np.ndarray       # Cena energii per timestep [PLN/kWh]
    freq: str                   # '15min' lub '1h'
    energyBank: EnergyBank      # Parametry baterii
    powerMarket: PowerMarket    # Parametry rynku mocy (opcjonalnie)
    dsr: DSR                    # Parametry DSR (opcjonalnie)
    export_limit_kW: float      # Limit eksportu [kW]

    # Wyprowadzane:
    net_demand = P_demand - P_production  # Bilans netto
```

#### EnergyBank
```python
class EnergyBank:
    capacity_kWh: float         # Pojemność [kWh]
    max_load_C_ratio: float     # Max C-rate (fraction of capacity per hour)
    SoC_high: float             # Max SoC (0-1)
    SoC_low: float              # Min SoC (0-1)
    efficiency: float           # Round-trip efficiency (0-1)
    SoH: float                  # State of Health (0-1), degradation tracking

    # Time-varying (private, ustawiane przez assemble()):
    _C_ratio_charge: pd.Series      # Charge C-rate over time
    _C_ratio_discharge: pd.Series   # Discharge C-rate over time
    _SoC_high: pd.Series            # Time-varying SoC upper bound
    _SoC_low: pd.Series             # Time-varying SoC lower bound

    # Metody:
    def PowerToDeltaEnergy(P, freq)    # Konwersja moc → ΔE z efektywnością
    def DeltaEnergyToPower(dE, freq)   # Konwersja ΔE → moc z efektywnością
    def updateStateOfHealth(C_rate)    # Aktualizacja SoH na podstawie użycia
```

**Kluczowe różnice vs nasze BatteryParams:**
1. `efficiency` to **round-trip** (single value), nie osobne eta_ch/eta_dis. W LP efektywność jest rozdzielana na ładowanie/rozładowanie przez `getEfficiencyMultiplier()` na podstawie znaku mocy.
2. **Time-varying SoC bounds** — `_SoC_high` i `_SoC_low` mogą się zmieniać w czasie (np. rezerwacja dla bilansowania). U nas SoC bounds są stałe.
3. **SoH tracking** — `SoH` jest aktualizowany w trakcie symulacji, co zmniejsza efektywną pojemność. U nas pojemność jest stała w trakcie dispatchu.

Domyślne roundtrip efficiency: ~0.85 (pagra) vs 0.90 (nasze). Pagra jest bardziej konserwatywna.

#### BatteryAging
```python
class BatteryAging:
    n_cycles_to_eol: int = 6000     # Cykle do końca życia
    eol_soh: float = 0.70           # SoH na EOL (70%)
    mechanism: str = "linear"       # "linear" lub "sqrt"

    # Metody:
    def update_soh(throughput_kWh, capacity_kWh):
        cycles = throughput_kWh / (2 * capacity_kWh)
        if mechanism == "linear":
            soh = 1.0 - (cycles / n_cycles_to_eol) * (1 - eol_soh)
        elif mechanism == "sqrt":
            soh = 1.0 - sqrt(cycles / n_cycles_to_eol) * (1 - eol_soh)
        return max(soh, eol_soh)
```

To jest model degradacji oparty na throughput/cyklach, znacznie bardziej zaawansowany niż nasze liniowe %/rok.

#### PowerMarket
```python
class PowerMarket:
    enabled: bool = False
    capacity_kW: float          # Moc oferowana [kW]
    price_activation_pln: float # Cena za aktywację [PLN/MWh]
    markets: List[str]          # ['aFRR', 'mFRR', 'FCR', 'RR']
    availability_hours: int     # Godziny dostępności/dobę
```

#### DSR (Demand Side Response)
```python
class DSR:
    enabled: bool = False
    capacity_kW: float
    activation_price_pln: float
    max_activations_per_year: int
    duration_hours: float
```

### 3.5 Algorytm LP (linear.py) — SZCZEGÓŁOWO

#### Zmienne decyzyjne
Podobne do naszych: SoC trajectory + cost auxiliary. Ale z KLUCZOWĄ RÓŻNICĄ:

#### Funkcja celu — ZAWIERA KARĘ ZA NIERÓWNOMIERNOŚĆ PROFILU
```
minimize: sum(t_aux[t]) + λ_power × sum(flatness_penalty[t])
```

Gdzie `λ_power` (power_fee_weight) to waga kary za opłatę mocową. pagra dodaje do funkcji celu LP dodatkowy człon penalizujący odchylenie profilu zużycia od średniej.

**To jest NAJWAŻNIEJSZA różnica algorytmiczna.**

#### Szczegóły mechanizmu flatness w pagra (z dekompilacji _constraints.py)

Power fee jest **non-continuous** i zależy od `flatness = mean(P_peak) / mean(P_offpeak)`.
pagra NIE dodaje prostej kary do funkcji celu. Zamiast tego:

1. Definiuje przedziały flatness: `power_fee_flatness_steps` (np. [0.8, 0.9, 1.0, 1.1, 1.2])
2. Każdemu przedziałowi przypisuje współczynnik: `power_fee_coeffs` (np. [0.17, 0.50, 0.83, 1.00])
3. **Rozwiązuje LP OSOBNO** dla każdego przedziału flatness (z dodatkowym ograniczeniem `lpPowerFeeConstr` wymuszającym, by ratio peak/offpeak mieścił się w danym przedziale)
4. Wybiera rozwiązanie o najniższym łącznym koszcie (energia + power fee)

To jest bardziej zaawansowane niż prosta kara — to pełne przeszukiwanie po dyskretnych poziomach flatness.

Constraint `lpPowerFeeConstr`:
```
mean(P_grid[peak_hours]) / mean(P_grid[offpeak_hours]) ∈ [flatness_low, flatness_high]
```
Dodawany jako nierówność liniowa do macierzy A_ub. Najwyższy przedział flatness (bez górnego limitu) jest zawsze feasible → gwarantuje rozwiązanie.

Skutek: Solver pagra aktywnie szuka dispatch'u, który:
1. Minimalizuje koszt energii (jak u nas)
2. **JEDNOCZEŚNIE** spłaszcza profil zużycia (czego my nie robimy)

To powoduje, że BESS w pagra będzie rozładowywany w godzinach szczytu i ładowany w godzinach doliny **nawet jeśli sam arbitraż cenowy tego nie uzasadnia**, bo flatness constraint "wymusza" płaski profil jeśli to daje niższy łączny koszt.

#### Ograniczenia
Identyczna struktura jak u nas:
- Power rate constraints (C-rate, peak shaving)
- Piecewise-linear cost constraints (4 kawałki)
- SoC bounds

#### Rolling Horizon
```python
forecast_hours = 34
keep_hours = 24
```
Identyczne parametry jak u nas (34h/24h).

#### Solver backend
```python
scipy.optimize.linprog(method='highs')
```
Ten sam solver (HiGHS) jak u nas.

### 3.6 Algorytm NLP (hourly.py) — Alternatywny solver

3 tryby działania:

#### 1. Standard optimization
```python
def optimizeEnergyProfile(user, date_range, add_power_fee=False):
    # scipy.optimize.minimize(method='trust-constr' | 'COBYQA' | 'SLSQP')
    # fun = costEnergy() lub costEnergyPowerFee()
    # jac = gradEnergy() lub gradEnergyPowerFee()  (analityczny gradient z _metrics.py)
    # constraints: SoC bounds, power limits, LinearConstraint
    return (results_df, net_cost_PLN)
```

#### 2. Profile matching (kontrola)
```python
def fitPredefinedGridProfile(user, date_range, P_grid_declared):
    # Minimalizuje RMSE między zadanym profilem sieci a osiągniętym
    # Przydatne do testowania strategii sterowania
    return (results_df, distance_metric)
```

#### 3. Balancing with declared profile
```python
def balanceGridProfile(user, date_range, P_grid_declared, balance_price):
    # Grid profile zadeklarowany z góry, odchylenia kosztują balance_price
    # Minimalizuje: declared_cost + balancing_cost
    return (results_df, total_cost)
```

NLP solver pozwala na:
- Nieliniowe koszty (np. kwadratowa kara za peak)
- Bardziej złożone ograniczenia
- Profile matching (dopasowanie do zadanego profilu sieci)
- Koszt odchyleń od deklaracji (balancing)
- Ale jest **wolniejszy** i mniej stabilny

Używany jako fallback lub dla specjalnych przypadków.

### 3.7 Heurystyki (arithmetic.py)

6 strategii bez optymalizacji:

| Funkcja | Strategia | Opis |
|---------|-----------|------|
| `zeroExportEnergyProfile` | Zero export | Minimalizuj eksport do sieci. Nadmiar PV → bateria, brak eksportu |
| `zeroImportEnergyProfile` | Zero import | Minimalizuj import z sieci. Deficyt → bateria first |
| `simpleGridArbitrageEnergyProfile` | Simple arbitrage | Ładuj gdy buy_price < sell_price w innych godzinach |
| `naiveArbitrageEnergyProfile` | Naive arbitrage | Moving average ceny jako threshold |
| `fixedHoursArbitrageEnergyProfile` | Fixed hours | Stałe godziny ładowania/rozładowania (najdroższa/najtańsza średnia) |
| `trivialSolve` | No battery | Brak baterii: P_grid = P_demand - P_production |

Każda zwraca `(results_df, net_cost_PLN)` z kolumnami: P_production, P_demand, P_bank, P_grid, E_bank_stored, buy_price, sell_price.

Wybór solvera jest konfigurowalny:
```python
# Solvers: "linear", "hourly", "arithmetic", "quarterly"
# Controls: "optimal", "zero_export", "zero_import", "arbitrage"
```

### 3.8 Model cenowy (preprocessing/price.py) — SZCZEGÓŁOWO

#### Składniki ceny
```python
# Każdy timestep ma oddzielnie:
buy_price[t]           # Cena kupna energii (stała LUB RDN z PSE)
sell_price[t]          # Cena sprzedaży energii
distribution_cost[t]   # Koszt dystrybucji OSD (z JSON, zone-based)
power_fee              # Opłata mocowa [PLN/kW] (stała)
akcyza                 # Akcyza
oze_fee                # Opłata OZE
cogeneration_fee       # Opłata kogeneracyjna (default: 0.00618 PLN/kWh)
quality_fee            # Opłata jakościowa
color_certificate      # Świadectwo kolorowe
buy_margin_const       # Marża sprzedawcy — stały składnik [PLN/kWh]
buy_margin_ratio       # Marża sprzedawcy — proporcjonalny składnik [%]
sell_margin_const      # Marża sprzedawcy (sprzedaż) — stały
sell_margin_ratio      # Marża sprzedawcy (sprzedaż) — proporcjonalny
bank_efficiency        # Round-trip efficiency baterii (None jeśli brak)
```

#### Pobieranie danych PSE (price.py)
```python
def downloadPSEData(first_day, last_day, entity, extra_select={}):
    # Queries PSE API for:
    # - "rce-pln": ceny RDN (Rynek Dnia Następnego) w PLN
    # - "cmbu-tu": ceny mocy bilansującej (CMBP)
    # Returns: DataFrame z paginacją
```

#### Serializacja taryf
```python
def timeSeriesTariffToJSON(df):
    # Analizuje wzorce (miesięczne, dzienne), tworzy kompaktowy JSON
def jsonToTimeSeriesTariff(raw_json, end_date, tz):
    # Rekonstruuje ciągłą serię z JSON
```

**Kluczowe różnice vs nasze rozwiązanie:**
1. **Cena energii może być z RDN** — pagra pobiera dane z PSE (CSDAC/CMBP) — 35040 wartości 15-minutowych
2. **Koszty dystrybucji z bazy JSON** — 75+ taryf z podziałem na miesiąc/dzień tygodnia/godzinę
3. **Marża sprzedawcy** — jawny składnik (stały + proporcjonalny), my tego nie modelujemy
4. **Power fee w cenie** — stała stawka dodana do ceny + flatness constraint w LP (podwójne uwzględnienie)
5. **Świadectwa kolorowe (color_certificate)** — dodatkowy składnik, my tego nie mamy

#### Baza taryf dystrybucyjnych
```
data/distribution_cost/
├── 2024/
│   ├── Enea/    (B11, B21, B22, B23, C11, C12a, C12b, C21, C22a, C22b, C23...)
│   ├── Energa/  (...)
│   ├── Eon/     (...)
│   ├── PGE/     (...)
│   └── Tauron/  (...)
├── 2025/ (taka sama struktura)
└── 2026/ (taka sama struktura)
```

Każdy plik JSON:
```json
{
  "1": {  // styczeń
    "workday": [[0, 6, 13, 15, 22, 24], [22.98, 124.41, 66.12, 124.41, 22.98]],
    "saturday": [[0, 24], [22.98]],
    "sunday": [[0, 24], [22.98]]
  },
  ...
}
```

**~75 taryf** (5 OSD × ~15 grup taryfowych × 3 lata) vs nasze **7 presetów**.

### 3.9 Usługi bilansujące (solver.py, JG.py) — SZCZEGÓŁOWO

```python
def optimizeWithBalancingServices(user, date_range, pm_dsr, capacity_split, solver, max_calls):
    # 1. Rezerwuj część pojemności dla bilansowania
    #    capacity_split definiuje ile % SoC rezerwować

    # 2. Optymalizuj dispatch energii (LP) z ograniczoną pojemnością
    arbitrage_results = optimizeBankOverPeriod(user, ...)

    # 3. Generuj oferty bilansujące
    OPMB, OEB = createBalancingOffers(
        arbitrage_results, date_range, capacity_split, user, balancing_price
    )
    # OPMB = "Oferta Portfolio na Moce Bilansujące" (power offers)
    # OEB = oferty energii bilansującej

    # 4. Symuluj wywołania rynkowe (PM/DSR events)
    #    max_calls ogranicza liczbę aktywacji

    # 5. Policz przychody: revenue_dict z breakdown per usługa
    return (revenue_dict, results_df, OPMB, OEB)
```

#### Typy usług bilansujących
8 usług w 2 kierunkach (generation/demand):
- **FCR_G / FCR_D** — Frequency Containment Reserve (rezerwa pierwotna)
- **aFRR_G / aFRR_D** — automatic Frequency Restoration Reserve (automatyczna wtórna)
- **mFRRd_G / mFRRd_D** — manual FRR direct (ręczna wtórna)
- **RR_G / RR_D** — Replacement Reserve (rezerwa odbudowy)

#### Prawdopodobieństwo wywołań
```python
class PowerMarketBase:
    daily: List[float]    # Prawdopodobieństwo per godzina (0-23)
    weekly: List[float]   # Mnożnik per dzień tygodnia (Pn-Nd)
    monthly: List[float]  # Mnożnik per miesiąc (I-XII)
    scale: float          # Ogólny mnożnik
```

#### JG_M2 (Jednostka Grafikowa Magazynu, model 2)
```python
class JG_M2:
    P_con: Range          # Zakres mocy konsumpcji [MW]
    P_gen: Range          # Zakres mocy generacji [MW]
    E_stored: float       # Energia magazynowana [MWh]

    # Pojemności per usługa:
    FCR_g, FCR_d, aFRR_g, aFRR_d, mFRRd_G, mFRRd_D, RR_g, RR_d

    def getGO()           # Grafik Obciążenia (load schedule) [1/h]
    def createPPD(SoC, gmb_g, gmb_d)  # Plan Pracy Deklarowany
    def createOPMB()      # Oferty mocy bilansujących
    def getHighestCMBP()  # Najwyższa cena bilansującej pojemności
```

#### Ograniczenia LP dla bilansowania (_constraints.py)
```
# Discharge offer: nie więcej niż moc + SoC pozwala
-(SoC_i - SoC_{i-1})/dt/eff + GMB_d_i <= P_max

# Generation offer: nie więcej niż moc + SoC pozwala
-(SoC_i - SoC_{i-1})/dt * eff + GMB_g_i <= P_max

# SoC po dostarczeniu energii bilansującej musi mieścić się w limitach
GMB_d_i * store_time * eff + SoC_i <= SoC_max
GMB_g_i * store_time/eff - SoC_i <= -SoC_min
```

**My tego NIE MAMY w żadnej formie.**

### 3.10 Postprocessing (summarize.py)

```python
def costWithOptionalFees(
    grid_import_kWh,
    grid_export_kWh,
    prices,
    distribution_cost,
    power_fee,
    additional_fees
):
    # Oblicz koszt energii per timestep
    energy_cost = sum(grid_import * price)
    distribution_cost = sum(grid_import * distribution_rate[zone][hour])
    power_fee_cost = sum(grid_import * power_fee_rate)

    # Eksport: przychód
    export_revenue = sum(grid_export * export_price)

    return CostBreakdown(
        energy=energy_cost,
        distribution=distribution_cost,
        power_fee=power_fee_cost,
        export=export_revenue,
        total=energy_cost + distribution_cost + power_fee_cost - export_revenue
    )
```

### 3.11 Parallel Execution (core/runner.py)

```python
def parallelFunc(defined_cases, n_cores=16):
    with multiprocessing.Pool(n_cores) as pool:
        results = pool.map(runSingleCase, defined_cases)
    return results
```

Każdy wariant (kombinacja bank_size × bank_power × price × export) jest uruchamiany na osobnym rdzeniu. 12 wariantów na 16 rdzeniach = ~30 sekund.

### 3.12 Input/Output (core/io.py)

#### Input: excel_pagra.xlsx (25 sheets)
Kluczowe arkusze:
- `_constants` — stałe parametry (efektywność, SoC limits, SOM rate)
- `_cases` — warianty do przetestowania (bank_size, bank_power, export_limit)
- `Parametry` — parametry ogólne
- `Taryfy` — wybór taryfy
- `Zapotrzebowanie` — profil zużycia (35040 wartości 15min)
- `Produkcja` — profil PV
- `Ceny` — ceny energii (stałe lub RDN)

#### Output: excel_pagra_finished.xlsx
- Arkusze per wariant z wynikami hourly
- Arkusz zbiorczy z porównaniem wariantów
- Koszty z pełnym breakdownem

---

## 4. PORÓWNANIE ALGORYTMÓW OPTYMALIZACJI LP {#4-porownanie-lp}

| Aspekt | Rozwiązanie A (Portal) | Rozwiązanie B (pagra) |
|--------|----------------------|---------------------|
| **Solver** | scipy.linprog + HiGHS | scipy.linprog + HiGHS |
| **Zmienne decyzyjne** | SoC[n] + t_aux[n] = 2n | SoC[n] + t_aux[n] + flatness_aux[n] |
| **Funkcja celu** | min(sum(t_aux × cap)) | min(sum(t_aux × cap) + λ × flatness) |
| **Flatness penalty** | **NIE** | **TAK** — kara za nierównomierność profilu |
| **Rolling horizon** | 34h forecast / 24h keep | 34h forecast / 24h keep |
| **Piecewise cost** | 4 kawałki (ch/dis × buy/sell) | 4 kawałki (identyczne) |
| **Power constraints** | C-rate + peak shaving bounds | C-rate + peak shaving bounds |
| **SoC bounds** | 0.10 - 0.90 | 0.10 - 0.90 |
| **Progressive relaxation** | 4 poziomy | Brak info |
| **NLP fallback** | NIE | TAK (trust-constr/COBYQA) |
| **Parallel execution** | Sekwencyjne | 16 cores (multiprocessing) |
| **Heurystyki** | PV_SURPLUS, PEAK_SHAVING, STACKED (greedy) | zero_export, arbitrage, peak_shaving (greedy) |

### Kluczowa różnica: Flatness Penalty

**Rozwiązanie A** minimalizuje TYLKO koszt energii. Solver nie wie, że spłaszczony profil zużycia daje niższą opłatę mocową (niższą klasę K). Opłata mocowa jest obliczana post-factum.

**Rozwiązanie B** minimalizuje koszt energii PLUS karę za nierównomierność profilu. Solver aktywnie szuka dispatch'u, który spłaszcza zużycie z sieci, co bezpośrednio obniża klasę K i opłatę mocową.

**Konsekwencja:** Dla klientów z wysokim udziałem K4 (typowy profil biurowy/przemysłowy ze szczytem dziennym), pagra da LEPSZE wyniki oszczędności, bo BESS będzie rozładowywany w szczycie nawet gdy arbitraż cenowy tego nie uzasadnia.

---

## 5. PORÓWNANIE MODELI CENOWYCH I TARYFOWYCH {#5-porownanie-cen}

| Aspekt | Rozwiązanie A | Rozwiązanie B |
|--------|--------------|---------------|
| **Cena energii** | Flat lub ToU z presetów | Stała LUB RDN (35040 wartości z PSE) |
| **Taryfy dystrybucyjne** | 7 presetów (3 OSD × C12a/G12) | ~75 taryf (5 OSD × 15 grup × 3 lata) |
| **Grupy taryfowe** | C11, C12a, C12b, C22, G12 | B11, B21, B22, B23, C11, C12a, C12b, C21, C22a, C22b, C23, G11, G12 |
| **OSD** | PGE, Tauron, Energa | PGE, Tauron, Energa, Enea, Eon |
| **Marża sprzedawcy** | Brak (implicit w stawce) | Jawny składnik |
| **Opłata OZE** | W "other_fees" (flat) | Osobny składnik |
| **Ceny RDN** | Brak (placeholder w kodzie) | TAK — download z CSDAC/CMBP PSE |
| **Seasonal rates** | C22 z opcją has_seasonality | Pełne per-month schedules w JSON |
| **Format taryf** | Python code (OsdTariff Pydantic) | JSON per OSD/tariff/year |
| **Export price** | 0 (zero-export) lub flat | Konfigurowalne per timestep |

### Szczegóły bazy taryf pagra

Struktura JSON (data/distribution_cost/2025/PGE/B23.json):
```json
{
  "1": {
    "workday": [[0, 6, 13, 15, 22, 24], [22.98, 124.41, 66.12, 124.41, 22.98]],
    "saturday": [[0, 24], [22.98]],
    "sunday": [[0, 24], [22.98]]
  }
}
```
Interpretacja: W styczniu, w dzień roboczy:
- 0:00-6:00: 22.98 PLN/MWh (noc)
- 6:00-13:00: 124.41 PLN/MWh (szczyt 1)
- 13:00-15:00: 66.12 PLN/MWh (dzień)
- 15:00-22:00: 124.41 PLN/MWh (szczyt 2)
- 22:00-24:00: 22.98 PLN/MWh (noc)

To jest WYŁĄCZNIE składnik dystrybucyjny (OSD variable). Energia czynna + inne opłaty są dodawane osobno.

---

## 6. PORÓWNANIE MODELI BATERII I DEGRADACJI {#6-porownanie-baterii}

| Aspekt | Rozwiązanie A | Rozwiązanie B |
|--------|--------------|---------------|
| **Efektywność** | η_ch = η_dis = 0.9487 (RT=90%) | η_ch = η_dis = ~0.92 (RT=~85%) |
| **SoC range** | 0.10 - 0.90 | 0.10 - 0.90 |
| **C-rate** | power_kw / energy_kwh | power_kW / capacity_kWh |
| **Model degradacji** | Liniowy %/rok (np. 2%/rok) | Throughput-based SoH curve |
| **Formuła degradacji** | `factor = (1-rate)^year` | `soh = 1 - (cycles/6000) * 0.3` lub `1 - sqrt(...)` |
| **Cycles to EOL** | Brak (nie modelowane) | 6000 cykli do 70% SoH |
| **Mechanism** | Brak wyboru | "linear" lub "sqrt" |
| **Calendar aging** | Brak | Prawdopodobnie modelowane (brak pewności) |
| **Impact na sizing** | Savings spadają liniowo z rokiem | Savings spadają z throughput (rzeczywisty użytek) |

### Konsekwencje

1. **Nasze RT=90% vs pagra RT=85%:** Nasze wyniki będą nieco bardziej optymistyczne (wyższe oszczędności z arbitrażu), bo mniej energii tracimy na konwersji.

2. **Degradacja liniowa vs throughput-based:** Nasze wyniki NPV mogą być zbyt optymistyczne dla agresywnego arbitrażu. Jeśli bateria robi 2 cykle/dzień (arbitraż), po 8 latach zrobiła ~5840 cykli → SoH = 71% w modelu pagra. Nasz model z 2%/rok daje SoH = 85% po 8 latach — znaczna różnica.

---

## 7. PORÓWNANIE ANALIZY FINANSOWEJ {#7-porownanie-finanse}

| Aspekt | Rozwiązanie A | Rozwiązanie B |
|--------|--------------|---------------|
| **NPV** | TAK — sum(CF/(1+r)^t) | Brak (nie jest częścią kalkulatora) |
| **IRR** | TAK — Newton-Raphson + bisection | Brak |
| **Simple Payback** | TAK — CAPEX/annual_savings | Brak |
| **Cashflow timeseries** | TAK — per year, z degradacją | Brak |
| **Sensitivity analysis** | TAK — 3 wymiary (discount, energy price, CAPEX) | Brak |
| **Replacement modeling** | TAK — replacement w zadanym roku | Brak |
| **Stacked decomposition** | TAK — rozdzielenie peak+arbitrage CAPEX | Brak |
| **Pareto frontier** | TAK — sizing constraints + Pareto | Brak |
| **Variant comparison** | S/M/L z rekomendacją | Cartesian product (bank_size × power × price) |
| **Advisor response** | TAK — tekstowa rekomendacja | Brak |

### Podsumowanie
Rozwiązanie A ma **znacznie lepszą** analizę finansową. pagra daje surowe wyniki dispatchu i kosztów, ale nie robi analizy inwestycyjnej. Jest to narzędzie obliczeniowe (solver), nie narzędzie decyzyjne (portal).

---

## 8. PORÓWNANIE OBSŁUGI OPŁATY MOCOWEJ {#8-porownanie-oplata-mocowa}

| Aspekt | Rozwiązanie A | Rozwiązanie B |
|--------|--------------|---------------|
| **Algorytm K-class** | TAK — per-day classification | Brak jawnego modułu K-class |
| **Backend thresholds** | K1 < -10%, K2 < 10%, K3 < 30%, K4 ≥ 30% | Brak |
| **Frontend thresholds** | K1 < 5%, K2 < 10%, K3 < 15%, K4 ≥ 15% (celowe) | Brak |
| **SOM rate** | 0.2194 PLN/kWh (2026, URE) | Jako stała w cenie (~219 PLN/MWh) |
| **Selected hours** | 7:00-22:00, per quarter | Nie dotyczy (brak K-class) |
| **Impact na LP** | **Brak** — post-factum only | **Pośredni** — flatness penalty w LP |
| **Savings comparison** | TAK — before/after BESS | Brak jawnego porównania K-class |
| **Monthly breakdown** | TAK — per-month K histogram | Brak |
| **Top 10 days** | TAK — analiza najdroższych dni | Brak |

### Jak pagra obsługuje opłatę mocową

pagra NIE ma osobnego modułu K-class. Zamiast tego:
1. Opłata mocowa jest dodana jako STAŁA STAWKA per kWh do ceny energii (np. 219 PLN/MWh)
2. **Flatness penalty** w LP pośrednio redukuje opłatę mocową, bo spłaszcza profil
3. Nie ma analizy K1/K2/K3/K4, nie ma dziennej klasyfikacji

### Jak nasze rozwiązanie obsługuje opłatę mocową

My mamy **pełną analitykę K-class** (dzienną klasyfikację, histogram, top 10 dni, savings comparison), ale **solver LP nie wie o opłacie mocowej** — obliczamy ją post-factum.

### Paradoks
- pagra: **lepszy dispatch** (solver aktywnie optymalizuje pod spłaszczenie), ale **gorsza analityka** (brak K-class details)
- Portal: **gorsza optymalizacja** (solver nie optymalizuje pod K-class), ale **lepsza analityka** (pełny K-class breakdown)

Idealne rozwiązanie: nasz K-class analytics + flatness penalty pagra w solverze LP.

---

## 9. PORÓWNANIE ARCHITEKTURY I UX {#9-porownanie-architektura}

| Aspekt | Rozwiązanie A | Rozwiązanie B |
|--------|--------------|---------------|
| **Typ** | Web portal (Docker, 37 kontenerów) | Desktop app (PyInstaller) |
| **Dostęp** | Przeglądarka, multi-user | Lokalna instalacja, single-user |
| **GUI** | Nowoczesny HTML/JS (mikrofrontendy) | tkinter (podstawowy) |
| **API** | REST (FastAPI, OpenAPI docs) | Brak (Excel I/O) |
| **Monitoring** | Prometheus + Grafana | Brak |
| **Reproducibility** | Repro bundles, audit trail | Brak |
| **Input** | Web forms + REST API | Excel (25 sheets) |
| **Output** | Interaktywne wykresy + JSON API | Excel (wyniki) |
| **Deployment** | `docker compose up -d` | Uruchom .exe |
| **Skalowanie** | Horizontal (per container) | Vertical (multiprocessing) |
| **Wersjonowanie** | Git, semver, ENGINE_VERSION | Brak widocznego |
| **Testowanie** | Testy jednostkowe (pytest) | Brak widocznych testów |
| **Czas obliczeń** | ~5 min (sekwencyjne) | ~30s (16 cores parallel) |

---

## 10. PODSUMOWANIE MOCNYCH I SŁABYCH STRON {#10-podsumowanie}

### Rozwiązanie A (Portal) — Mocne strony
1. **Analiza finansowa** — NPV, IRR, cashflow, sensitivity analysis, payback
2. **K-class analytics** — pełna dzienna klasyfikacja, histogram, top 10 days
3. **UX** — webowy portal, interaktywne wykresy, multi-user
4. **Observability** — Prometheus metryki, structured logging, repro bundles
5. **API** — REST API umożliwiające integrację z innymi systemami
6. **Progressive relaxation** — 4-level fallback gwarantujący zawsze wynik
7. **Stacked decomposition** — rozdzielenie peak shaving + arbitrage sizing
8. **Grid constraints** — max import/export limits z post-processing

### Rozwiązanie A (Portal) — Słabe strony
1. **KRYTYCZNE: Brak flatness penalty w LP** — solver nie optymalizuje pod opłatę mocową
2. **Brak cen RDN** — nie integruje cen z Rynku Dnia Następnego
3. **Ograniczona baza taryf** — 7 presetów vs ~75 u pagra
4. **Uproszczona degradacja** — liniowy %/rok zamiast throughput-based SoH
5. **Brak usług bilansujących** — nie modeluje aFRR/mFRR/FCR/DSR
6. **Brak marży sprzedawcy** — nie rozdziela marży od ceny energii
7. **Sekwencyjne obliczenia** — brak paralelizacji wariantów
8. **Brak eksportu szczegółowych wyników** — brak hourly CSV/Excel

### Rozwiązanie B (pagra) — Mocne strony
1. **Flatness penalty w LP** — solver aktywnie spłaszcza profil zużycia
2. **Ceny RDN** — integracja z CSDAC/CMBP PSE (dane 15-minutowe)
3. **Bogata baza taryf** — ~75 taryf (5 OSD × 15 grup × 3 lata)
4. **Realistyczna degradacja** — throughput-based SoH (6000 cykli do 70%)
5. **Usługi bilansujące** — model PowerMarket, DSR, JG_M2
6. **NLP fallback** — alternatywny solver dla nieliniowych kosztów
7. **Parallel execution** — 16 cores, ~30s na 12 wariantów
8. **Marża sprzedawcy** — jawny składnik ceny

### Rozwiązanie B (pagra) — Słabe strony
1. **Brak analizy finansowej** — brak NPV, IRR, sensitivity
2. **Brak K-class analytics** — brak dziennej klasyfikacji
3. **Desktop only** — brak API, brak multi-user, brak web access
4. **Brak monitoringu** — brak Prometheus, brak logów
5. **Skomplikowany input** — Excel z 25 arkuszami
6. **Brak stacked decomposition** — brak rozdzielenia komponentów sizing
7. **Brak progressive relaxation** — potencjalnie niestabilne wyniki LP
8. **Closed-source** — brak możliwości modyfikacji (PyInstaller)

---

## 11. FRONTEND — SZCZEGÓŁY UI I KOMUNIKACJI {#11-frontend}

### 11.1 Architektura frontend (mikrofrontendy)

Portal używa **iframe-based microfrontend** architektury:
- `frontend-shell` — główna powłoka, nginx reverse proxy, nawigacja
- Moduły ładowane jako iframe'y: bess, economics, consumption, config, production, etc.
- Komunikacja między modułami: `window.postMessage()` z typami:
  - `NAVIGATE_TO_MODULE` — przełączanie modułów
  - `REQUEST_SETTINGS` — pobranie ustawień z shell
  - `SHARED_DATA_RESPONSE` — wymiana danych wariantów
  - `DATA_AVAILABLE` / `PROJECT_LOADED` — odświeżenie po załadowaniu projektu

### 11.2 frontend-bess (bess.js — 11,146 linii)

**Cel:** Konfiguracja i wyświetlanie wyników sizing BESS.

**Kluczowe funkcje:**
- `fetchSizingVariants()` → `POST /api/bess-dispatch/sizing` (compat=clean)
- `displaySizingVariants()` — renderuje siatkę S/M/L (1h, 2h, 4h duration)
- `updateEnergyMetrics()` — autokonsumpcja, discharge, cykle
- `updateEconomics()` — CAPEX, OPEX, replacement schedule
- `runCapacityFeeAnalysisIfEnabled()` → `POST /api/bess-dispatch/capacity-fee/savings`

**UI features:**
- Siatka wariantów S/M/L z rekomendacją (highlight najlepszego NPV)
- SVG-based animacja energy flow (real-time godzinowe)
- Monthly/quarterly breakdown tables
- Savings breakdown: energia, peak shaving, capacity fee, arbitraż, eksport, degradacja
- Arbitrage overlay (ToU visualization)
- Degradation budget z replacement schedule
- Stacked mode info (priorytety: peak shaving > PV surplus > arbitrage)

**Algorytmy client-side:**
- P95 Peak Limit — 95-percentyl profilu jako target peak shaving
- Reserve fraction — 30% SoC na peak shaving
- Multi-engine comparison z convergence metrics

### 11.3 frontend-economics (economics.js — 19,498 linii)

**Cel:** Pełna analiza finansowa inwestycji PV+BESS.

**Kluczowe funkcje:**
- `calculateCentralizedFinancialMetrics()` — **SSoT** dla wszystkich obliczeń NPV
- `calculateBessReplacementSchedule()` — lifecycle cost z replacement events
- `calculateIRR()` + `fetchBackendIRR()` — obliczenia lokalne + walidacja backend
- `calculateEaaSFullModel()` — Energy-as-a-Service subscription model
- `generatePulsDniaChart()` — 24h energy flow z real data lub synthetic
- `getSolarParametersForDay()` — solar equation dla ~52°N (Polska)

**UI features:**
- **Financial Dashboard:** CAPEX breakdown, OPEX %, replacement, residual value
- **NPV/IRR analysis:** Sensitivity sweeps (discount rate, energy price, CAPEX)
- **EaaS Pricing:** Miesięczna/roczna subskrypcja z CPI indexation
- **PULS DNIA (24h Energy Flow):** Kalendarz (miesiąc/dzień), real hourly consumption, synthetic PV, 4 wykresy: produkcja, grid, BESS, koszty godzinowe
- **Bankability:** DSCR, loan covenant analysis
- **P50/P75/P90 scenariusze** produkcji

**Algorytmy client-side:**
- Day-length calculation: ~8h (zima) do ~16.5h (lato) dla 52°N
- Production factor: cosine-based seasonal variation
- EaaS IRR target solving: iteracyjne obliczenie subscription → target IRR
- Sensitivity: [4%, 6%, 8%, 10%, 12%, 15%] discount × [0.8-1.2x] energy × [0.8-1.2x] CAPEX
- Residual value: zero / market (20% CAPEX) / contractual (PLN/kWp buyback)

### 11.4 frontend-consumption (consumption.js — 4,761 linii)

**Cel:** Analiza profilu zużycia + K-class (opłata mocowa) — analiza PV-only (bez BESS).

**Kluczowe funkcje K-class (linie ~3100-3300):**
```javascript
function getKClass(deltaS) {
    if (deltaS < 5)  return { class: 'K1', coefficient: 0.17 };  // UWAGA: 5% nie -10%
    if (deltaS < 10) return { class: 'K2', coefficient: 0.50 };
    if (deltaS < 15) return { class: 'K3', coefficient: 0.83 };
    return { class: 'K4', coefficient: 1.00 };
}
```
**UWAGA:** Progi frontendowe (5/10/15%) są CELOWO inne niż ustawowe (-10/10/30%). Użytkownik potwierdził, że to jest poprawione/zamierzone.

- `getPolishHolidays(year)` — 13 świąt (ruchome Wielkanoc + stałe)
- `isPolishWorkday(date)` — Pn-Pt minus święta
- `calculateKClassAnalysis(loadHourly, pvHourly, year, som)` — per-day K-class before/after PV

**Algorytm K-class (client-side):**
1. Per dzień roboczy: podział load na godziny 7-22 (selected) vs reszta (outside)
2. `Δs = ((avgSelected / avgOutside) - 1) × 100%`
3. Before PV: klasyfikacja na load
4. After PV: klasyfikacja na `max(load - pv, 0)` (grid draw)
5. Fee = coefficient × SOM × ZS[kWh]
6. Monthly savings = sum(fee_before - fee_after) per miesiąc

### 11.5 Nginx routing (frontend-shell/nginx.conf)

**17 modułów frontendowych:**
- admin, config, consumption, production, comparison, economics, settings, esg, energyprices, reports, projects, estimator, bess, profile, hub, scoring, siteassessment

**Backend API routing:**
| Path | Backend | Timeout |
|------|---------|---------|
| `/api/data/` | pv-data-analysis:8001 | default |
| `/api/pv/` | pv-calculation:8002 | default |
| `/api/economics/` | pv-economics:8003 | default |
| `/api/bess-dispatch/` | pv-bess-dispatch:8031 | **300s** |
| `/api/bess-optimizer/` | pv-bess-optimizer:8030 | **300s** |
| `/api/reports/` | pv-reports:8011 | 60s |
| `/api/projects/` | pv-projects-db:8012 | default |
| `/api/profile/` | pv-profile-analysis:8040 | 120s |

Client body size limit: 100MB. Caching wyłączony dla economics/settings.

---

## ZAŁĄCZNIK A: Kluczowe pliki źródłowe

### Rozwiązanie A (Portal)
| Plik | Lokalizacja | Rola |
|------|------------|------|
| lp_dispatch.py | services/bess-dispatch/ | LP solver z rolling horizon |
| dispatch_engine.py | services/bess-dispatch/ | Algorytmy greedy |
| models.py | services/bess-dispatch/ | Pydantic DTOs |
| sizing_runner.py | services/bess-dispatch/ | Sizing + NPV/IRR |
| economics_helper.py | services/bess-dispatch/ | Unified cost calculation |
| price_engine.py | services/bess-dispatch/ | PriceBundle provider |
| calculator.py | services/bess-dispatch/capacity_fee_pl/ | K-class capacity fee |
| models.py | services/bess-dispatch/capacity_fee_pl/ | K-class models |
| templates.py | services/bess-dispatch/osd_tariffs/presets/ | OSD tariff presets |
| app.py | services/bess-dispatch/ | FastAPI endpoints |
| consumption.js | services/frontend-consumption/ | Frontend K-class analysis |
| economics.js | services/frontend-economics/ | Frontend finance UI |
| bess.js | services/frontend-bess/ | Frontend BESS config/results |

### Rozwiązanie B (pagra-galileo)
| Moduł | Rola |
|-------|------|
| ozetoolbox/solver/linear.py | LP solver z flatness penalty |
| ozetoolbox/solver/solver.py | Rolling horizon orchestrator |
| ozetoolbox/solver/_basics.py | User, EnergyBank, BatteryAging, PowerMarket, DSR |
| ozetoolbox/solver/hourly.py | NLP solver (trust-constr) |
| ozetoolbox/solver/arithmetic.py | Heuristic strategies |
| ozetoolbox/solver/_constraints.py | LP constraint matrices |
| ozetoolbox/preprocessing/price.py | Price preparation with fees |
| ozetoolbox/preprocessing/_taryfy_2025.py | OSD tariff database |
| core/runner.py | Parallel execution (16 cores) |
| core/io.py | Excel I/O |
| pagra_galileo/runner.py | Main orchestrator |

---

## ZAŁĄCZNIK B: Rekomendowane ulepszenia Rozwiązania A

### Priorytet 1 — Krytyczne
1. **Dodać flatness penalty do LP** — λ_power × sum(deviation from mean) w funkcji celu
2. **Integracja cen RDN** — pobieranie z PSE, PriceBundle z wariantem RDN
3. **Rozbudowa bazy taryf OSD** — dodać Enea, Eon, grupy B, pełne per-month schedules

### Priorytet 2 — Ważne
4. **Throughput-based degradacja** — model SoH oparty na cyklach (6000 → 70%)
5. **Uproszczone usługi bilansujące** — szacunkowy przychód z aFRR/mFRR
6. **Marża sprzedawcy** — osobne pole w konfiguracji cenowej

### Priorytet 3 — Nice-to-have
7. **Parallel sizing** — multiprocessing dla wariantów
8. **Eksport hourly wyników** — CSV/Excel z pełnym profilem 8760h
9. **NLP solver** — alternatywny solver dla złożonych przypadków

---

*Dokument wygenerowany: 2026-03-07*
*Źródło: Analiza kodu źródłowego obu rozwiązań*
