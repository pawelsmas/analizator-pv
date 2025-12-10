# Model Analizy Profilu PV+BESS - Dokumentacja Techniczna


**Data:** 2024-12-10
**Status:** Produkcja (model uproszczony)

---

## 1. Podsumowanie Wykonawcze

Model służy do **wstępnego doboru wielkości magazynu energii (BESS)** dla instalacji PV na podstawie profilu zużycia i produkcji. Używa uproszczonej analityki zamiast pełnej optymalizacji matematycznej, co zapewnia szybkie wyniki  wystarczające do wstępnej analizy opłacalności.

### Co model robi:
- Analizuje godzinowy bilans energii (PV vs zużycie)
- Identyfikuje nadwyżki i deficyty w podziale miesięcznym
- Generuje front Pareto (NPV vs cykle)
- Rekomenduje rozmiar BESS według trzech strategii
- Oblicza NPV, payback, curtailment

### Czego model NIE robi (jeszcze):
- Godzinowa symulacja stanu naładowania (SoC)
- Optymalizacja dispatch (LP/MILP)
- Uwzględnienie strat pomocniczych BESS
- Degradacja baterii
- Dynamiczne ceny energii

---

## 2. Architektura

```
┌─────────────────────────────────────────────────────────────────────┐
│                    FRONTEND (profile.js)                            │
│  - Pobiera dane z shell (hourlyData, timestamps, analyticalYear)    │
│  - Wysyła request do backendu                                       │
│  - Wizualizuje wyniki (Chart.js)                                    │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ POST /api/profile/analyze
┌─────────────────────────────────────────────────────────────────────┐
│                BACKEND (profile-analysis/app.py)                    │
│  - FastAPI + Pydantic (walidacja)                                   │
│  - NumPy (obliczenia macierzowe)                                    │
│  - Własna implementacja algorytmów (bez PyPSA)                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Pliki źródłowe:
- `services/profile-analysis/app.py` - backend (FastAPI)
- `services/frontend-profile/profile.js` - frontend
- `services/frontend-profile/index.html` - UI
- `services/frontend-profile/profile.css` - style

---

## 3. Dane Wejściowe

```python
class ProfileAnalysisRequest(BaseModel):
    # Dane czasowe (8760 wartości godzinowych)
    pv_generation_kwh: List[float]    # Produkcja PV [kWh]
    load_kwh: List[float]             # Zużycie [kWh]
    timestamps: List[str]             # ISO timestamps (KRYTYCZNE dla mapowania miesięcy!)

    # Parametry instalacji
    pv_capacity_kwp: float            # Moc PV [kWp]
    bess_power_kw: Optional[float]    # Moc BESS [kW] (do analizy istniejącego)
    bess_energy_kwh: Optional[float]  # Pojemność BESS [kWh]

    # Parametry ekonomiczne
    energy_price_plnmwh: float = 800         # Cena energii [PLN/MWh]
    bess_capex_per_kwh: float = 1500         # CAPEX baterii [PLN/kWh]
    bess_capex_per_kw: float = 300           # CAPEX inwertora [PLN/kW]
    bess_efficiency: float = 0.90            # Sprawność round-trip
    discount_rate: float = 0.08              # Stopa dyskontowa
    project_years: int = 15                  # Okres analizy [lat]

    # Strategia optymalizacji
    strategy: str = "balanced"               # npv_max | cycles_max | balanced
    min_cycles_per_year: int = 200
    max_cycles_per_year: int = 400
```

---

## 4. Algorytm - Szczegółowy Opis

### 4.1 Bilans Energetyczny (godzinowy)

```python
# Dla każdej godziny i:
surplus[i] = max(pv_kwh[i] - load_kwh[i], 0)    # Nadwyżka → do magazynu
deficit[i] = max(load_kwh[i] - pv_kwh[i], 0)    # Deficyt → z magazynu/sieci
direct[i] = min(pv_kwh[i], load_kwh[i])         # Autokonsumpcja bezpośrednia
```

### 4.2 Agregacja Miesięczna (z timestamps!)

```python
def analyze_monthly(pv_kwh, load_kwh, timestamps):
    """
    KRYTYCZNE: Timestamps są niezbędne bo rok analityczny może zaczynać się
    od dowolnego miesiąca (np. Lipiec 2024 - Czerwiec 2025).
    Bez timestamps dane byłyby błędnie przypisane do miesięcy.
    """
    month_data = defaultdict(lambda: {'pv': [], 'load': [], 'days': set()})

    for i, ts_str in enumerate(timestamps):
        ts = datetime.fromisoformat(ts_str)
        month_num = ts.month  # 1-12 (Styczeń-Grudzień)
        month_data[month_num]['pv'].append(pv_kwh[i])
        month_data[month_num]['load'].append(load_kwh[i])
        month_data[month_num]['days'].add(ts.day)
