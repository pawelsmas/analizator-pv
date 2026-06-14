# PLAN: Integracja K-class (opłata mocowa) PV + BESS → EKONOMIA

**Data:** 2026-03-08
**Autor:** Claude + Paweł
**Status:** DO REVIEW przez Agent #2

---

## 1. OPIS PROBLEMU

### 1.1 Obecny stan — trzy oddzielne kalkulatory K-class

| Komponent | Plik | Co liczy | Wie o BESS? | Używany przez EKONOMIA NPV? |
|---|---|---|---|---|
| `profile-analysis` | `services/profile-analysis/app.py:2510` `calculate_capacity_fee()` | K-class z profilu godzinowego (load ± PV) | ❌ NIE | ❌ Tylko widget TCSL |
| `bess-dispatch` | `services/bess-dispatch/capacity_fee_pl/calculator.py` | K-class before/after BESS | ✅ TAK | ❌ Tylko `savings_breakdown` |
| `frontend-economics` | `services/frontend-economics/economics.js:1608` `calculateCapacityFeeForConsumption()` | **FLAT RATE** `params.capacity_fee` (domyślnie 219 PLN/MWh) | ❌ NIE | ✅ TAK — to jest problem! |

### 1.2 Konsekwencje

**NPV/IRR/Payback w module EKONOMIA jest BŁĘDNY**, ponieważ:

1. **Oszczędności PV są zawyżone** — zakładamy że każda kWh autokonsumpcji oszczędza pełne 219 PLN/MWh opłaty mocowej, ale klient może być w K1 (współczynnik 0.17) i płacić tylko 37 PLN/MWh zamiast 219.

2. **Efekt BESS na K-class jest niewidoczny** — BESS ładujący się z sieci w godzinach wybranych (7-22) pogarsza Δs (podnosi zużycie dzienne), a rozładowujący się w tych godzinach obniża Δs. Ten efekt nie wpływa na cashflow NPV.

3. **Brak rozróżnienia scenariuszy BESS** — tryb `pv_surplus` vs `stacked` vs `load_only` generuje kompletnie inne profile charge/discharge → inne wpływy na K-class.

### 1.3 Skala błędu (szacunek)

Typowy klient prosument biznesowy (C2x):
- Zużycie roczne: 500 MWh
- Opłata mocowa baseline (K4, pełna stawka): ~500 × 219 = **109 500 PLN/rok**
- Z PV (K2, współczynnik 0.50): ~350 × 219 × 0.50 = **38 325 PLN/rok**
- Różnica: **71 175 PLN/rok** oszczędności na K-class

Ale EKONOMIA liczy: 150 MWh autokonsumpcji × 219 = 32 850 PLN (brak K-class adjustmentu!)

**Błąd może sięgać 30-50% w NPV** dla klientów z dobrą klasą K.

---

## 2. ARCHITEKTURA ROZWIĄZANIA

### 2.1 Zasada: Jeden kalkulator, N scenariuszy

Używamy **jednego kalkulatora K-class** (`profile-analysis/calculate_capacity_fee()`) wywoływanego dla każdego scenariusza z odpowiednim profilem `grid_import[8760]`.

### 2.2 Scenariusze do obliczenia

Dla każdego wariantu PV (np. 70%, 80%, 90% autokonsumpcji):

| # | Scenariusz | Profil grid_import[h] | Cel |
|---|---|---|---|
| S0 | **Baseline** (bez niczego) | `load[h]` | Obecny koszt klienta |
| S1 | **PV only** | `max(0, load[h] - pv[h])` | Koszt z samym PV |
| S2a | **PV + BESS surplus** | `max(0, load[h] - pv[h] - discharge_surplus[h] + charge_from_grid_surplus[h])` | Koszt z PV + BESS tryb surplus |
| S2b | **PV + BESS stacked** | `max(0, load[h] - pv[h] - discharge_stacked[h] + charge_from_grid_stacked[h])` | Koszt z PV + BESS tryb stacked |
| S2c | **BESS load_only** | `max(0, load[h] - discharge_load[h] + charge_from_grid_load[h])` | Koszt z BESS bez PV |

**UWAGA**: W profilu BESS liczymy tylko `charge_from_grid` (ładowanie z sieci), NIE `charge_from_pv` — bo ładowanie z PV nie zwiększa importu z sieci.

### 2.3 Wynik per scenariusz

