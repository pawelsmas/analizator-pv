# ANALIZATOR PV — Materiał źródłowy do artykułu

**Cel dokumentu:** Kompletny materiał referencyjny dla agenta redakcyjnego piszącego artykuł na stronę WWW. Opisuje metodologię doboru instalacji PV, analizę ekonomiczną, obsługę magazynów energii oraz rolę poszczególnych modułów portalu.

**Zakres:** Platforma ANALIZATOR PV — zintegrowane narzędzie do analizy techniczno-ekonomicznej instalacji fotowoltaicznych z magazynami energii (BESS).

---

## 1. FILOZOFIA PLATFORMY

ANALIZATOR PV odpowiada na 4 fundamentalne pytania biznesowe klienta:

| Pytanie | Odpowiedź platformy |
|---|---|
| **Jaki rozmiar instalacji PV jest dla mnie optymalny?** | Warianty A/B/C/D z progami autokonsumpcji + wariant Best NPV |
| **Czy ta inwestycja się opłaci?** | NPV, IRR, payback (prosty + dyskontowany), LCOE, analiza wrażliwości, Monte Carlo |
| **Czy warto dodać magazyn energii?** | Sizing BESS S/M/L + LP dispatch + analiza przychodów (arbitraż, opłata mocowa, aFRR) |
| **Jakie ryzyka i efekt ESG?** | Tornado chart, P10/P50/P90, VaR, redukcja CO₂, ekwiwalenty |

Platforma działa na **rzeczywistych danych klienta** (profil zużycia 15-min lub 1h) oraz symulowanej produkcji PV pobieranej z **PVGIS-SARAH3** (European Commission).

---

## 2. MODUŁ ZUŻYCIE — ANALIZA PROFILU KLIENTA

### 2.1 Obsługiwane formaty danych

| Format | Wymagania |
|---|---|
| CSV / Excel (.xlsx) | timestamp (ISO) + wartość mocy lub zużycia |
| Interwały czasowe | 15-min, 30-min, 60-min (auto-detekcja z timestamps) |
| Konwersja | kWh → kW automatycznie: `kW = kWh × (60 / interwał_min)` |

**Backend:** `services/data-analysis/app.py:742-766` — auto-detekcja interwału z mediany różnic timestamp.

### 2.2 Dwutorowe przechowywanie: 15-min + godzinowe

- `data_store.hourly_data` — agregowane do godzin (analizy ekonomiczne, ToU)
- `data_store.quarter_hour_data` — pełna rozdzielczość 15-min (peak shaving, opłata mocowa)

Peak shaving wymaga rozdzielczości 15-min bo **opłata mocowa (SOM)** liczona jest z 15-min interwałów (linia 1087).

### 2.3 Statystyki obliczane z profilu

| Metryka | Znaczenie biznesowe |
|---|---|
| **Peak power** (P100) | Do obliczenia mocy umownej i potencjału peak shaving |
| **Percentyle** (P50/P75/P90/P95/P99) | Rozkład obciążenia → wybór mocy BESS |
| **Load factor** (avg/peak × 100%) | Charakter profilu: >50% = stabilny 24/7, <20% = sezonowy |
| **Coefficient of Variation** (σ/avg) | >30% = niestabilny, <15% = przemysłowy |
| **Annual consumption** | Podstawa doboru PV (zużycie roczne) |
| **Daily/monthly profile** | Wykresy dobowe i miesięczne |

### 2.4 Analiza sezonowości — 3 pasma

Klasyfikacja dni na **High/Mid/Low** (`data-analysis/app.py:439-546`):

1. Dzienny P95 mocy
2. Rolling median 7 dni
3. Standaryzacja MAD (Median Absolute Deviation)
4. Klasyfikacja: High (z-score ≥ 0.7), Low (≤ -0.7), Mid
5. Czyszczenie "wysp" — ciągi < 10 dni przypisane do sąsiadów

**Efekt:** Klient widzi kiedy zużywa najwięcej (sezon grzewczy / chłodzenie / production peaks).