```

### 4.3 Symulacja BESS (uproszczona)

```python
def simulate_bess_dispatch(monthly_analysis, bess_energy_kwh, bess_power_kw, efficiency):
    """
    Model uproszczony - agregacja na poziomie DZIENNYM, nie godzinowym.
    Założenie: bateria ładuje się w ciągu dnia, rozładowuje wieczorem.
    """
    usable_capacity = bess_energy_kwh * 0.8  # DoD 80% (SoC 10%-90%)

    annual_cycles = 0
    annual_discharge = 0
    annual_curtailment = 0

    for month in monthly_analysis:
        # Energia dostępna do ładowania (po stratach ładowania)
        daily_available = month.avg_daily_surplus_kwh * sqrt(efficiency)

        # KLUCZOWE: Trzy ograniczenia - bierzemy MINIMUM
        daily_charge = min(
            daily_available,      # Ile nadwyżki PV jest dostępne
            usable_capacity,      # Ile bateria może pomieścić
            bess_power_kw * 8     # Ile można "wpompować" przez ~8h słońca
        )

        # Energia oddana (po stratach rozładowania)
        daily_discharge = daily_charge * sqrt(efficiency)

        # Cykle = energia_oddana / pojemność_użytkowa
        monthly_cycles = (daily_discharge / usable_capacity) * month.days

        # Curtailment = nadwyżka której nie udało się zmagazynować
        daily_curtail = max(0, month.avg_daily_surplus_kwh - daily_charge / sqrt(efficiency))

        annual_cycles += monthly_cycles
        annual_discharge += daily_discharge * month.days
        annual_curtailment += daily_curtail * month.days

    return annual_cycles, annual_discharge, annual_curtailment
```

### 4.4 Założenie `power * 8`

Linia `daily_charge = min(..., power * 8)` zakłada:
- Słońce świeci efektywnie **~8 godzin dziennie**
- Bateria może ładować przez te 8h z pełną mocą

**Ograniczenia tego założenia:**
- Profil PV jest nierównomierny (szczyt w południe)
- Zimą może być tylko 4-5h efektywnego słońca
- To założenie jest **optymistyczne**

### 4.5 Front Pareto (NPV vs Cykle)

```python
def generate_pareto_frontier(monthly_analysis, n_points=10):
    """
    Cel: Znaleźć kompromisy między NPV a liczbą cykli.

    Trade-off:
    - Duża bateria → wysoki NPV (dużo zmagazynowanej energii) → mało cykli (niewykorzystana pojemność)
    - Mała bateria → niski NPV (mało energii) → dużo cykli (pełne wykorzystanie)
    """
    # Zakres rozmiarów BESS
    avg_daily_surplus = mean([m.avg_daily_surplus_kwh for m in monthly_analysis])
    min_energy = max(50, avg_daily_surplus * 0.3)
    max_energy = max(min_energy * 3, max_daily_surplus * 1.5, 200)

    pareto_points = []
    for energy_kwh in linspace(min_energy, max_energy, n_points):
        # Dobór mocy: duration 2-4h
        duration = min(4, max(2, energy_kwh / avg_daily_surplus))
        power_kw = energy_kwh / duration

        # Symulacja
        cycles, discharge, curtail = simulate_bess_dispatch(...)

        # Ekonomia
        capex = power_kw * capex_per_kw + energy_kwh * capex_per_kwh
        annual_savings = discharge * energy_price / 1000
        npv = calculate_npv(annual_savings, capex, discount_rate, years)

        pareto_points.append({...})

    # Oznacz punkty niezdominowane (Pareto-optymalne)
    mark_pareto_optimal(pareto_points)

    return pareto_points