```python
{
    "scenario": "pv_bess_stacked",
    "capacity_fee_annual_pln": 45230.0,   # Roczny koszt opłaty mocowej
    "k_class": "K2",                       # Dominująca klasa K
    "k_coefficient": 0.50,                 # Efektywny współczynnik
    "delta_s_avg": 5.2,                    # Średnie Δs [%]
    "total_zs_mwh": 280.5,                # Energia w godzinach wybranych [MWh]
    "monthly_fees": [3800, 3500, ...]      # 12 wartości miesięcznych
}
```

### 2.4 Oszczędności per-komponentowe

```
Oszczędność PV na opłacie mocowej      = fee(S0) - fee(S1)
Oszczędność BESS na opłacie mocowej     = fee(S1) - fee(S2x)
Łączna oszczędność na opłacie mocowej   = fee(S0) - fee(S2x)
```

---

## 3. PLAN IMPLEMENTACJI — KROK PO KROKU

### KROK 1: Endpoint w `profile-analysis` do multi-scenariuszowego K-class
**Plik:** `services/profile-analysis/app.py`
**Zmiana:** Nowy endpoint `POST /compute-capacity-fee-scenarios`

```python
@app.post("/compute-capacity-fee-scenarios")
async def compute_capacity_fee_scenarios(request: CapacityFeeScenariosRequest):
    """
    Oblicz opłatę mocową (K-class) dla wielu scenariuszy grid_import.

    Input:
        - load_kwh[8760]: profil zużycia
        - pv_kwh[8760]: profil produkcji PV (opcjonalny)
        - bess_charge_from_grid_kwh[8760]: ładowanie BESS z sieci (opcjonalny)
        - bess_discharge_kwh[8760]: rozładowanie BESS (opcjonalny)
        - som_rate_pln_kwh: stawka SOM
        - selected_hours: {start: 7, end: 22}
        - start_year / data_start_date

    Output:
        - baseline: {fee, k_class, k_coeff, delta_s, monthly}
        - with_pv: {fee, k_class, k_coeff, delta_s, monthly}
        - with_pv_bess: {fee, k_class, k_coeff, delta_s, monthly}
        - savings_pv_only_pln: fee(baseline) - fee(with_pv)
        - savings_pv_bess_pln: fee(baseline) - fee(with_pv_bess)
        - savings_bess_incremental_pln: fee(with_pv) - fee(with_pv_bess)
    """
```

**Logika:**
1. `grid_baseline[h] = load[h]`
2. `grid_pv[h] = max(0, load[h] - pv[h])`
3. `grid_pv_bess[h] = max(0, load[h] - pv[h] - discharge[h] + charge_from_grid[h])`
4. Wywołaj istniejący `calculate_capacity_fee()` 3× z różnymi profilami
5. Oblicz delty (oszczędności)

**Dlaczego nowy endpoint a nie modyfikacja /compute-tcsl:**
- `/compute-tcsl` liczy pełny TCSL (energia + opłaty + opłata mocowa + stałe). Nie chcemy go komplikować o BESS.
- Nowy endpoint jest lekki, fokusowany na K-class, łatwy do testowania i reusable.

### KROK 2: `pv-calculation` wysyła profile BESS do nowego endpointu
**Plik:** `services/pv-calculation/app.py`
**Zmiana:** Po wywołaniu `bess-dispatch /sizing`, wywołaj `profile-analysis /compute-capacity-fee-scenarios`

**Skąd wziąć `charge_from_grid[h]` i `discharge[h]`?**

Obecnie `bess-dispatch /sizing` zwraca w `dispatch_summary`:
- `total_charge_kwh`, `total_discharge_kwh` — sumy roczne
- **NIE zwraca profili godzinowych** charge/discharge

**WYMAGANA ZMIANA w `bess-dispatch`:** Dodać do response opcjonalnie:
```python
"hourly_profiles": {
    "charge_from_grid_kw": [...8760...],
    "discharge_kw": [...8760...]
}
```

To jest kluczowe — bez profili godzinowych nie policzymy K-class per dzień.

**Plik:** `services/bess-dispatch/sizing_runner.py`
- W `run_sizing_for_variant()` (~linia 1323) dispatch LP solver już produkuje `charge_kw` i `discharge_kw` tablice numpy.
- Potrzeba: rozdzielić `charge_kw` na `charge_from_pv` i `charge_from_grid` (już jest ta logika ~linia 1460).
- Dodać te profile do response (opcjonalnie, sterowane flagą `include_hourly_profiles=True`).

**Plik:** `services/bess-dispatch/models.py`
- Dodać `include_hourly_profiles: bool = False` do `SizingRequest`
- Dodać opcjonalne pole w response wariantu: `hourly_charge_from_grid_kw`, `hourly_discharge_kw`