### 2.5 Typical Days — dzień reprezentatywny

`services/typical-days/app.py:160-322`:

- **Dzień typowy** — znaleziony przez minimum dystansu euklidesowego do średniego profilu
- **Best/worst day** — najwyższa/najniższa samokonsumpcja
- **Workday vs weekend** — rozróżnienie wg daty (nie indexu)
- **Seasonal patterns** — profile zimowe/wiosenne/letnie/jesienne osobno

### 2.6 Klasa K — opłata mocowa

Kluczowy element rachunku za prąd dla firm. Algorytm (`consumption.js:3244-3406`):

```
Δs = (avg_zużycie_w_godzinach_wybranych / avg_zużycie_poza - 1) × 100%

K1: Δs < 5%   → A = 0.17 (najniższa opłata)
K2: 5%-10%    → A = 0.50
K3: 10%-15%   → A = 0.83
K4: Δs ≥ 15%  → A = 1.00 (najwyższa opłata)

WOM = A × SOM × ZS (opłata mocowa)
```

Godziny "wybrane": 7-22 dni robocze (konfigurowalne per kwartał).

### 2.7 Wykresy dla klienta

- **4 karty KPI** (roczne zużycie, peak, min, średnia dzienna)
- **Średni profil dobowy** (24h)
- **Profil tygodniowy** (7 dni)
- **Profil miesięczny** (12 miesięcy)
- **Load Duration Curve** (rozkład od max do min)
- **Sezonowość** — 3 pasma z tabelą miesięczną
- **Heatmapa 24h × 12 miesięcy** (z profile-analysis)

### 2.8 Wartość dla klienta

Moduł pozwala:
1. **Poznać własny profil** — kiedy, ile, dlaczego zużywa
2. **Zoptymalizować taryfę** — porównanie kosztów w C11/C12a/C22a/C22b/RDN
3. **Zidentyfikować potencjał BESS** — peak shaving + redukcja klasy K
4. **Podjąć decyzję inwestycyjną** — wiarygodne dane wejściowe do PV/BESS

### 2.9 Ograniczenia

- Minimalna długość: 24h
- Obsługa luk: detekcja >3h, imputacja średnią sezonową (`data-analysis/app.py:1452-1546`)
- Rok analityczny: dowolne 365/366 kolejnych dni

---

## 3. MODUŁ PV — DOBÓR WIELKOŚCI INSTALACJI

### 3.1 Cztery warianty A/B/C/D

Algorytm `find_variant()` (`pv-calculation/app.py:2580`) szuka **największej instalacji** spełniającej zadany próg autokonsumpcji:

| Wariant | Próg autokonsumpcji | Interpretacja biznesowa |
|---|---|---|
| **A** | 90-95% | Bardzo wysoka autokonsumpcja → minimalny eksport, najszybszy payback |
| **B** | 85% | Wyważona → kompromis wielkości i zwrotu |
| **C** | 80% | Większa instalacja → więcej eksportu |
| **D** | 75% | Maksymalna wielkość → akceptujemy eksport za większą redukcję rachunku |

### 3.2 Wariant Best NPV

Endpoint `/optimize-seasonality` (`app.py:1472`) szuka **maksymalnego NPV** z ograniczeniem autokonsumpcji w zakresie **65-95%**.

- Sweep po mocach PV (grid search)
- Dla każdej mocy: `simulate_pv_with_seasonal_bands()` — symulacja per-slot z uwzględnieniem sezonowości
- Kryterium: MAX_NPV lub MAX_AUTOCONSUMPTION
- Wynik: rekomendacja z największym zwrotem inwestycji

**Przykład z logów** (client 1.89 GWh):
```
Found best NPV within 65-95% autoconsumption: 400 kWp, 94.3%, NPV: 0.05 mln PLN
Sample scenarios:
  1000 kWp: prod=980 MWh, auto=69.4%
  5000 kWp: prod=4900 MWh, auto=20.3%
  16000 kWp: prod=15676 MWh, auto=6.8%
```

### 3.3 Źródło danych produkcji — PVGIS

