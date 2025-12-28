# BESS Dispatch System Architecture

## Wersja dokumentu
- **Data**: 2025-12-25
- **Engine Version**: 1.2.0
- **Service Port**: 8031

---

## 1. Przegląd Systemu

System BESS Dispatch to mikroserwis odpowiedzialny za symulację pracy magazynu energii (BESS) w różnych trybach operacyjnych. Serwis jest częścią większego systemu "Pagra ENERGY Studio" do analizy instalacji PV+BESS.

### Lokalizacja kodu
```
services/bess-dispatch/
├── app.py                    # FastAPI main + endpoints
├── api_arbitrage.py          # ToU Arbitrage API (NEW)
├── models.py                 # Pydantic DTOs
├── dispatch_engine.py        # Core dispatch algorithms
├── dispatch_arbitrage.py     # ToU arbitrage algorithm (NEW)
├── price_engine.py           # Price signals infrastructure (NEW)
├── sizing_runner.py          # BESS sizing optimization
├── sensitivity_runner.py     # Tornado chart sensitivity
├── capacity_fee_pl/          # Polish capacity fee (Opłata Mocowa)
│   ├── calculator.py
│   ├── models.py
│   └── calendar_pl.py
├── osd_tariffs/              # OSD tariff definitions
│   ├── models.py
│   ├── compiler.py
│   ├── validators.py
│   └── presets/
│       └── templates.py      # PGE, TAURON, ENERGA presets
└── common/
    ├── calendar_pl.py        # Polish holidays
    └── time_utils.py         # Timezone handling (CET)
```

---

## 2. Tryby Dispatch (DispatchMode)

### 2.1. PV_SURPLUS (Autokonsumpcja)
**Cel**: Maksymalizacja zużycia własnego energii z PV

**Algorytm**:
1. Energia z PV najpierw pokrywa obciążenie (direct consumption)
2. Nadwyżka PV ładuje baterię (do SOC_max)
3. Deficyt pokrywany z baterii (do SOC_min)
4. Pozostała nadwyżka jest curtailowana (model 0-export)
5. Pozostały deficyt pobierany z sieci

**Parametry**:
- `battery_power_kw`: Moc nominalna [kW]
- `battery_energy_kwh`: Pojemność [kWh]
- `roundtrip_efficiency`: Sprawność (domyślnie 0.90)
- `soc_min/soc_max`: Limity SOC (domyślnie 10%-90%)

**Metryki**:
- `self_consumption_pct`: % autokonsumpcji PV
- `grid_independence_pct`: % niezależności od sieci
- `total_curtailment_kwh`: Energia stracona (curtail)

---

### 2.2. PEAK_SHAVING
**Cel**: Redukcja szczytów poboru mocy z sieci

**Algorytm**:
1. Gdy `net_load > peak_limit_kw`: rozładuj baterię
2. Gdy `net_load < peak_limit_kw`: ładuj z sieci (headroom charging)
3. Nadwyżka PV jest curtailowana

**Parametry dodatkowe**:
- `peak_limit_kw`: Limit importu z sieci [kW]

**Metryki**:
- `original_peak_kw`: Szczyt przed BESS
- `new_peak_kw`: Szczyt po BESS
- `peak_reduction_pct`: % redukcji szczytu

---

### 2.3. STACKED (PV Shifting + Peak Shaving)
**Cel**: Dual-service - jedna bateria świadczy dwie usługi

**Algorytm z priorytetami**:
1. **PRIORYTET 1 - Peak Shaving**: Gdy `net_load > peak_limit_kw`
   - Rozładuj baterię (może użyć pełnego SOC włącznie z rezerwą)
2. **PRIORYTET 2 - PV Shifting**: Gdy `net_load <= peak_limit_kw`
   - Nadwyżka PV → ładuj baterię
   - Deficyt → rozładuj baterię (tylko SOC powyżej rezerwy!)

