# Dokumentacja Algorytmów BESS - ANALIZATOR PV

**Wersja:** 2.0
**Data aktualizacji:** Styczeń 2026
**Autor:** Zespół ANALIZATOR PV

---

## Spis treści

1. [Wprowadzenie](#1-wprowadzenie)
2. [Algorytmy Peak Shaving](#2-algorytmy-peak-shaving)
3. [Strategie Dispatch (Sterowania)](#3-strategie-dispatch-sterowania)
4. [Algorytmy Wymiarowania BESS](#4-algorytmy-wymiarowania-bess)
5. [Kalkulacje Ekonomiczne](#5-kalkulacje-ekonomiczne)
6. [Modele Degradacji](#6-modele-degradacji)
7. [Optymalizacja Taryfowa](#7-optymalizacja-taryfowa)
8. [Opłata Mocowa](#8-opłata-mocowa)
9. [Symulacja Monte Carlo](#9-symulacja-monte-carlo)
10. [Ograniczenia Sieciowe](#10-ograniczenia-sieciowe)
11. [Revenue Stacking](#11-revenue-stacking)
12. [Stack Technologiczny](#12-stack-technologiczny)

---

## 1. Wprowadzenie

System ANALIZATOR PV implementuje kompleksowy zestaw algorytmów do analizy, wymiarowania i optymalizacji magazynów energii (BESS - Battery Energy Storage System). Dokumentacja ta opisuje wszystkie kluczowe algorytmy używane w systemie.

### 1.1 Zakres funkcjonalności BESS

- **Peak Shaving** - redukcja szczytów poboru mocy
- **PV Shifting** - przesunięcie nadwyżek PV w czasie
- **Arbitraż ToU** - wykorzystanie różnic cen energii
- **Opłata Mocowa** - redukcja składnika mocowego
- **Analiza ryzyka** - symulacje Monte Carlo

---

## 2. Algorytmy Peak Shaving

### 2.1 Analiza progów percentylowych

**Lokalizacja:** `services/frontend-economics/consumption.js` (linie ~700-2308)

**Cel:** Identyfikacja optymalnego progu odcięcia szczytów dla BESS

#### Metodologia

1. **Sortowanie danych** - moce godzinowe od największej do najmniejszej
2. **Obliczenie progów percentylowych** - P100, P99.5, P99, P98, P97, P95
3. **Zliczanie przekroczeń** - liczba godzin powyżej każdego progu
4. **Grupowanie zdarzeń** - łączenie kolejnych godzin w bloki czasowe
5. **Obliczenie energii do shave'owania** - (moc - próg) × czas [kWh]

#### Wzory

```
Próg Pxx = wartość mocy, gdzie xx% godzin jest powyżej

Energia nadwyżkowa = Σ max(0, P[t] - próg) × Δt

Redukcja szczytu [%] = (P_max - próg) / P_max × 100
```

#### Ocena opłacalności

| Liczba godzin przekroczeń | Ocena |
|---------------------------|-------|
| ≤50 godzin | Bardzo opłacalne |
| ≤100 godzin | Opłacalne |
| ≤500 godzin | Możliwe |
| >500 godzin | Nieopłacalne |

#### Przykład

```
Dane wejściowe: 8760 wartości godzinowych [kW]
Szczyt roczny: 1245 kW

Wyniki:
P99.5 (próg 968 kW):
- 42 godziny przekroczeń rocznie
- 3,310 kWh do shave'owania
- Redukcja szczytu: 22.3%
- Ocena: Bardzo opłacalne
```

### 2.2 Algorytm grupowania bloków

**Lokalizacja:** `services/frontend-economics/consumption.js` (linia ~1130)

**Funkcja:** `groupConsecutiveEvents()`

**Cel:** Grupowanie pojedynczych godzin przekroczeń w ciągłe bloki czasowe

#### Logika

```
1. Sortuj zdarzenia chronologicznie
2. Rozpocznij pierwszy blok
3. Dla każdego zdarzenia:
   - Jeśli przerwa ≤ tolerancja (1.5 × interwał): rozszerz blok
   - Jeśli przerwa > tolerancja: zakończ blok, rozpocznij nowy
```

#### Struktura bloku

```javascript
{
  startTime: Date,        // początek bloku
  endTime: Date,          // koniec bloku
  durationHours: number,  // czas trwania [h]
  maxPowerKW: number,     // maksymalna moc w bloku [kW]
  totalExcessKWh: number, // suma energii nadwyżkowej [kWh]
  intervalCount: number   // liczba interwałów
}
```

---

## 3. Strategie Dispatch (Sterowania)

### 3.1 Dispatch PV-Surplus (Autokonsumpcja)

**Lokalizacja:** `services/bess-dispatch/dispatch_engine.py`

**Cel:** Maksymalizacja autokonsumpcji energii z PV

#### Algorytm

```
DLA każdego kroku czasowego t:
  1. Konsumpcja bezpośrednia = min(PV[t], Obciążenie[t])
  2. Nadwyżka = PV[t] - konsumpcja bezpośrednia
  3. Deficyt = Obciążenie[t] - konsumpcja bezpośrednia

  4. JEŚLI Nadwyżka > 0:
     - Ładuj baterię: min(nadwyżka, P_max) z uwzględnieniem SOC
     - Nadmiar → curtailment (model 0-export)

  5. JEŚLI Deficyt > 0:
     - Rozładuj baterię: min(deficyt, P_max) do SOC_min
     - Pozostałość → import z sieci
```

#### Parametry kluczowe

| Parametr | Opis | Typowa wartość |
|----------|------|----------------|
| P_max | Moc znamionowa [kW] | zależna od projektu |
| E_nom | Pojemność [kWh] | zależna od projektu |
| η_roundtrip | Sprawność cyklu | 90% |
| η_one_way | Sprawność jednokierunkowa | √0.90 ≈ 94.87% |
| SOC_min | Minimalny SOC | 10% |
| SOC_max | Maksymalny SOC | 90% |

### 3.2 Dispatch Peak Shaving

**Lokalizacja:** `services/bess-dispatch/dispatch_engine.py`

**Cel:** Redukcja szczytów importu z sieci (zmniejszenie opłat za moc)

#### Algorytm

```
PARAMETR: peak_limit_kw [próg odcięcia]

DLA każdego kroku czasowego t:
  net_load[t] = Obciążenie[t] - PV[t]

  JEŚLI net_load[t] > peak_limit_kw:
    required_discharge = net_load[t] - peak_limit_kw
    discharge[t] = min(required, P_max, dostępny_SOC)
    grid_import[t] = net_load[t] - discharge[t]
    new_peak = max(new_peak, grid_import[t])

  W PRZECIWNYM RAZIE JEŚLI 0 < net_load[t] ≤ peak_limit_kw:
    headroom = peak_limit_kw - net_load[t]
    JEŚLI SOC < SOC_max:
      charge[t] = min(headroom, P_max, dostępna_przestrzeń)

  W PRZECIWNYM RAZIE (net_load[t] ≤ 0):
    surplus = -net_load[t]
    curtailment[t] = surplus  (0-export)
```

#### Metryki

```
Szczyt oryginalny = max(net_load > 0)
Nowy szczyt = max(grid_import po BESS)
Redukcja szczytu [%] = (oryginalny - nowy) / oryginalny × 100
```

### 3.3 Dispatch STACKED (Tryb hybrydowy)

**Lokalizacja:** `services/bess-dispatch/dispatch_engine.py`

**Cel:** Jeden magazyn realizuje jednocześnie PV shifting i peak shaving z rezerwą SOC

#### Algorytm z priorytetami

```
rezerwa_soc = E_nom × procent_rezerwy  [np. 30%]
pv_soc_min = max(SOC_min × E_nom, rezerwa_soc)

DLA każdego kroku czasowego t:

  PRIORYTET 1 - Peak Shaving:
    JEŚLI net_load[t] > peak_limit_kw:
      energia_dostępna = SOC[t] - SOC_min × E_nom  [PEŁNY zakres]
      discharge[t] = min(required, P_max, dostępna)
      SOC[t+1] = SOC[t] - discharge[t] / η_dis / Δt

  PRIORYTET 2 - Ładowanie z nadwyżki PV:
    W PRZECIWNYM RAZIE JEŚLI nadwyżka > 0:
      charge[t] = min(nadwyżka, P_max, przestrzeń_do_SOC_max)
      SOC[t+1] = SOC[t] + charge[t] × η_charge × Δt
      curtailment[t] = nadwyżka - charge[t]

  PRIORYTET 3 - Rozładowanie PV Shifting:
    W PRZECIWNYM RAZIE JEŚLI deficyt > 0:
      energia_ponad_rezerwę = SOC[t] - pv_soc_min  [TYLKO ponad rezerwą]
      JEŚLI energia_ponad_rezerwę > 0:
        discharge[t] = min(deficyt, dostępna_ponad_rezerwą)
      grid_import[t] = deficyt - discharge[t]
```

#### Śledzenie degradacji per usługa

```
throughput_peak_mwh: Energia dla peak shaving
throughput_pv_mwh: Energia dla PV shifting
efc_peak: Cykle dla peak shaving
efc_pv: Cykle dla PV shifting
peak_events_count: Liczba zdarzeń peak shaving
```

### 3.4 Dispatch arbitrażu ToU

**Lokalizacja:** `services/bess-dispatch/dispatch_arbitrage.py`

**Cel:** Zysk z różnic cen energii między strefami/godzinami

#### Algorytm

```
próg_ładowania = P25  [np. 300 PLN/MWh]
próg_rozładowania = P75  [np. 600 PLN/MWh]

DLA każdego kroku czasowego t:
  cena_t = ceny_importu[t]

  PRIORYTET 1 - Peak Shaving (jeśli ustawiony peak_limit):
    JEŚLI Obciążenie[t] > peak_limit:
      rozładuj aby zredukować szczyt

  PRIORYTET 2 - Ładowanie przy niskiej cenie:
    W PRZECIWNYM RAZIE JEŚLI cena_t ≤ próg_ładowania:
      ładowanie_z_sieci = min(P_max, dostępna_przestrzeń)
      grid_import[t] = Obciążenie[t] + ładowanie_z_sieci

  PRIORYTET 3 - Rozładowanie przy wysokiej cenie:
    W PRZECIWNYM RAZIE JEŚLI cena_t > próg_rozładowania I SOC > SOC_min:
      discharge[t] = min(P_max, dostępny_SOC)
      grid_export[t] LUB reduce_import[t]

  W PRZECIWNYM RAZIE (normalna cena):
    standard_dispatch (autokonsumpcja lub peak shaving)
```

---

## 4. Algorytmy Wymiarowania BESS

### 4.1 Metoda heurystyczna (szybka)

**Lokalizacja:** `services/economics/bess_optimizer.py`

**Cel:** Szybkie oszacowanie pojemności i mocy BESS

#### Metodologia

```
1. Znajdź bloki przekroczeń powyżej peak_limit_kw
2. Zidentyfikuj największy blok według energii

Obliczenie pojemności:
  E_bess = (E_max_blok / (DOD × η)) × margines_bezpieczeństwa
  gdzie:
    E_max_blok = energia największego bloku [kWh]
    DOD = głębokość rozładowania (0.8)
    η = sprawność cyklu (0.9)
    margines_bezpieczeństwa = 1.2 (20% bufor)

Obliczenie mocy:
  P_bess = max_nadwyżka_mocy × margines_bezpieczeństwa
  gdzie:
    max_nadwyżka_mocy = max(moc - próg) ze wszystkich bloków [kW]
```

#### Przykład

```
Największy blok: 920 kWh, max nadwyżka: 232 kW
E_bess = (920 / 0.72) × 1.2 = 1,533 kWh
P_bess = 232 × 1.2 = 278 kW
```

**Czas obliczeń:** <1ms na punkt testowy

### 4.2 Optymalizacja PyPSA+HiGHS (zaawansowana)

**Lokalizacja:** `services/economics/bess_optimizer.py`

**Cel:** Optymalne wymiarowanie BESS przy użyciu programowania liniowego

#### Model optymalizacyjny

```
Minimalizuj: CAPEX = E × koszt_kwh + P × koszt_kw

Z ograniczeniami:
  SOC(t) = SOC(t-1) + ładowanie(t)×η - rozładowanie(t)/η
  SOC_min ≤ SOC(t) ≤ SOC_max
  ładowanie(t) ≤ P_max
  rozładowanie(t) ≤ P_max
  rozładowanie(t) ≥ nadwyżka(t)  [dla wszystkich godzin przekroczeń]
  SOC(0) = SOC(T)  [cykliczność]
```

#### Używane biblioteki

- **PyPSA** v0.27.1: Model optymalizacji sieci energetycznej
- **HiGHS** v1.7.1: Wydajny solver LP/MIP

### 4.3 Optymalizacja Grid Search (iteracyjna NPV)

**Lokalizacja:** `services/bess-dispatch/sizing_runner.py`

**Cel:** Znalezienie optymalnej kombinacji moc/czas trwania maksymalizującej NPV

#### Metodologia

```
DLA każdego czasu trwania D w [1h, 2h, 4h]:
  zakres_mocy = linspace(min_moc, max_moc, 15 kroków)

  DLA każdej mocy P w zakres_mocy:
    E = P × D

    JEŚLI E w [E_min, E_max]:
      1. Uruchom symulację dispatch (8760 godzin)
         → roczne_rozładowanie_kwh
         → szczyt_sieciowy_kw
         → oszczędności_opłat_za_moc

      2. Oblicz ekonomię:
         capex = E × koszt_kwh + P × koszt_kw
         roczny_opex = capex × procent_opex
         roczne_oszczędności = rozładowanie × cena + oszczędności_szczytu + arbitraż
         npv = NPV(oszczędności-opex, capex, stopa_dyskontowa, lata)

      3. Jeśli NPV > najlepsze_npv:
         zapisz konfigurację
```

#### Wzór NPV

```
NPV = Σ(t=1..n) [(roczne_oszczędności - opex) / (1+r)^t] - CAPEX

gdzie:
  r = stopa dyskontowa (7%)
  n = okres analizy (25 lat)
```

---

## 5. Kalkulacje Ekonomiczne

### 5.1 Analiza kosztów BESS

**Lokalizacja:** `services/bess-dispatch/economics_helper.py`

#### Obliczenie CAPEX

```
CAPEX = E_nom × capex_per_kwh + P_max × capex_per_kw

Wartości domyślne:
  capex_per_kwh = 1500 PLN/kWh
  capex_per_kw = 300 PLN/kW

Przykład: 100 kW / 200 kWh
  CAPEX = 200 × 1500 + 100 × 300 = 330,000 PLN
```

#### Obliczenie OPEX

```
Roczny OPEX = CAPEX × procent_opex_rocznie

Domyślnie: procent_opex_rocznie = 1.5%
Przykład: 330,000 × 0.015 = 4,950 PLN/rok

Przez 25 lat: 4,950 × 25 = 123,750 PLN
```

### 5.2 Oszczędności z Peak Shaving

```
Miesięczne oszczędności = redukcja_szczytu_kw × opłata_za_moc_pln_kw_mies
Roczne oszczędności = miesięczne_oszczędności × 12

Przykład:
  Oryginalny szczyt: 1200 kW
  Nowy szczyt (po BESS): 1000 kW
  Redukcja szczytu: 200 kW
  Opłata za moc: 50 PLN/kW/mies
  Miesięczne oszczędności: 200 × 50 = 10,000 PLN
  Roczne oszczędności: 120,000 PLN
```

### 5.3 Analiza Peak Shaving vs Kara umowna

**Lokalizacja:** `services/frontend-economics/consumption.js` (linie 2139-2308)

#### Obliczenie kary (polska taryfa)

```
Kara = C_ss × suma(TOP10 nadwyżek/mies.)

gdzie:
  C_ss = składnik stały stawki sieciowej [zł/kW/mies.]
         (typowo 40 zł/kW/mies. dla TAURON/PGE B21)
  TOP10 = 10 największych nadwyżek godzinowych ponad P_um w miesiącu [kW]

Algorytm:
1. Dla każdego miesiąca:
   - Pobierz wszystkie nadwyżki godzinowe: nadwyżka[h] = max(0, moc[h] - P_um)
   - Posortuj malejąco
   - Weź 10 największych wartości
   - Zsumuj: suma_top10

2. Miesięczna kara = C_ss × suma_top10

3. Roczna kara = Σ(wszystkie miesiące) miesięczna_kara

4. Przez 15 lat: roczna_kara × 15
```

#### Logika decyzyjna

```
JEŚLI (KOSZT_BESS_15L < KOSZT_KARY_15L):
  → Zainwestuj w BESS
  oszczędności = KOSZT_KARY_15L - KOSZT_BESS_15L
W PRZECIWNYM RAZIE:
  → Płać karę
  oszczędności = KOSZT_BESS_15L - KOSZT_KARY_15L
```

---

## 6. Modele Degradacji

### 6.1 Liczenie cykli (Equivalent Full Cycles - EFC)

**Lokalizacja:** `services/bess-dispatch/cycle_accounting_helper.py`

#### Wzór

```
EFC = całkowite_rozładowanie_kwh / pojemność_użytkowa_kwh

Pojemność użytkowa:
  E_użytkowa = E_nom × (SOC_max - SOC_min)
  E_użytkowa = E_nom × (0.90 - 0.10) = 0.80 × E_nom

Przykład:
  E_nom = 200 kWh
  E_użytkowa = 160 kWh
  Roczne rozładowanie = 40,000 kWh
  Roczne EFC = 40,000 / 160 = 250 cykli/rok
```

### 6.2 Kontrola budżetu degradacji

**Lokalizacja:** `services/bess-dispatch/dispatch_engine.py`

#### Metodologia

```
żywotność_cyklowa = 6000 cykli (typowo)
żywotność_kalendarzowa = 15 lat
degradacja_rok1 = 3%
degradacja_na_rok = 1.5% (rok 2+)

Dozwolone roczne cykle = żywotność_cyklowa / oczekiwana_żywotność_lat

Dla trybu STACKED:
  - Oddzielne budżety cykli dla peak shaving vs PV shifting
  - Śledzenie skumulowanych cykli per usługa
  - Alert przy przekroczeniu
```

### 6.3 Degradacja pojemności w czasie

```
Pojemność(rok_n) = Pojemność(0) × (1 - stopa_degradacji)^n

Przykład przy 1.5%/rok degradacji:
  Rok 0:  200 kWh (100%)
  Rok 1:  194 kWh (97%)  - włącznie z początkową 3% stratą Y1
  Rok 5:  182.5 kWh (91.2%)
  Rok 10: 169 kWh (84.5%)
  Rok 15: 156.3 kWh (78.1%)

Wpływ na roczną energię:
  roczne_rozładowanie(rok_n) = roczne_rozładowanie(0) × współczynnik_pojemności(n)
```

---

## 7. Optymalizacja Taryfowa

### 7.1 System taryf OSD (polskie taryfy dystrybucyjne)

**Lokalizacja:** `services/bess-dispatch/osd_tariffs/compiler.py`

#### Struktura taryfy

```
Składniki taryfy OSD:
  1. Zmienny - koszt zmienny w czasie [zł/kWh]
  2. Stały - stały koszt miesięczny [zł]
  3. Opłata mocowa - opłata za moc [zł/kW/mies]
  4. Opłata przesyłowa - dostęp do sieci [zł]

Ceny strefowe (system 3-strefowy):
  Strefa I (droga): Godziny szczytowe (7-21 dni robocze)
  Strefa II (pół-droga): Godziny przejściowe
  Strefa III (tania): Godziny pozaszczytowe (21-7, weekendy)
```

#### Algorytm kompilatora taryf

```
1. Załaduj definicję taryfy z harmonogramami per zakres dat
2. Dla każdej daty:
   - Określ typ dnia (roboczy/weekend/święto)
   - Pobierz aktywny harmonogram dla tej daty
   - Dla każdej minuty: mapuj na strefę (I/II/III)
   - Dla każdej godziny: weź strefę większościową
   - Oblicz stawkę ze strefy

3. Kompiluj dzień: (data, typ_dnia, strefy_minutowe[], strefy_godzinowe[], stawki_godzinowe[])
4. Cachuj wyniki dla wydajności
```

---

## 8. Opłata Mocowa

### 8.1 Algorytm obliczania opłaty mocowej (polski rynek mocy)

**Lokalizacja:** `services/bess-dispatch/capacity_fee_pl/calculator.py`

**Cel:** Obliczenie oszczędności z opłaty mocowej dzięki BESS redukującemu szczyty importu

#### Klasyfikacja K-Class

```
Δs = (średnia_wybrane / średnia_poza - 1) × 100%

gdzie:
  wybrane = godziny robocze 7:00-22:00
  poza = godziny pozaszczytowe

K1: Δs < 5%           → A = 0.17
K2: Δs ∈ [5%, 10%)    → A = 0.50
K3: Δs ∈ [10%, 15%)   → A = 0.83
K4: Δs ≥ 15% LUB ZPS=0 → A = 1.00
```

#### Wzór opłaty

```
WOM = A × SOM × ZS

gdzie:
  A = współczynnik klasy
  SOM = średnia moc w wybranych godzinach [kW]
  ZS = stawka taryfowa [PLN/kW]
```

#### Wpływ BESS

```
oryginalna_opłata = A_oryginalne × SOM_oryginalne × ZS
nowa_opłata = A_nowe × SOM_nowe × ZS
oszczędności = oryginalna_opłata - nowa_opłata
```

---

## 9. Symulacja Monte Carlo

### 9.1 Silnik symulacji stochastycznej

**Lokalizacja:** `services/economics/monte_carlo/`

**Cel:** Ocena ryzyka finansowego przez symulację niepewnych parametrów

#### Symulowane parametry (wektoryzacja NumPy)

```
1. Cena energii: Normal(baza=450 PLN/MWh, σ=15%)
2. Współczynnik produkcji: Normal(baza=1.0, σ=10%)
3. CAPEX: Lognormal(baza=3500 PLN/kWp, σ=10%)
4. Inflacja: Normal(baza=2.5%, σ=2pp)
5. Degradacja: Triangular(min=0.3%, mode=0.5%, max=0.8%)
6. Stopa dyskontowa: Triangular(min=5%, mode=7%, max=10%)
```

#### Macierz korelacji (dekompozycja Cholesky'ego)

```
          Cena   Prod  CAPEX  Inflacja
Cena      1.00   0.00  -0.00  0.60
Prod      0.00   1.00  -0.20  -0.00
CAPEX    -0.00  -0.20   1.00  -0.00
Inflacja  0.60  -0.00  -0.00  1.00
```

#### Algorytm

```
DLA każdej z N_symulacji (typowo 5,000-10,000):
  1. Generuj skorelowane próbki parametrów
  2. Dla każdego roku (1..25):
     - Zastosuj degradację: pojemność(rok) × współczynnik_degrad
     - Zastosuj inflację: cena(rok) × (1+inflacja)^rok
     - Oblicz przepływ gotówki: oszczędności - opex
     - Wkład NPV: CF / (1+stopa_dyskontowa)^rok
  3. Zsumuj wkłady NPV
  4. Oszacuj IRR (metoda Newtona-Raphsona)
  5. Oblicz okres zwrotu

WYNIK:
  - Rozkład NPV (średnia, odch. std., P10, P50, P90)
  - Rozkład IRR
  - Rozkład okresu zwrotu
  - Metryki ryzyka: VaR, CVaR, prawdopodobieństwo dodatniego NPV
```

#### Wektoryzacja (NumPy Broadcasting)

```python
Wszystkie N symulacji równolegle:
  npv_results = -investments.copy()  # shape: (N,)
  FOR year in range(1, 26):
    degrad = (1 - degradation) ** year  # shape: (N,)
    production = base_prod × degrad × prod_factors  # shape: (N,)
    price = prices × (1 + inflation) ** year  # shape: (N,)
    savings = (production × price_discount)  # shape: (N,)
    npv_results += savings / ((1+discount)^year)
```

**Czas obliczeń:** ~20ms dla 10,000 symulacji

### 9.2 Metryki ryzyka

```
1. Prawdopodobieństwo dodatniego NPV = count(NPV > 0) / N_symulacji

2. VaR (Value at Risk):
   VaR_95 = percentyl(NPV, 5)  [95% pewności]

3. CVaR (Conditional VaR / Expected Shortfall):
   CVaR_95 = średnia(NPV | NPV ≤ VaR_95)

4. Współczynnik zmienności:
   CV = odch_std(NPV) / abs(średnia(NPV))

5. Wskaźnik Sharpe'a:
   Sharpe = średnia(NPV) / odch_std(NPV)
```

---

## 10. Ograniczenia Sieciowe

### 10.1 Ograniczenie eksportu (Export Cap)

**Lokalizacja:** `services/bess-dispatch/dispatch_engine.py`

**Cel:** Limit eksportu PV dla modeli 0-export lub ze zredukowanym eksportem

#### Algorytm

```
JEŚLI max_export_kw jest ustawione LUB allow_export = False:
  DLA każdego kroku czasowego t:
    JEŚLI grid_export[t] > max_export_kw:
      nadmiar = grid_export[t] - max_export_kw
      grid_export[t] = max_export_kw
      curtailment[t] += nadmiar  [konwertuj na curtail]
```

### 10.2 Ograniczenie importu (Import Cap)

**Lokalizacja:** `services/bess-dispatch/dispatch_engine.py`

**Cel:** Respektowanie maksymalnego limitu importu z sieci

#### Algorytm

```
JEŚLI max_import_kw jest ustawione:
  DLA każdego kroku czasowego t:
    JEŚLI grid_import[t] > max_import_kw:
      nieobsłużone = grid_import[t] - max_import_kw
      grid_import[t] = max_import_kw
      śledź nieobsłużone_obciążenie_kwh
```

---

## 11. Revenue Stacking

### 11.1 Wielousługowy BESS (tryb STACKED)

**Główna strategia:** Użycie jednego magazynu dla wielu strumieni przychodów:

1. **PV Shifting (Autokonsumpcja):** Ładowanie z nadwyżki PV, rozładowanie podczas deficytu
2. **Peak Shaving:** Redukcja szczytów importu dla obniżenia opłat za moc
3. **Arbitraż ToU:** Ładowanie przy niskich cenach, rozładowanie przy wysokich (przyszłość)
4. **Oszczędności z opłaty mocowej:** Redukcja średniej w wybranych godzinach

#### Implementacja

- Tryb STACKED z alokacją rezerwy SOC
- Oddzielne śledzenie degradacji per usługa (efc_pv, efc_peak)
- Księgowanie energii per usługa (throughput_pv_mwh, throughput_peak_mwh)

### 11.2 Atrybucja degradacji

```
Dla każdej usługi:
  throughput[usługa] = całkowita_energia_przez_baterię_dla_usługi
  efc[usługa] = throughput[usługa] / pojemność_użytkowa

Całkowita degradacja:
  ważone_efc = efc_pv × waga_pv + efc_peak × waga_peak
```

---

## 12. Stack Technologiczny

### Backend

| Technologia | Wersja | Zastosowanie |
|-------------|--------|--------------|
| Python | 3.10+ | Główny język |
| FastAPI | latest | REST API |
| Pydantic | latest | Walidacja |
| NumPy | latest | Wektoryzowana matematyka |
| PyPSA | 0.27.1 | Modelowanie systemów energetycznych |
| HiGHS | 1.7.1 | Solver optymalizacyjny |

### Frontend

| Technologia | Zastosowanie |
|-------------|--------------|
| JavaScript | Główny język (vanilla) |
| Chart.js | Wizualizacja |
| HTML/CSS | Interfejs użytkownika |

---

## Lokalizacje plików - Podsumowanie

| Algorytm | Plik | Lokalizacja |
|----------|------|-------------|
| Analiza Peak Shaving | consumption.js | services/frontend-economics/~2139 |
| Dispatch PV-Surplus | dispatch_engine.py | services/bess-dispatch/~347 |
| Dispatch Peak Shaving | dispatch_engine.py | services/bess-dispatch/~450 |
| Dispatch STACKED | dispatch_engine.py | services/bess-dispatch/~550 |
| Arbitraż ToU | dispatch_arbitrage.py | services/bess-dispatch/~40 |
| Wymiarowanie BESS (heurystyczne) | bess_optimizer.py | services/economics/~192 |
| Wymiarowanie BESS (PyPSA) | bess_optimizer.py | services/economics/~250 |
| Optymalizacja Grid Search | sizing_runner.py | services/bess-dispatch/~138 |
| Obliczanie NPV | sizing_runner.py | services/bess-dispatch/~138 |
| Opłata mocowa | calculator.py | services/bess-dispatch/capacity_fee_pl/~87 |
| Kompilator taryf OSD | compiler.py | services/bess-dispatch/osd_tariffs/~54 |
| Silnik cen | price_engine.py | services/bess-dispatch/~82 |
| Liczenie cykli | cycle_accounting_helper.py | services/bess-dispatch/~50 |
| Silnik Monte Carlo | engine.py | services/economics/monte_carlo/ |
| Budżet degradacji | dispatch_engine.py | services/bess-dispatch/ |

---

## Powiązana dokumentacja

- [BESS Peak Shaving Algorithm Full](BESS_Peak_Shaving_Algorithm_FULL.md)
- [BESS vs Penalty Calculation](BESS_vs_Penalty_Calculation.md)
- [Monte Carlo Dokumentacja Techniczna](MONTE_CARLO_DOKUMENTACJA_TECHNICZNA.md)

---

*Dokumentacja wygenerowana: Styczeń 2026*