`services/pvgis-proxy/main.py:43` — proxy do **PVGIS-SARAH3** (2005-2023, Polska):

**Dwie metody:**

1. **PVcalc** (szybka, uncertainty method):
   - Zwraca E_y (kWh/rok) + sigma (zmienność)
   - Scenariusze: P90 = 1.0 - Z_90 × σ_total_rel
   - Z_P75 = 0.6745, Z_P90 = 1.2816

2. **Seriescalc** (dokładna, timeseries):
   - Rzeczywiste 19 lat danych godzinowych
   - P50 = mediana, P75 = 25-percentyl, P90 = 10-percentyl
   - Wolniejsza, ale **bankable** (dane historyczne)

**Model PV:** crystSi2025 (LID + degradacja roczna już w profilu).

### 3.4 Parametry techniczne

| Parametr | Zakres | Źródło |
|---|---|---|
| Azymut (aspect) | 0°=S, -90°=E, 90°=W | `app.py:62` |
| Nachylenie (angle) | optimal lub custom | `app.py:61` |
| Temperature coefficient | -0.004 %/°C | `app.py:94` |
| Albedo | 0.2 | `app.py:` |
| Soiling loss | 2% | `app.py:97` |
| DC/AC ratio | 1.1-1.5 | inverter clipping |
| LID + degradacja roczna | ~0.5%/rok | model crystSi2025 |

### 3.5 Parowanie PV vs load — per-slot (15min/1h)

Rdzeń symulacji (`app.py:1736`):

```python
# Slot-wise matching
self_consumed[t] = min(production[t], consumption[t])
exported[t] = max(0, production[t] - consumption[t])
imported[t] = max(0, consumption[t] - production[t])

# Metryki agregowane
auto_consumption_pct = Σ self_consumed / Σ production × 100
coverage_pct = Σ self_consumed / Σ consumption × 100
```

**Kluczowe wnioski:**
- Autokonsumpcja (%) — ile PRODUKCJI PV zużywamy sami (nie eksportujemy)
- Pokrycie (%) — ile ZUŻYCIA pokrywamy PV (niezależność)

Te dwie metryki są **odwrotnie skorelowane**: większa instalacja = niższa autokonsumpcja, ale wyższe pokrycie.

### 3.6 Surplus (nadwyżka) — jak pokazujemy

```
surplus[t] = max(0, production[t] - consumption[t])
exported_mwh = Σ surplus / 1000
```

**Wizualizacja:**
- **Heatmapa nadwyżki** 24h × 365 dni (profile-analysis) — kolory pokazują godzinowe nadwyżki
- **Profile godzinowe** — wykres PV vs Load, nadwyżka = obszar pod PV powyżej Load
- **Duration curve** nadwyżki — rozkład od max do min
- **Miesięczne sumy** — ile MWh nadwyżki w każdym miesiącu

### 3.7 Co zwraca moduł (API Response)

`AnalysisResult` (`app.py:407`):

```json
{
  "scenarios": [...],  // pełna tabela sweep mocy
  "key_variants": {
    "A": { capacity, production, auto_consumption_pct, coverage_pct, ... },
    "B": { ... },
    "C": { ... },
    "D": { ... }
  },
  "npv_optimal": { capacity, npv_pln, ... },
  "bess_summary": { ... }  // jeśli włączony
}
```

### 3.8 Co daje klientowi

1. **4 warianty do wyboru** — każdy z wyjaśnioną logiką
2. **Wariant NPV-optymalny** — sugestia "matematyczna" poza progami
3. **Krzywa kompromisów** — wizualizacja trade-off autokonsumpcja vs NPV
4. **Dane do negocjacji** — P50/P75/P90 scenariusze produkcji

---

## 4. MODUŁ EKONOMIA — ANALIZA INWESTYCYJNA

### 4.1 Kluczowe metryki