**Parametry dodatkowe**:
- `peak_limit_kw`: Limit importu [kW]
- `reserve_fraction`: Rezerwa SOC dla peak shaving (domyślnie 30%)

**Mechanizm rezerwy SOC**:
```
|-------|===============|=======|
SOC_min  reserve_soc   SOC_max

PV shifting może używać tylko: [reserve_soc → SOC_max]
Peak shaving może używać:      [SOC_min → SOC_max] (pełny zakres)
```

**Metryki degradacji per-usługa**:
- `efc_pv`: Cykle dla PV shifting
- `efc_peak`: Cykle dla peak shaving
- `throughput_pv_mwh` / `throughput_peak_mwh`: Przepustowość per usługa

---

### 2.4. LOAD_ONLY (Stand-alone BESS bez PV)
**Cel**: Peak shaving dla obiektów bez fotowoltaiki

**Algorytm**:
1. Rozładuj gdy `load > peak_limit_kw`
2. Ładuj z sieci gdy `load < peak_limit_kw` (headroom)
3. Całe ładowanie z sieci (charge_from_grid = 100%)

**Use cases**:
- Zakłady przemysłowe z opłatami mocowymi
- Przygotowanie pod przyszły arbitraż ToU

---

### 2.5. ARBITRAGE (Time-of-Use) - NOWY, OSOBNY ENDPOINT
**Cel**: Zarabianie na różnicach cen w strefach taryfowych

**UWAGA**: Ten tryb NIE jest jeszcze zintegrowany z głównym dispatch_engine!
Działa jako osobne API: `POST /arbitrage/dispatch`

**Algorytm** (w `dispatch_arbitrage.py`):
1. Ładuj gdy `price < charge_threshold` (percentyl P25)
2. Rozładuj gdy `price > discharge_threshold` (percentyl P75)
3. Opcjonalnie: `peak_limit_kw` dla trybu hybrydowego

**Strategia cenowa**:
```python
class ArbitrageStrategy(Enum):
    PERCENTILE_THRESHOLD = "percentile"  # P25/P75 thresholds
    ZONE_BASED = "zone_based"            # Charge in II, discharge in I
    SPREAD_THRESHOLD = "spread"          # Min spread requirement
```

---

## 3. System Cen (Price Engine)

### 3.1. Architektura

```
┌─────────────────────────────────────────────────────────────────┐
│                      PriceBundle (output)                        │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐ │
│  │ import_total[t] │  │ export_total[t] │  │ breakdown[t]     │ │
│  │ [PLN/kWh]       │  │ [PLN/kWh]       │  │ zone + components│ │
│  └─────────────────┘  └─────────────────┘  └──────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
┌─────────────────────────────────────────────────────────────────┐
│                    ToUPriceProvider                              │
│  - Kompiluje taryfy OSD na serie godzinowe                      │
│  - Dodaje opłatę mocową + inne składniki                        │
│  - Obsługuje sezonowość (lato/zima)                             │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
┌─────────────────────────────────────────────────────────────────┐
│                    OsdTariff (preset)                            │
│  - Definicja stref (I = szczyt, II = pozaszczyt, III = noc)    │
│  - Schedule blocks z segmentami minut                           │
│  - Stawki per strefa [PLN/kWh]                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2. Składniki ceny importu

```python
class PriceComponent(str, Enum):
    ENERGY = "energy"           # Stawka bazowa z taryfy (energia + dystrybucja)
    CAPACITY_FEE = "capacity"   # Opłata mocowa [PLN/kWh]
    OTHER = "other"             # Akcyza, OZE, kogeneracja [PLN/kWh]