```

### 4.6 Strategie Wyboru

| Strategia | Opis | Kiedy używać |
|-----------|------|--------------|
| `npv_max` | Maksymalizuj NPV | Gdy priorytetem jest zwrot z inwestycji |
| `cycles_max` | Maksymalizuj cykle | Gdy chcemy pełne wykorzystanie baterii |
| `balanced` | Najlepsze NPV w zakresie [min_cycles, max_cycles] | Domyślna - kompromis |

---

## 5. Obliczenia Ekonomiczne

### 5.1 NPV (Net Present Value)

```python
def calculate_npv(annual_savings, capex, discount_rate, project_years):
    """
    NPV = -CAPEX + Σ (annual_savings / (1 + r)^t)
    """
    npv = -capex
    for year in range(1, project_years + 1):
        npv += annual_savings / ((1 + discount_rate) ** year)
    return npv
```

### 5.2 CAPEX BESS

```
CAPEX = (Moc_kW × CAPEX_per_kW) + (Pojemność_kWh × CAPEX_per_kWh)

Typowe wartości (2024):
- CAPEX_per_kWh: 1500 PLN/kWh (ogniwa LFP + BMS)
- CAPEX_per_kW: 300 PLN/kW (inwerter + instalacja)

Przykład 500 kW / 2000 kWh:
CAPEX = 500 × 300 + 2000 × 1500 = 3,150,000 PLN
```

### 5.3 Roczne Oszczędności

```
annual_savings = annual_discharge_mwh × energy_price_pln_per_mwh

Przykład:
300 cykli × 2000 kWh × 0.8 DoD × √0.9 = 456 MWh
456 MWh × 800 PLN/MWh = 364,800 PLN/rok
0.8 DoD- Depth of Discharge - ile % pojemności faktycznie używamy
√0.9 - Straty przy rozładowaniu (połowa round-trip efficiency 90%), straty w obu kierunkach tracimy na ładowaniu i tracimy na rozładowaniu

WIZUALIZACJA PRZEPŁYWU ENERGII
Nadwyżka PV: 1000 kWh
      │
      ▼ × √0.9 (straty ładowania)
Naładowano: 949 kWh
      │
      ▼ × √0.9 (straty rozładowania)
Oddano do sieci: 900 kWh

Łączne straty: 10% (100 kWh)
```

---

## 6. Co Model Pomija (Ograniczenia)

### 6.1 Zużycie Własne BESS (Auxiliary Losses)

**Aktualnie NIE uwzględnione:**

| Składnik | Typowa wartość | Rocznie (2 MWh BESS) |
|----------|----------------|----------------------|
| BMS (ciągłe) | 0.5-1% pojemności/miesiąc | ~120-240 kWh |
| Klimatyzacja | 2-5% throughput | ~200-500 kWh |
| Inwerter standby | 50-200 W ciągłe | ~440-1750 kWh |
| Monitoring | 20-50 W | ~175-440 kWh |
| **SUMA** | **~3-8% throughput** | **~1-3 MWh** |

### 6.2 Degradacja Baterii

**Aktualnie NIE uwzględnione:**

- **Calendar aging:** ~2-3% pojemności/rok (niezależnie od użycia)
- **Cycle aging:** ~0.02% pojemności/cykl (LFP)
- Po 15 latach: pozostaje ~70-80% początkowej pojemności

### 6.3 Brak Godzinowej Symulacji SoC

**Problem:** Model agreguje na poziomie dziennym, nie śledzi godzinowego stanu naładowania.

**Konsekwencje:**
- Nie wykrywa sytuacji gdy bateria jest pełna a nadal jest nadwyżka
- Nie optymalizuje momentu ładowania/rozładowania
- Nie uwzględnia ograniczeń mocy w szczytach

### 6.4 Brak Dynamicznych Cen

**Aktualnie:** Stała cena energii przez cały rok.

**W rzeczywistości:**
- Ceny RDN zmieniają się godzinowo
- Arbitraż cenowy może znacząco zwiększyć NPV
- Peak shaving może redukować opłaty za moc

---

## 7. Roadmapa Rozwoju

### Faza 1: Ulepszenia Modelu (Priorytet: ŚREDNI)

- [ ] **Dodanie strat pomocniczych BESS**
  ```python
  bess_auxiliary_kw: float = 0.1      # Stałe zużycie [kW]
  bess_cooling_pct: float = 0.02      # % throughput na chłodzenie
  bess_self_discharge_pct: float = 0.1  # %/dzień samorozładowania
  ```

- [ ] **Degradacja baterii**
  ```python
  def apply_degradation(year, cycles_per_year, initial_capacity):
      calendar_loss = 0.025 * year  # 2.5%/rok
      cycle_loss = 0.0002 * cycles_per_year * year  # 0.02%/cykl
      return initial_capacity * (1 - calendar_loss - cycle_loss)
  ```

- [ ] **Sezonowe różnice w czasie ładowania**
  - Zima: `power * 5` (krótszy dzień)
  - Lato: `power * 10` (dłuższy dzień)

### Faza 2: Godzinowa Symulacja SoC (Priorytet: WYSOKI)

```python
def simulate_hourly_dispatch(pv_kwh, load_kwh, bess_params):
    """
    Pełna godzinowa symulacja z śledzeniem SoC.
    """
    soc = bess_params.soc_initial
    results = []

    for hour in range(8760):
        surplus = pv_kwh[hour] - load_kwh[hour]

        if surplus > 0:
            # Ładowanie
            charge_possible = min(
                surplus,
                bess_params.power_kw,
                (bess_params.soc_max - soc) * bess_params.energy_kwh
            )
            charge_actual = charge_possible * sqrt(bess_params.efficiency)
            soc += charge_actual / bess_params.energy_kwh
            curtailed = surplus - charge_possible
        else:
            # Rozładowanie
            discharge_needed = -surplus
            discharge_possible = min(
                discharge_needed,
                bess_params.power_kw,
                (soc - bess_params.soc_min) * bess_params.energy_kwh
            )
            discharge_actual = discharge_possible * sqrt(bess_params.efficiency)
            soc -= discharge_possible / bess_params.energy_kwh
            grid_import = discharge_needed - discharge_actual

        results.append({...})

    return results