| Metryka | Wzór | Interpretacja |
|---|---|---|
| **NPV** | `Σ CF_t / (1+r)^t` | Wartość bieżąca netto — jeśli >0, projekt rentowny |
| **IRR** | hybrid Newton-Raphson + bisection | Wewnętrzna stopa zwrotu — porównaj z kosztem kapitału |
| **Payback prosty** | `CAPEX / avg_annual_savings` | Ile lat do zwrotu (bez dyskonta) |
| **Payback dyskontowany (DPP)** | rok, w którym skumulowane DCF ≥ 0 | Uwzględnia wartość pieniądza w czasie |
| **ROI** | `(NPV + Investment) / Investment × 100%` | Procentowy zwrot |
| **LCOE** | `(Inv + PV(OPEX)) / PV(Produkcja)` | Koszt jednostkowy energii [PLN/MWh] |
| **PI** | `PV(wpływy) / PV(wydatki)` | Profitability Index — >1 rentowny |

### 4.2 Parametry inwestora

```
CAPEX [PLN/kWp]: tiered (3500/3000/2500 wg mocy instalacji)
OPEX [PLN/kWp/rok]: 15 (domyślnie)
Stopa dyskontowa: 10% (konfigurowalna)
Inflacja: 2.5% (NBP target)
Horyzont: 25 lat (standard PV)
Degradacja PV: 0.5%/rok (liniowa)
Wymiana inwertera: rok 12, 15% CAPEX
Wymiana BESS: rok 15, 70% CAPEX (jeśli obecny)
```

### 4.3 Model cashflow — rok po roku

```
Year 0: -CAPEX
Year t (1..N):
  Production_t = Production_base × (1 - degradation)^t × ProductionFactor[P50/P75/P90]
  Savings_t = SelfConsumed_t × Price[PLN/MWh] × (1 + inflation)^t
  OPEX_t = OPEX_base × (1 + inflation)^t
  Replacement_t = wymiana inwertera/BESS jeśli dotyczy
  NCF_t = Savings_t + ExportRev_t - OPEX_t - Replacement_t
  DCF_t = NCF_t / (1 + r)^t
  NPV += DCF_t
```

### 4.4 Cena energii — struktura

**Komponenty all-in** (dla C12a):

```
Energia czynna (EA):          550 PLN/MWh
+ Dystrybucja zmienna:         200 PLN/MWh
+ Opłata jakościowa:            10 PLN/MWh
+ Opłata OZE:                    7 PLN/MWh
+ Opłata kogeneracyjna:         10 PLN/MWh
+ Akcyza:                        5 PLN/MWh
+ Opłata mocowa (SOM):         219 PLN/MWh
────────────────────────────────────────────
RAZEM ~1001 PLN/MWh
```

**Taryfy obsługiwane:**
- **C11** — jednostrefowa (flat)
- **C12a** — z opłatą mocową
- **C22a** — 2-strefowa (dzień/noc)
- **C22b** — 3-strefowa (szczyt/pozaszczyt/noc)
- **RDN** — rynek dnia następnego (ceny godzinowe z PSE)

**ToU (Time-of-Use):** 2-zone, 3-zone, 4-zone — każda z własnymi godzinami i stawkami.

### 4.5 Analiza wrażliwości (Tornado + Macierz)

`/comprehensive-sensitivity` (`app.py:847-998`):

**Tornado chart** — wpływ ±20% zmian na NPV:
- Cena energii (największy wpływ zwykle)
- CAPEX
- Stopa dyskontowa
- Yield PV
- Degradacja
- OPEX

**Macierz 2D NPV** — cena × yield:
- Heatmapa pokazująca NPV dla wszystkich kombinacji
- Użyteczna dla bankierów (worst-case/best-case)

### 4.6 Monte Carlo — analiza ryzyka

`services/economics/monte_carlo/engine.py` + `monte-carlo.js`:

**Zmienne losowe (N=10,000 iteracji):**

| Zmienna | Rozkład | Parametry |
|---|---|---|
| Cena energii | N(μ, σ) | σ = 12% (bankable) |
| Production factor | N(1.0, 0.08), [0.75, 1.25] | P99 protection |
| Investment cost | Lognormalny | σ = 8% (post-EPC) |
| Inflacja | N(2.5%, 1.5pp), [0%, 10%] | NBP target |
| Degradacja | N(0.5%, 30%), [0%, 20%] | |