```

**Przykład dla PGE C12a 2025**:
- Strefa I (szczyt): 0.85 PLN/kWh
- Strefa II (pozaszczyt): 0.55 PLN/kWh
- + Opłata mocowa: 0.12 PLN/kWh
- = Total: 0.97 / 0.67 PLN/kWh

### 3.3. Presety taryfowe

Lokalizacja: `osd_tariffs/presets/templates.py`

```python
ALL_PRESETS = {
    "pge_c12a_2025": PGE_C12A_2025,      # 2-strefowa
    "tauron_c12a_2025": TAURON_C12A_2025, # 2-strefowa
    "energa_g12_2025": ENERGA_G12_2025,   # 2-strefowa
    # ... więcej presetów
}
```

---

## 4. API Endpoints

### 4.1. Główne endpointy dispatch

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/dispatch` | POST | Symulacja dispatch (wszystkie tryby oprócz ARBITRAGE) |
| `/sizing` | POST | Optymalizacja rozmiaru BESS (S/M/L) |
| `/sizing/quick` | POST | Szybki sizing dla PV-surplus |
| `/sensitivity` | POST | Analiza wrażliwości (tornado chart) |

### 4.2. Endpointy arbitrażu (NOWE)

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/arbitrage/dispatch` | POST | Symulacja arbitrażu ToU |
| `/arbitrage/tariffs` | GET | Lista dostępnych taryf |
| `/arbitrage/prices/preview` | POST | Podgląd cen dla zakresu dat |

### 4.3. Endpointy opłaty mocowej

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/capacity-fee` | POST | Oblicz opłatę mocową |
| `/capacity-fee/savings` | POST | Porównanie przed/po BESS |
| `/capacity-fee/presets/{year}` | GET | Preset dla roku |

### 4.4. Endpointy taryf OSD

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/osd-tariffs/presets` | GET | Lista presetów |
| `/osd-tariffs/presets/{id}` | GET | Szczegóły presetu |
| `/osd-tariffs/validate` | POST | Walidacja definicji taryfy |
| `/osd-tariffs/compile` | POST | Kompilacja dla daty |
| `/osd-tariffs/compile-range` | POST | Kompilacja dla zakresu |

---

## 5. Modele Danych

### 5.1. DispatchRequest

```python
class DispatchRequest(BaseModel):
    topology: TopologyType        # pv_load | load_only
    pv_generation_kw: List[float] # Generacja PV [kW], puste dla load_only
    load_kw: List[float]          # Zużycie [kW]
    interval_minutes: int         # 15 lub 60
    battery: BatteryParams
    mode: DispatchMode
    stacked_params: Optional[StackedModeParams]
    peak_limit_kw: Optional[float]
    prices: PriceConfig
    degradation_budget: Optional[DegradationBudget]
```

### 5.2. DispatchResult

```python
class DispatchResult(BaseModel):
    # Konfiguracja
    mode: DispatchMode
    battery_power_kw: float
    battery_energy_kwh: float

    # Przepływy energii [kWh]
    total_pv_kwh: float
    total_load_kwh: float
    total_direct_pv_kwh: float
    total_charge_kwh: float
    total_discharge_kwh: float
    total_grid_import_kwh: float
    total_grid_export_kwh: float      # Zawsze 0 dla modelu 0-export
    total_curtailment_kwh: float

    # Metryki autokonsumpcji
    self_consumption_pct: float
    grid_independence_pct: float

    # Metryki peak shaving
    original_peak_kw: float
    new_peak_kw: float
    peak_reduction_pct: float

    # Degradacja
    degradation: DegradationMetrics

    # Ekonomia
    baseline_cost_pln: float
    project_cost_pln: float
    annual_savings_pln: float

    # Tablice godzinowe (opcjonalne)
    hourly_charge_kw: Optional[List[float]]
    hourly_discharge_kw: Optional[List[float]]
    hourly_soc_pct: Optional[List[float]]
    hourly_grid_import_kw: Optional[List[float]]