**Plik:** `services/pv-calculation/app.py`
- W `call_bess_dispatch_sizing()`: dodać `include_hourly_profiles: True` do payload
- Po otrzymaniu odpowiedzi: wywołać `profile-analysis /compute-capacity-fee-scenarios`
- Dołączyć wynik K-class do `VariantResult`

### KROK 3: Rozszerzyć model `VariantResult` w `pv-calculation`
**Plik:** `services/pv-calculation/app.py`

Dodać do `VariantResult`:
```python
# Capacity fee (K-class) per scenariusz
capacity_fee_baseline_pln: float = 0       # S0: bez niczego
capacity_fee_with_pv_pln: float = 0        # S1: z PV
capacity_fee_with_pv_bess_pln: float = 0   # S2: z PV + BESS
k_class_baseline: str = "K4"
k_class_with_pv: str = "K4"
k_class_with_pv_bess: str = "K4"
capacity_fee_savings_pv_pln: float = 0     # S0 - S1
capacity_fee_savings_bess_pln: float = 0   # S1 - S2
capacity_fee_savings_total_pln: float = 0  # S0 - S2
```

### KROK 4: Frontend EKONOMIA — użyć rzeczywistych danych K-class
**Plik:** `services/frontend-economics/economics.js`

**Zmiana A:** Odbiór danych K-class z `pv-calculation`

W miejscu gdzie frontend odbiera `analysisResults.key_variants[X]`:
```javascript
// Nowe pola z pv-calculation
const capacityFeeBaseline = variant.capacity_fee_baseline_pln || 0;
const capacityFeeWithPV = variant.capacity_fee_with_pv_pln || 0;
const capacityFeeWithPVBess = variant.capacity_fee_with_pv_bess_pln || 0;
```

**Zmiana B:** NPV cashflow — rozdzielić savings na 2 strumienie

Obecnie (linia 3356):
```javascript
// OBECNE — BŁĘDNE: wszystko × flat capacity_fee
yearSavings = yearSelfConsumedMwh * adjustedEnergyPrice;
```

Nowe podejście:
```javascript
// Strumień 1: Oszczędności energetyczne (autokonsumpcja × cena energii BEZ opłaty mocowej)
const energyPriceWithoutCapacity = totalEnergyPrice - params.capacity_fee;
const yearEnergySavings = yearSelfConsumedMwh * energyPriceWithoutCapacity * savingsCpiEscalation;

// Strumień 2: Oszczędności na opłacie mocowej (z K-class, osobna eskalacja)
const yearCapacityFeeSavings = capacityFeeSavingsTotal * capacityCpiEscalation * pvDegradation;
// (capacityCpiEscalation może być inna niż energetyczna — SOM rate rośnie per URE)

// BESS strumień 3: Dodatkowe oszczędności BESS
const yearBessCapacityFeeSavings = capacityFeeSavingsBess * capacityCpiEscalation * bessDegradation;

yearSavings = yearEnergySavings + yearCapacityFeeSavings + yearBessCapacityFeeSavings;
```

**UWAGA:** To jest miejsce krytyczne. Degradacja PV wpływa na energię (mniej autokonsumpcji), ale K-class zależy od profilu — przy degradacji PV profil się zmienia i K-class może się pogorszyć. Na tym etapie zakładamy liniową degradację oszczędności K-class proporcjonalnie do degradacji PV. Jest to przybliżenie, ale akceptowalne.

**Zmiana C:** BESS savings w NPV

Dodać strumień BESS savings z `savings_breakdown`:
```javascript
// Z bess-dispatch savings_breakdown
const bessEnergySavings = variant.savings_breakdown?.energy_savings_pln || 0;
const bessArbitrageSavings = variant.savings_breakdown?.arbitrage_savings_pln || 0;
const bessPeakShavingSavings = variant.savings_breakdown?.demand_charge_savings_pln || 0;
const bessCapacityFeeSavings = variant.capacity_fee_savings_bess_pln || 0;
// Degradacja z SoH (calendar + cycle)
const bessYearSavings = (bessEnergySavings + bessArbitrageSavings + bessPeakShavingSavings)
                        * bessDegradation * savingsCpiEscalation;
const bessYearCapacitySavings = bessCapacityFeeSavings * bessDegradation * capacityCpiEscalation;
```

**Zmiana D:** Walidacja — EKONOMIA blokuje się bez danych K-class