**Korelacje empiryczne:**
```
Cena energii ↔ Inflacja: r = 0.5 (energia ~15% CPI)
```

**Wyniki:**
- Histogram NPV (50 binów)
- Percentyle: P5, P10, P25, **P50 (mediana)**, P75, **P90**, P95
- **VaR 95%** = P5 (wartość zagrożonego kapitału)
- **CVaR 95%** = średnia poniżej VaR (expected shortfall)
- **Prawdopodobieństwo zysku** (P(NPV > 0))
- Scenariusze P10/P50/P90 (pesymistyczny/bazowy/optymistyczny)

### 4.7 Bankability (DSCR) — dla finansowania bankowego

`bankability.js`:

```
DSCR = CFADS / DebtService
CFADS = Revenue - OPEX - Taxes - Maintenance ± ΔWC
```

**Metryki:**
- **Min DSCR** (worst year) — kluczowy covenant banku (zwykle ≥ 1.20)
- **Weighted Avg DSCR** = Σ CFADS / Σ DebtService
- **Headroom** = (Min DSCR / Covenant) - 1

**Schematy spłaty:**
- Annuity (raty równe)
- Linear (kapitał równy)
- Bullet (odsetki w trakcie, kapitał na koniec)

**Grace period:**
- `interest_only` (spłata tylko odsetek w grace)
- `capitalize` (odsetki dopisują się do kapitału)

### 4.8 ESG — redukcja CO₂

```
EF_grid = 0.658 kgCO₂e/kWh (Polska, KOBiZE 2023)
CO2_reduced = SelfConsumed_kWh × EF_grid
```

**Ekwiwalenty:**
- 1 tCO₂e ≈ 1.3 samochodu/rok
- 1 tCO₂e ≈ 40 drzew/rok
- 1 tCO₂e ≈ 0.4 lotu transatlantyckiego

**Carbon payback:** ~2-3 lata dla PV, ~1 rok dla BESS.

### 4.9 Break-even — minimalna cena energii

```
Regresja liniowa cena ↔ NPV
breakeven = -intercept / slope
```

Odpowiada na pytanie: *"Przy jakiej cenie energii projekt przestaje się opłacać?"*

### 4.10 Eksport do Excela

`capex-export.js` + `bankability.js` generują plik z arkuszami:

1. **Podsumowanie CAPEX** — parametry projektu + KPI
2. **CAPEX Rok po Roku** — cashflow z formułami Excel
3. **Analiza CFO** — tornado, macierz, scenariusze, ESG, break-even
4. **BESS Replacement** (jeśli obecny)
5. **DSCR Analysis** (bankability)
6. **Metodologia** — wyjaśnienia wzorów
7. Arkusze angielskie (CAPEX Summary, CAPEX Year by Year, CFO Analysis)

**Format:** Formuły Excel dla przejrzystości bankierów, wartości obliczone w JS dla złożonej logiki.

---

## 5. MODUŁ BESS — MAGAZYNY ENERGII

### 5.1 Sizing S/M/L

`sizing_runner.py` — grid search po trzech wariantach czasu pracy:

| Wariant | Duration | Charakterystyka |
|---|---|---|
| **Small (S)** | 1h | Szybka amortyzacja, mała pojemność, peak shaving |
| **Medium (M)** | 2h | Balans NPV/pojemność, arbitraż ToU |
| **Large (L)** | 4h | Więcej cykli, time-shift PV + arbitraż |

Dla każdego wariantu:
- Grid search po mocach (20 kroków między p_min a p_max)
- Każda kombinacja: LP dispatch + kalkulacja NPV
- Najwyższy NPV → rekomendacja dla danego czasu

### 5.2 LP Dispatch (Linear Programming, rolling horizon)

`lp_dispatch.py`:

- **Solver:** scipy HiGHS
- **Rolling horizon:** 48h forecast, 24h keep
- **Optymalizacja:** minimalizacja kosztu energii przy ograniczeniach baterii
- **Zmienne:** moc ładowania/rozładowania w każdym slocie
- **Ograniczenia:** SOC ∈ [SOC_min, SOC_max], moc ≤ P_max, grid_connection_kw

### 5.3 Tryby dispatch

| Tryb | Logika | Zastosowanie |
|---|---|---|
| **PV Surplus** | Ładuj tylko z nadwyżki PV, nigdy z sieci | Autokonsumpcja |
| **Peak Shaving** | Rozładuj bateria na szczyty obciążenia | Redukcja klasy K, SOM |
| **Stacked** | PV surplus + arbitraż ToU + peak shaving | Maksymalizacja przychodów |
| **Load Only** | Bez PV, tylko sieć (ładowanie noc, rozładowanie szczyt) | Czysty arbitraż |

### 5.4 Strumienie przychodów BESS

1. **Time-shift PV surplus** — przechwycona nadwyżka PV, rozładowana na wieczór
2. **Arbitraż ToU** — ładowanie w tanich godzinach (noc), rozładowanie w szczycie
3. **Arbitraż RDN** — ceny godzinowe z PSE (wymaga aktywnego rynku)
4. **Opłata mocowa (SOM)** — rozładowanie w godzinach 7-22 zmniejsza WOM
5. **Moc zamówiona** — redukcja peaku zmniejsza opłatę za moc umowną
6. **aFRR** — rezerwa wtórna (automatic frequency restoration reserve, usługa dla PSE)
7. **FCR** — rezerwa pierwotna (frequency containment reserve)

### 5.5 Topologie

- **pv_bess** — PV + Load + BESS (klasyczny)
- **bess_only** — tylko BESS + Load (arbitraż, brak PV)
- **pv_load** — PV + Load bez BESS (baseline)

### 5.6 Scenariusze (presety)

`settings.js` → `BESS_SCENARIOS`:

1. **Arbitraż BESS** — czysty trading (bess_only)
2. **Backup / UPS** — rezerwa dla przerw, wysoka rezerwa SOC
3. **Stacked (PV+Peak+Arb)** — maksymalny wykorzystanie
4. **Full Stack** — wszystko + ancillary services

### 5.7 Cykle i degradacja

```
EFC (Equivalent Full Cycles) = throughput_total_kWh / usable_capacity_kWh
SoH (State of Health) = f(calendar_age, throughput)
EOL (End of Life) = SoH ≤ 70%
```

**Degradacja:**
- **Kalendarzowa:** 2% rok 1, ~1% rocznie potem
- **Cyklowa:** liniowa lub sqrt, cycles_to_eol ∈ [5000, 6000]
- **Kombinowana:** SoH = min(SoH_calendar, SoH_cycle)

### 5.8 Przykładowy wynik (BESS 200 kW / 418 kWh przy PV 1000 kWp)

```
Autokonsumpcja:  64.6% → 66.5% (+1.9 pp)
Nadwyżka PV:     346 MWh → 328 MWh (schowane 17 MWh w BESS)
EFC:             313 cykli/rok
Peak reduction:  -82 kW (szczyt przesunięty na noc z ładowania)

PRZYCHODY ROCZNE:
  Time-shift PV:     16.4 tys PLN
  Arbitraż ToU:      40.0 tys PLN
  Opłata mocowa:     21.8 tys PLN
  aFRR:              18.0 tys PLN
  TOTAL:             96.1 tys PLN

EKONOMIA (CAPEX 350k):
  Payback:           3.9 lat
  NPV (15y/10%):    +257 k PLN
  IRR:               22.3%
```

---

## 6. POZOSTAŁE MODUŁY

### 6.1 Estymator

**Dla kogo:** Klient BEZ danych zużycia (szybka wycena).

**Input:** Moc [kWp], typ montażu, scenariusz P50/P75/P90, ograniczenia (zero-export, clipping).

**Output:** Produkcja roczna, CAPEX, LCOE, NPV.