```

### 5.3. DegradationMetrics

```python
class DegradationMetrics(BaseModel):
    # Przepustowość
    throughput_charge_kwh: float
    throughput_discharge_kwh: float
    throughput_total_mwh: float

    # EFC (Equivalent Full Cycles)
    efc_total: float

    # Per-service breakdown (dla STACKED)
    efc_pv: float
    efc_peak: float
    throughput_pv_mwh: float
    throughput_peak_mwh: float

    # Statystyki peak shaving
    peak_events_count: int
    peak_max_discharge_kw: float

    # Źródło ładowania
    charge_from_pv_kwh: float
    charge_from_grid_kwh: float
    charge_pv_pct: float

    # Status budżetu
    budget_status: DegradationStatus  # ok | warning | exceeded
    budget_utilization_pct: float
```

---

## 6. Ekonomia i Sizing

### 6.1. Funkcja celu dla sizing

```python
NPV = -CAPEX + Σ(t=1→n) [ (annual_savings - OPEX) / (1 + r)^t ]

gdzie:
- CAPEX = energy_kwh × capex_per_kwh + power_kw × capex_per_kw
- OPEX = CAPEX × opex_pct_per_year
- annual_savings = energy_savings + demand_savings
- r = discount_rate
- n = analysis_years
```

### 6.2. Warianty sizing

| Wariant | Duration | Typowe zastosowanie |
|---------|----------|---------------------|
| Small | 1h | Peak shaving krótkotrwałych szczytów |
| Medium | 2h | Balanced PV shifting + peak |
| Large | 4h | Maksymalizacja autokonsumpcji |

### 6.3. Multi-objective optimization (NOWE)

```python
class OptimizationObjective(str, Enum):
    NPV = "npv"                         # Maksymalizuj NPV (domyślne)
    PAYBACK = "payback"                 # Minimalizuj payback
    SELF_CONSUMPTION = "self_consumption"
    PEAK_REDUCTION = "peak_reduction"
    EFC_UTILIZATION = "efc_utilization"

class ConstraintType(str, Enum):
    MAX_CAPEX = "max_capex"             # Budżet maksymalny
    MAX_PAYBACK = "max_payback"         # Maksymalny payback [lata]
    MIN_NPV = "min_npv"                 # Minimalny NPV
    MAX_EFC = "max_efc"                 # Limit cykli/rok
```

---

## 7. Integracja z Frontendem

### 7.1. Flow analizy PV+BESS

```
USTAWIENIA (settings.js)
    │
    │  bessMode: 'off' | 'light' | 'pro'
    │  bessDuration: 'auto' | 1 | 2 | 4
    │  bessTopology: 'pv_bess' | 'bess_only'
    ▼
KONFIGURACJA (config-v2.js)
    │
    │  Buduje bess_config i wysyła do pv-calculation
    ▼
PV-CALCULATION (app.py)
    │
    │  Wywołuje auto_size_bess_lite() lub call_bess_pro_optimizer()
    │  Następnie simulate_pv_system_with_bess()
    ▼
BESS-DISPATCH (sizing API)
    │
    │  Zwraca SizingResult z wariantami S/M/L
    ▼
Frontend BESS Module (bess.js)
    │
    │  Sprawdza: variant.bess_power_kw > 0
    │  Jeśli TAK → pokazuje wyniki BESS
    │  Jeśli NIE → pokazuje "BESS disabled"
```

### 7.2. Arbitraż (osobny flow - jeszcze NIE zintegrowany)

```
Frontend (przyszłość)
    │
    │  POST /api/bess/arbitrage/dispatch
    ▼
BESS-DISPATCH (api_arbitrage.py)
    │
    │  Pobiera taryfy z presetów
    │  Kompiluje ceny za pomocą price_engine
    │  Uruchamia dispatch_arbitrage
    ▼
Wynik: ArbitrageDispatchResponse
    - dispatch: DispatchResult
    - price_summary: thresholds, zones
    - arbitrage_analysis: savings, spread