```javascript
if (!variant.capacity_fee_baseline_pln && variant.capacity_fee_baseline_pln !== 0) {
    showEconomicsWarning("Oczekiwanie na obliczenia K-class z modułu PV. Uruchom analizę PV.");
    return; // Nie licz NPV z fałszywymi danymi
}
```

### KROK 5: Widget TCSL — aktualizacja o scenariusz BESS
**Plik:** `services/frontend-economics/economics.js` (sekcja TCSL)
**Plik:** `services/frontend-economics/index.html` (HTML widgetu)

Dodać trzecią kolumnę w widgecie TCSL:

| | Bez PV | Z PV | Z PV + BESS |
|---|---|---|---|
| Energia | X PLN | Y PLN | Z PLN |
| Opł. mocowa (K-class) | K4: 109k | K2: 38k | K1: 18k |
| Opł. stałe | 6k | 6k | 6k |
| **TCSL** | **120k** | **52k** | **32k** |

### KROK 6: Aktualizacja widgetów BESS
**Plik:** `services/frontend-bess/bess.js`

W kartach wariantów S/M/L — pokazywać K-class:
- `Opłata mocowa PL: 87 051 PLN` → `Opłata mocowa PL: 87 051 PLN (K2 → K1)`
- Zmiana klasy K jest istotną informacją dla klienta

---

## 4. DANE FLOW — NOWY

```
Frontend → pv-calculation /analyze
              │
              ├── [per wariant PV] → bess-dispatch /sizing
              │     │                  (include_hourly_profiles=True)
              │     │
              │     └── Response: savings_breakdown + hourly_profiles
              │           ├── charge_from_grid_kw[8760]
              │           └── discharge_kw[8760]
              │
              ├── [per wariant PV] → profile-analysis /compute-capacity-fee-scenarios
              │     │
              │     │  Input: load[8760], pv[8760], bess_charge_from_grid[8760], bess_discharge[8760]
              │     │
              │     └── Response: 3 scenariusze K-class (baseline, PV, PV+BESS)
              │           ├── capacity_fee per scenariusz
              │           ├── k_class per scenariusz
              │           └── savings (delty)
              │
              └── VariantResult (do frontendu)
                    ├── PV dane (jak dotąd)
                    ├── BESS dane (jak dotąd) + savings_breakdown
                    ├── K-class dane (NOWE):
                    │   ├── capacity_fee_baseline_pln
                    │   ├── capacity_fee_with_pv_pln
                    │   ├── capacity_fee_with_pv_bess_pln
                    │   ├── k_class per scenariusz
                    │   └── savings per komponent
                    └── hourly_grid_import_with_bess[8760] (opcjonalnie)

Frontend EKONOMIA
  ├── Odbiera VariantResult z pv-calculation
  ├── Jeśli brak capacity_fee_baseline_pln → BLOKADA + komunikat
  ├── NPV per-komponentowe:
  │   ├── Strumień 1: Energia (MWh × cena BEZ opłaty mocowej)
  │   ├── Strumień 2: K-class PV (fee_baseline - fee_pv)
  │   ├── Strumień 3: K-class BESS (fee_pv - fee_pv_bess)
  │   ├── Strumień 4: BESS arbitraż + peak shaving
  │   └── Strumień 5: OPEX (PV + BESS)
  └── Cashflow year-by-year z degradacją per komponent
```

---

## 5. PLIKI DO ZMIANY (KOMPLETNA LISTA)

| # | Plik | Rodzaj zmiany | Ryzyko |
|---|---|---|---|
| 1 | `services/profile-analysis/app.py` | Nowy endpoint `/compute-capacity-fee-scenarios` | NISKIE — reuse istniejącej `calculate_capacity_fee()` |
| 2 | `services/bess-dispatch/models.py` | Dodać `include_hourly_profiles`, pola response | NISKIE |
| 3 | `services/bess-dispatch/sizing_runner.py` | Zwracać hourly profiles w response | ŚREDNIE — trzeba rozdzielić charge_from_grid |
| 4 | `services/pv-calculation/app.py` | Wywołać nowy endpoint, rozszerzyć VariantResult | ŚREDNIE — logika orkiestracji |
| 5 | `services/frontend-economics/economics.js` | NPV per-komponentowe, walidacja, TCSL update | WYSOKIE — core NPV logic |
| 6 | `services/frontend-economics/index.html` | TCSL kolumna BESS, UI warning | NISKIE |
| 7 | `services/frontend-bess/bess.js` | Wyświetlanie K-class w kartach S/M/L | NISKIE |

---