### 6.2 Porównanie wariantów

Side-by-side **A/B/C/NPV-opt** z wykresami:
- Produkcja miesięczna
- Ekonomika (NPV, payback)
- Profil godzinowy (PV vs Load)
- KPI (capacity, autocons%, coverage%)

### 6.3 Site Assessment

**4-etapowy wizard:**
1. **Lokalizacja** (Nominatim + Leaflet)
2. **Obszar** (polygon/prostokąt, area + perimeter)
3. **Konfiguracja** (tilt, azimuth, GCR, moduł)
4. **Wyniki** (PVGIS: optimal tilt, specific yield, total capacity)

Eksport: CSV/PDF dla inżyniera.

### 6.4 Scoring — wielokryterialna ocena ofert

4 kryteria + wagi:

- **Value** (40%) — NPV/CAPEX, IRR, payback
- **Robustness** (30%) — stabilność, niezawodność
- **Tech** (20%) — sprawność, innowacje
- **ESG** (10%) — CO₂, wpływ lokalny

**Profile wag:** CFO, ESG-first, Operations, Custom.

Wynik: score 0-100 dla każdej oferty.

### 6.5 ESG

- **Ślad węglowy** (EF_grid, embodied carbon panele + BESS)
- **Redukcja roczna** i **lifetime**
- **Carbon payback** (ile lat produkcji zwraca embodied carbon)
- Integracja **Electricity Maps** (live carbon intensity)

### 6.6 Profile Analysis — Pareto frontier BESS

Multi-objective: **NPV vs Cykle**.

- Heatmapa moc [kW] × pojemność [kWh] → NPV
- Pareto frontier (niezdominowane rozwiązania)
- Rekomendacja: best NPV + warianty trade-off

### 6.7 Projekty

**Baza danych:** PostgreSQL.

- Snapshots danych: rawConsumption, pvConfig, analysisResults, settings, economics
- Wersjonowanie
- Audit trail
- Soft-delete (archive)

### 6.8 Reports

**Formaty:** PDF (WeasyPrint) + Excel.

**Sekcje (opt-in):**
- Summary, Consumption profile, PV production, Economics, Scenarios, Heatmaps, BESS analysis, ESG

---

## 7. ARCHITEKTURA TECHNICZNA

```
┌─────────────────────────────────────────────────────────────┐
│              SHELL (frontend-shell, port 80)                │
│  Mikrofrontend host + nginx reverse proxy + sharedData      │
└─────────────────────────────────────────────────────────────┘
     │
     ├── Frontend modules (JavaScript): Consumption, Config,
     │   PV, Economics, BESS, Reports, Site Assessment, ESG,
     │   Scoring, Profile, Projects, Estimator, Comparison
     │
     └── Backend services (Python/FastAPI):
         ├── pv-data-analysis (8001) — profil zużycia
         ├── pv-calculation (8002) — dobór PV + symulacja
         ├── economics (8003) — NPV/IRR/Monte Carlo
         ├── advanced-analytics (8004)
         ├── typical-days (8005)
         ├── energy-prices (8010) — ENTSO-E + RDN
         ├── reports (8011) — PDF/Excel
         ├── projects-db (8012)
         ├── pvgis-proxy (8020) — PVGIS-SARAH3
         ├── geo-service (8021) — Nominatim, elevation
         ├── bess-optimizer (8030) — PyPSA+HiGHS
         ├── bess-dispatch (8031) — LP dispatch + sizing
         ├── profile-analysis (8040) — Pareto BESS
         └── database-api (8050) — PostgreSQL
     │
     ├── PostgreSQL (5432) — projekty, snapshoty
     └── Monitoring: Prometheus (9090), Grafana (3000), Loki (3100)
```

**Stack:**
- Frontend: Vanilla JS + Chart.js + Leaflet + D3.js + ExcelJS
- Backend: Python + FastAPI + NumPy + scipy (HiGHS LP solver) + PyPSA
- Baza: PostgreSQL
- Orkiestracja: Docker Compose (37 kontenerów)