```

---

## 8. Co Jest Zrobione vs Co Trzeba Zrobić

### ✅ ZROBIONE

1. **Tryby dispatch**: PV_SURPLUS, PEAK_SHAVING, STACKED, LOAD_ONLY
2. **Sizing**: Grid search z NPV, warianty S/M/L
3. **Degradacja**: EFC, throughput, per-service breakdown
4. **Sensitivity**: Tornado chart analysis
5. **Opłata mocowa**: K-class, SOM, strefy godzinowe
6. **Taryfy OSD**: Presety PGE/TAURON/ENERGA, compiler
7. **Price Engine (MVP)**: ToUPriceProvider, PriceBundle
8. **Arbitrage API**: Osobny endpoint `/arbitrage/dispatch`

### ❌ DO ZROBIENIA (dla pełnej integracji arbitrażu)

1. **Dodać ARBITRAGE do dispatch_engine.py** jako natywny tryb
2. **Nowy tryb STACKED_ARBITRAGE**: Peak + PV + Arbitrage
3. **Frontend UI dla arbitrażu**: Wybór taryfy, preview cen
4. **Integracja z sizing**: Automatyczne dodawanie arbitrage savings do NPV
5. **RDN arbitrage**: Ceny giełdowe (przyszłość)

---

## 9. Przykłady użycia API

### 9.1. STACKED dispatch

```bash
curl -X POST http://localhost:8031/dispatch \
  -H "Content-Type: application/json" \
  -d '{
    "pv_generation_kw": [0,0,0,0,0,10,50,100,...],
    "load_kw": [200,180,190,210,...],
    "interval_minutes": 60,
    "battery_power_kw": 100,
    "battery_energy_kwh": 200,
    "mode": "stacked",
    "peak_limit_kw": 535,
    "reserve_fraction": 0.3,
    "import_price_pln_mwh": 800,
    "demand_charge_pln_kw_month": 50
  }'
```

### 9.2. ToU Arbitrage dispatch

```bash
curl -X POST http://localhost:8031/arbitrage/dispatch \
  -H "Content-Type: application/json" \
  -d '{
    "load_kw": [200,180,190,...],
    "start_date": "2025-01-01",
    "battery_power_kw": 100,
    "battery_energy_kwh": 200,
    "tariff_id": "pge_dystrybucja_c12a_2025",
    "capacity_fee_pln_kwh": 0.12,
    "strategy": "percentile",
    "charge_below_percentile": 25,
    "discharge_above_percentile": 75
  }'
```

### 9.3. Sizing z constraints

```bash
curl -X POST http://localhost:8031/sizing \
  -H "Content-Type: application/json" \
  -d '{
    "pv_generation_kw": [...],
    "load_kw": [...],
    "mode": "stacked",
    "peak_limit_kw": 500,
    "optimization": {
      "objective": "npv",
      "constraints": [
        {"constraint_type": "max_capex", "value": 2000000, "hard": true},
        {"constraint_type": "max_payback", "value": 8, "hard": false}
      ]
    }
  }'
```

---

## 10. Uwagi dla Agenta

### Kluczowe pliki do modyfikacji przy dodawaniu ARBITRAGE do głównego flow:

1. **models.py**: Dodać nowe pola do `DispatchRequest` (price_bundle, arbitrage_config)
2. **dispatch_engine.py**: Dodać `dispatch_arbitrage_mode()` lub rozszerzyć `dispatch_stacked()`
3. **app.py**: Rozszerzyć `/dispatch` o obsługę trybu ARBITRAGE z cenami
4. **sizing_runner.py**: Uwzględnić arbitrage savings w NPV

### Zależności między modułami:

```
models.py ← dispatch_engine.py ← app.py
              ↑
         dispatch_arbitrage.py ← price_engine.py ← osd_tariffs/
```

### Polish specifics:

- **Strefy czasowe**: Taryfy używają CET (czas zimowy) całorocznie
- **Święta**: `common/calendar_pl.py` zawiera polskie dni wolne
- **Opłata mocowa**: Godziny 7:00-22:00 w dni robocze (2026)