## 6. RYZYKA I EDGE CASES

### 6.1 Performance
- Dodajemy 1 dodatkowy HTTP call per wariant PV (do profile-analysis)
- Profile 8760×float64 ≈ 70KB per profil → akceptowalne
- `calculate_capacity_fee()` iteruje po 365 dniach — szybkie (<10ms)

### 6.2 Brak danych BESS
- Jeśli BESS wyłączony → S2 = S1 (PV only), `bess_charge_from_grid = zeros(8760)`
- Profile-analysis endpoint musi obsługiwać puste/zerowe profile BESS

### 6.3 Zmiana K-class w czasie (degradacja PV)
- W roku 10+ PV produkuje mniej → K-class może się pogorszyć (wrócić do K3/K4)
- **Uproszczenie akceptowalne:** Degradujemy oszczędności K-class proporcjonalnie do PV degradacji
- **Pełne rozwiązanie (przyszłość):** Recalculacja K-class per rok z zdegradowanym profilem PV

### 6.4 BESS charge_from_grid vs charge_from_pv
- LP solver w `sizing_runner.py` (~linia 1460) **już rozdziela** te dwa strumienie:
  ```python
  charge_from_pv_kw = np.minimum(charge_kw, np.maximum(pv_kw - load_kw, 0.0))
  charge_from_grid_kw = np.maximum(charge_kw - charge_from_pv_kw, 0.0)
  ```
- To jest kluczowe — ładowanie z PV nie zwiększa grid_import, ładowanie z sieci tak

### 6.5 Tryb RDN vs Taryfa
- Opłata mocowa (K-class) jest NIEZALEŻNA od tego czy klient jest na taryfie czy RDN
- SOM rate jest ustalany przez URE i obowiązuje wszystkich
- Jedyna różnica: eskalacja SOM w czasie (URE co roku) vs eskalacja cen energii (inflacja/rynek)

### 6.6 Godziny wybrane — zmienne per kwartał
- Q1/Q4: 6:00-22:00, Q2/Q3: 7:00-22:00
- `calculate_capacity_fee()` **obecnie** przyjmuje stały `selected_start/selected_end`
- **TODO (nie w tym PR):** Obsługa zmiennych godzin per kwartał

### 6.7 Backward compatibility
- Stare requesty bez danych BESS → endpoint zwraca S0 + S1 (bez S2)
- Frontend bez nowych pól → fallback na stare zachowanie (flat rate)
- `calculateCapacityFeeForConsumption()` zostawiamy jako fallback

---

## 7. PYTANIA DO REVIEW (Agent #2)

1. **Czy rozdzielenie charge na charge_from_pv i charge_from_grid jest poprawne?**
   Logika: `charge_from_pv = min(charge, max(pv - load, 0))`, reszta = from_grid.
   Czy to poprawnie modeluje fizykę przepływu energii?

2. **Czy degradacja oszczędności K-class proporcjonalna do degradacji PV jest akceptowalnym przybliżeniem?**
   Alternatywa: recalkulacja K-class per rok z zdegradowanym profilem PV (dużo cięższe obliczeniowo).

3. **Czy brakuje jakiegoś scenariusza?**
   Np. co z cable pooling? Co z net-billing gdzie eksport się liczy inaczej?

4. **Czy endpoint w profile-analysis jest właściwym miejscem?**
   Alternatywa: przenieść kalkulator K-class do shared library i wywoływać bezpośrednio w pv-calculation.

5. **Czy 8760-godzinowe profile w response bess-dispatch to nie za dużo danych?**
   Alternatywa: bess-dispatch sam wywołuje profile-analysis i zwraca tylko wynik K-class.

6. **Czy EKONOMIA powinna blokować NPV bez danych K-class, czy lepiej liczyć z ostrzeżeniem?**
   Propozycja: liczyć z flat rate + banner "Obliczenie przybliżone — brak danych K-class".

---

## 8. KOLEJNOŚĆ IMPLEMENTACJI

```
Faza 1 (backend): Krok 1 + Krok 2 (bess-dispatch hourly profiles)
                   → Testowalne niezależnie od frontendu
                   → curl do nowych endpointów

Faza 2 (orkiestracja): Krok 3 (pv-calculation wywołuje oba serwisy)
                        → E2E test: pv-calculation zwraca K-class dane

Faza 3 (frontend): Krok 4 + 5 + 6 (economics + TCSL + bess cards)
                    → Widoczne w UI
```

Szacowany rozmiar: ~500-800 LOC zmian, ~3-4h pracy.