**Integracje zewnętrzne:**
- **PVGIS** (JRC / European Commission) — produkcja PV
- **ENTSO-E** — ceny energii RDN
- **Nominatim (OSM)** — geokodowanie
- **NBP** — kurs EUR/PLN
- **Electricity Maps** — carbon intensity

---

## 8. KLUCZOWE WYRÓŻNIKI (USP) DLA ARTYKUŁU

1. **Dane klienta per-slot (15 min)** — nie estymaty, nie średnie miesięczne
2. **PVGIS-SARAH3 19 lat historii** — P50/P75/P90 z rzeczywistych danych, nie fikcja
3. **LP dispatch BESS** — matematyczny optimum, nie reguły heurystyczne
4. **Monte Carlo 10,000 iteracji** — realna analiza ryzyka dla bankierów
5. **DSCR bankability** — arkusz gotowy do banku (covenant, headroom, schemat spłaty)
6. **Multi-topologia** — PV, PV+BESS, BESS-only (arbitraż) — wszystko w jednym
7. **Klasy K (opłata mocowa)** — pełne polskie realia taryfowe
8. **ESG live** — Electricity Maps integration, nie ryczałt

---

## 9. TYPOWY WORKFLOW KLIENTA (user journey)

1. **Upload profilu zużycia** (CSV/Excel 15-min lub 1h)
2. **Moduł Zużycie** analizuje: peak, średnia, klasa K, sezonowość
3. **Moduł Config** — wybór lokalizacji (Site Assessment), parametrów PV
4. **Dobór PV** — warianty A/B/C/D + Best NPV
5. **Moduł Ekonomia** — NPV, IRR, payback + Monte Carlo + wrażliwość
6. **Opcjonalnie: BESS** — sizing S/M/L + dispatch + przychody
7. **Bankability** (jeśli finansowanie) — DSCR, covenant, schemat spłaty
8. **Raport** — PDF/Excel do klienta/banku
9. **Zapis projektu** do bazy (wersjonowanie)

---

## 10. KLUCZOWE DEFINICJE (glossary)

- **Autokonsumpcja** — % produkcji PV zużytej na miejscu (vs eksport)
- **Pokrycie** — % zużycia pokrytego produkcją PV (vs import)
- **Surplus / Nadwyżka** — produkcja PV przekraczająca bieżące zużycie (idzie do eksportu lub BESS)
- **Peak Shaving** — redukcja szczytowego poboru z sieci
- **ToU (Time of Use)** — taryfa strefowa (dzień/noc lub 3-4 strefy)
- **SOM** — Składnik Opłaty Mocowej (opłata za moc umowną)
- **EFC** — Equivalent Full Cycles (ekwiwalentne pełne cykle baterii)
- **SoH** — State of Health (stan zdrowia baterii, %)
- **EOL** — End of Life (koniec życia, zwykle SoH=70%)
- **aFRR** — Automatic Frequency Restoration Reserve (rezerwa wtórna)
- **DSCR** — Debt Service Coverage Ratio (wskaźnik pokrycia obsługi długu)
- **LCOE** — Levelized Cost of Energy (uśredniony koszt energii)
- **PI** — Profitability Index (wskaźnik rentowności)
- **VaR** — Value at Risk (wartość zagrożonego kapitału)
- **CVaR** — Conditional VaR (oczekiwana strata poniżej VaR)
- **CAPEX** — Capital Expenditure (nakład inwestycyjny)
- **OPEX** — Operating Expenditure (koszty eksploatacji)
- **LID** — Light-Induced Degradation (degradacja indukowana światłem)
- **DPP** — Discounted Payback Period (zdyskontowany okres zwrotu)
- **CFADS** — Cash Flow Available for Debt Service (przepływ do obsługi długu)

---

**Dokument przygotowany dla:** agent redakcyjny piszący artykuł na stronę WWW
**Źródło:** analiza kodu portalu ANALIZATOR PV, 4 agentów specjalistycznych
**Data:** kwiecień 2026