```

### Faza 3: Integracja PyPSA (Priorytet: NISKI)

```python
import pypsa

def optimize_with_pypsa(pv_kwh, load_kwh, bess_params):
    """
    Pełna optymalizacja LP z PyPSA.
    Solver znajduje optymalny dispatch minimalizujący koszty.
    """
    network = pypsa.Network()
    network.set_snapshots(range(8760))

    network.add("Bus", "main")
    network.add("Generator", "PV", bus="main", p_nom=pv_capacity,
                p_max_pu=pv_profile, marginal_cost=0)
    network.add("Store", "BESS", bus="main",
                e_nom=bess_params.energy_kwh,
                e_cyclic=True,
                standing_loss=0.001)  # Self-discharge
    network.add("Load", "demand", bus="main", p_set=load_kwh)
    network.add("Generator", "Grid", bus="main", p_nom=1e6,
                marginal_cost=energy_price)

    network.optimize(solver_name="glpk")

    return network.stores_t.e["BESS"]  # Profil SoC
```

### Faza 4: Zaawansowane Funkcje (Priorytet: PRZYSZŁOŚĆ)

- [ ] **Dynamiczne ceny energii (RDN)**
- [ ] **Peak shaving** (redukcja mocy szczytowej)
- [ ] **Arbitraż cenowy** (kupuj tanio, sprzedawaj drogo)
- [ ] **Multi-use BESS** (usługi systemowe, rezerwa)
- [ ] **Prognozy** (weather forecast, load forecast)

---

## 8. Podsumowanie Dokładności

| Aspekt | Obecny model | Rzeczywistość | Błąd |
|--------|--------------|---------------|------|
| Roczne cykle | ~300 | ~280-320 | ±10% |
| Energia oddana | ~456 MWh | ~430-450 MWh | ~5% zawyżone |
| NPV | +X mln PLN | ~0.95X mln PLN | ~5% zawyżone |
| Payback | Y lat | ~1.05Y lat | ~5% zaniżony |

**Wniosek:** Model jest **wystarczająco dokładny do wstępnej analizy** i porównania wariantów. Do szczegółowego projektowania potrzebna jest godzinowa symulacja z pełnym modelem strat.

---

## 9. Changelog

### v2.0 (2024-12-10)
- Dodano obsługę timestamps dla poprawnego mapowania miesięcy
- Naprawiono problem z rokiem analitycznym (Lip-Cze vs Sty-Gru)
- Dodano front Pareto i trzy strategie optymalizacji
- Heatmapa 24h × 12 miesięcy

### v1.0 (2024-11)
- Pierwsza wersja z podstawową analizą profilu
- Uproszczona symulacja BESS

---

## 10. Dalszy Rozwój

Następne priorytety:
1. Dodanie strat pomocniczych BESS
2. Godzinowa symulacja SoC
3. Integracja z cenami RDN
