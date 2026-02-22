# PROMPT: Pełna weryfikacja modelu finansowego portalu ANALIZATOR PV

## Kontekst

Jesteś audytorem modeli finansowych. Twoim zadaniem jest zweryfikowanie poprawności **wszystkich obliczeń ekonomicznych** w portalu do analizy opłacalności instalacji fotowoltaicznych (PV) i magazynów energii (BESS) dla klientów przemysłowych w Polsce.

Portal obsługuje dwa modele finansowe:
- **CAPEX** — klient kupuje instalację (ponosi nakład inwestycyjny)
- **EaaS** (Energy as a Service) — dostawca buduje i utrzymuje instalację, klient płaci abonament

Waluta: PLN. Rynek: Polska (regulacje, święta, taryfy).

---

## Pliki źródłowe

| Plik | Rola | Rozmiar |
|------|------|---------|
| `services/frontend-economics/economics.js` | Główny silnik kalkulacyjny | ~18 900 linii |
| `services/frontend-economics/capex-export.js` | Eksport CAPEX do Excel | ~3 200 linii |
| `services/frontend-economics/bankability.js` | Wskaźniki bankowalności (DSCR) | ~1 100 linii |
| `services/profile-analysis/app.py` | Backend — TCSL, opłata mocowa, klasy K | ~3 000 linii |
| `services/frontend-economics/monte-carlo.js` | Monte Carlo (frontend) | ~1 100 linii |

---

## 1. OBLICZENIA NPV

### 1.1 CAPEX NPV (`calculateCapexNPV` — economics.js:5775)

```
Dane wejściowe:
  capacity_kwp          [kWp]           Moc instalacji PV
  self_consumed_annual_kwh [kWh]        Roczna autokonsumpcja
  total_energy_price_per_kwh [PLN/kWh]  Pełna cena energii z sieci (suma składników)
  capex_per_kwp         [PLN/kWp]       Jednostkowy CAPEX
  opex_per_kwp          [PLN/kWp/rok]   Jednostkowy OPEX (serwis)
  degradation_rate      [ułamek]        Roczna degradacja PV (np. 0.005 = 0.5%)
  discount_rate         [ułamek]        Stopa dyskontowa (np. 0.07)
  analysis_period       [lata]          Okres analizy (domyślnie 25-30)
  inflation_rate        [ułamek]        Stopa inflacji (domyślnie 0.025)

Formuła:
  CAPEX = capacity_kwp × capex_per_kwp
  NPV = −CAPEX
  Dla roku = 1 do analysis_period:
    degradation_factor = (1 − degradation_rate)^(rok−1)
    inflation_factor = (1 + inflation_rate)^(rok−1)
    savings = (self_consumed_annual_kwh / 1000) × degradation_factor × total_energy_price_per_kwh × inflation_factor × 1000
    opex = capacity_kwp × opex_per_kwp × inflation_factor
    cash_flow = savings − opex
    NPV += cash_flow / (1 + discount_rate)^rok

Wynik: NPV [PLN]
```

**Do weryfikacji:**
- Czy degradation_factor poprawnie zaczyna od roku 1 (rok 1 = brak degradacji, rok 2 = pierwsza degradacja)?
- Czy inflacja jest stosowana do obu: savings ORAZ opex?
- Czy units są spójne (kWh→MWh→PLN)?
- Czy discount_rate jest roczna (nie miesięczna)?

### 1.2 EaaS NPV (`calculateEaaSNPV` — economics.js:5811)

```
Dodatkowe dane wejściowe:
  eaas_subscription     [PLN/rok]       Abonament EaaS
  eaas_om_per_kwp       [PLN/kWp/rok]   O&M per kWp
  insurance_rate        [ułamek]        Stawka ubezpieczenia (np. 0.005 = 0.5% CAPEX)
  eaas_duration         [lata]          Czas trwania kontraktu EaaS
  eaas_indexation       ['fixed'|'cpi'] Czy abonament rośnie z inflacją

Formuła:
  base_eaas_cost = eaas_subscription + (capacity_kwp × eaas_om_per_kwp) + (capex × insurance_rate)
  NPV = 0  (brak nakładu inwestycyjnego po stronie klienta)
  Dla roku = 1 do analysis_period:
    savings = self_consumed_MWh × degradation × adjusted_energy_price × 1000
    eaas_inflation = (indexation=='cpi') ? inflation_factor : 1
    costs = (rok ≤ eaas_duration) ? base_eaas_cost × eaas_inflation : 0
    cash_flow = savings − costs
    NPV += cash_flow / (1 + discount_rate)^rok

Wynik: NPV [PLN]
```

**Do weryfikacji:**
- Czy po zakończeniu kontraktu EaaS (rok > eaas_duration) koszty = 0? Czy to poprawne? (W rzeczywistości po kontrakcie klient przejmuje instalację i ponosi O&M + ubezpieczenie)
- Czy `base_eaas_cost` nie zawiera podwójnego liczenia O&M (subscription może już zawierać O&M)?

### 1.3 Master function (`calculateCentralizedFinancialMetrics` — economics.js:3189)

To jest **główna funkcja** używana do wszystkich metryk finansowych. Przelicza zarówno CAPEX jak i EaaS w jednym przebiegu, z uwzględnieniem:
- Dwufazowej degradacji PV (rok 1: wyższa, lata 2+: niższa)
- Degradacji BESS (osobna krzywa)
- Inflacji (tryb nominalny/realny)
- Wymiany falownika i BESS (reinvestment)
- Wartości rezydualnej
- Land lease (dzierżawa gruntu)

```
Degradacja PV:
  Rok 1: factor = 1 − pvDegradationYear1    (domyślnie 2%)
  Rok N: factor = (1 − pvDegYear1) × (1 − degradationRate)^(N−1)   (domyślnie 0.5%/rok)

Degradacja BESS:
  Rok 1: factor = 1 − bessDegradationYear1   (domyślnie 3%)
  Rok N: factor = (1 − bessDegYear1) × (1 − bessDegRate)^(N−1)   (domyślnie 2%/rok)

CAPEX:
  npv = −capex
  Dla roku = 1 do 30:
    pvDeg = pvDegFactor(rok)
    bessDeg = bessDegFactor(rok)
    inflFactor = useInflation ? (1 + inflation)^(rok−1) : 1
    savings = (pvDirectMwh × pvDeg + bessSelfConsumedMwh × bessDeg) × totalEnergyPrice × inflFactor
    opex = (capacityKwp × opex_per_kwp + opexBESS) × inflFactor
    CF = savings − opex
    npv += CF / (1 + discountRate)^rok

EaaS:
  npv = 0
  Dla roku = 1 do 30:
    gridCost = yearSelfConsumedMwh × gridPrice × inflFactor   ← co klient zapłaciłby za prąd z sieci
    Jeśli rok ≤ eaasDuration:
      eaasCost = subscription × (indexation=='cpi' ? inflFactor : 1)
    W przeciwnym razie:
      eaasCost = O&M + ubezpieczenie + landLease + bessOpex  (wszystko × inflFactor)
    savings = gridCost − eaasCost
    npv += savings / (1 + discountRate)^rok

Wyniki:
  capex: { npv, irr, cashFlows[], investment, simplePayback, discountedPayback, lcoe }
  eaas: { npv, duration, baseSubscription, cashFlows[] }
```

**Do weryfikacji:**
- Czy EaaS po kontrakcie prawidłowo nalicza koszty O&M (klient przejmuje instalację)?
- Czy wymiana falownika (co 12 lat) i BESS (co 15 lat) są odliczone od cash flow w odpowiednich latach?
- Czy wartość rezydualna jest dodana w ostatnim roku?
- Czy tryb nominalny/realny jest spójny (inflacja do savings + opex, albo żadnych + real discount rate)?

---

## 2. IRR

### 2.1 Bisection method (`calculateSimpleIRR` — economics.js:1116)

```
low = −0.5, high = 1.0
Dla 50 iteracji:
  mid = (low + high) / 2
  npv = −capex
  Dla roku = 1 do years:
    cf = annualSavings × (1 − degradationRate)^(rok−1) − annualOpex
    npv += cf / (1 + mid)^rok
  Jeśli |npv| < 100 PLN: return mid
  Jeśli npv > 0: low = mid; w.p.p: high = mid
Return (low + high) / 2
```

**Do weryfikacji:**
- Tolerancja 100 PLN — czy wystarczająca dla projektów >1 mln PLN?
- Czy 50 iteracji bisection daje wystarczającą precyzję (2^−50 ≈ 10^−15)?
- Czy degradation stosowana jest od roku 1 (rok 1 = brak, rok 2 = pierwsza degradacja)?
- Czy OPEX nie ma degradacji/inflacji? (W tym uproszczonym IRR — brak inflacji)

### 2.2 Newton-Raphson XIRR (`calculateXIRR` — economics.js:1997)

```
Konwersja miesięcznych przepływów na roczne (sumowanie 12 miesięcy)
guess = targetIRR
Dla 200 iteracji:
  npv = Σ( annualCFs[t] / (1+irr)^t )
  dnpv = Σ( −t × annualCFs[t] / (1+irr)^(t+1) )
  Jeśli |npv| < 1: break
  irr = irr − npv / dnpv
  Clamp irr do [−0.99, 2.0]
```

**Do weryfikacji:**
- Czy konwersja miesięcznych CF na roczne jest poprawna (proste sumowanie vs dyskontowanie)?
- Czy `t` zaczyna od 0 czy od 1? (rok 0 = inwestycja)
- Czy Newton-Raphson konwerguje dla typowych projektów PV?

---

## 3. LCOE (Levelized Cost of Energy)

### 3.1 Standard LCOE (`computeLCOE` — economics.js:13944)

```
Formuła (standard IEA/NREL):
  LCOE = PV(koszty) / PV(energia)

  PV_costs = CAPEX  (t=0)
  PV_energy = 0
  Dla roku = 1 do years:
    df = 1 / (1 + discountRate)^rok
    degradation = (1 − degradationRate)^(rok−1)
    inflFactor = applyInflationToOpex ? (1 + inflationRate)^(rok−1) : 1
    PV_costs += opexBase × inflFactor × df
    PV_energy += energyBase × degradation × df
  LCOE = PV_costs / PV_energy  [PLN/MWh]
```

### 3.2 Pięć wariantów LCOE (`calculateVariantEconomics` — economics.js:14064)

| Wariant | Formuła | Znaczenie |
|---------|---------|-----------|
| `lcoeStd` | PV(CAPEX + OPEX) / PV(Produkcja) | Koszt właściciela per MWh wyprodukowane |
| `lcoeEff` | PV(CAPEX + OPEX) / PV(Autokonsumpcja) | Koszt per MWh autokonsumowane |
| `lcoeGrid` | Aktualna cena sieci | Benchmark |
| `lcoeOfftaker` | PV(Płatności klienta EaaS) / PV(Autokonsumpcja) | Koszt klienta EaaS per MWh |
| `deltaLevelized` | lcoeGrid − lcoeEff | Oszczędność klienta vs sieć |

**Do weryfikacji:**
- Czy `lcoeStd` używa PRODUKCJI a `lcoeEff` używa AUTOKONSUMPCJI w mianowniku?
- Czy dyskontowanie jest spójne (nominalny/realny) z NPV?
- Konwersja nominalny→realny: `r_real = (1+r_nominal)/(1+inflation) − 1`

---

## 4. PAYBACK PERIOD

### 4.1 Simple Payback (economics.js:3491)

```
cumSavings = 0
Dla i = 0 do length(cashFlows):
  cumSavings += cashFlows[i].net_cash_flow
  Jeśli cumSavings ≥ capex:
    remaining = capex − prevCumulative
    simplePayback = (i + 1) + remaining / cashFlows[i].net_cash_flow
    break
```

### 4.2 Discounted Payback (DPP) (economics.js:3504)

```
runningNPV = −capex
Dla i = 0 do length(cashFlows):
  discCF = cashFlows[i].net_cash_flow / (1 + discountRate)^(i+1)
  prevNPV = runningNPV
  runningNPV += discCF
  Jeśli runningNPV ≥ 0 AND prevNPV < 0:
    DPP = rok − 1 + (−prevNPV / discCF)   ← interpolacja liniowa
    break
```

**Do weryfikacji:**
- Czy interpolacja liniowa w roku break-even jest poprawna?
- Czy DPP może być null (NPV nigdy nie osiąga 0)?

---

## 5. ANALIZA WRAŻLIWOŚCI

### 5.1 Wykres sensitivity w portalu (`generateSensitivityChart` — economics.js:5685)

5 parametrów, każdy ±20%, pełne przeliczenie `calculateCapexNPV()` dla każdego scenariusza:
- Cena energii (zmiana `total_energy_price_per_kwh`)
- CAPEX (zmiana `capex_per_kwp`)
- OPEX (zmiana `opex_per_kwp`)
- Produkcja (zmiana `self_consumed_annual_kwh`)
- Stopa dyskontowa (zmiana `discount_rate` o ±20% wartości bazowej)

### 5.2 Wykresy CAPEX vs EaaS (`generateSensitivityAnalysisCharts` — economics.js:5855)

Dwa wykresy liniowe porównujące NPV CAPEX vs NPV EaaS:
1. **Cena energii:** variacje [-30, -20, -10, 0, +10, +20, +30, +40, +50]%
2. **Stopa dyskontowa:** wartości [3, 4, 5, 6, 7, 8, 9, 10, 12]%

Oba wywołują `calculateCapexNPV()` i `calculateEaaSNPV()`.

### 5.3 Tornado Chart — CAPEX (capex-export.js:1092)

Pełne przeliczenie NPV dla 4 scenariuszy:

| Parametr | Zmiana | Metoda |
|----------|--------|--------|
| Cena energii | ±20% | `calculateCapexNPV({...base, price×0.80})` / `price×1.20` |
| CAPEX | ±20% | `calculateCapexNPV({...base, capex_per_kwp×1.20})` / `×0.80` |
| Yield PV | ±15% | `calculateCapexNPV({...base, self_consumed×0.85})` / `×1.15` |
| Stopa dyskontowa | ±2pp | `calculateCapexNPV({...base, rate+0.02})` / `rate−0.02` |

Sortowane malejąco po rozpiętości (impact).

### 5.4 Tornado Chart — EaaS (economics.js:9222)

Operuje na `baseTotalSavings` (suma nominalnych oszczędności 30 lat, tys. PLN):

```
gridPriceRatio = GridPrice / (GridPrice − EaaSPrice)
eaasPriceRatio = EaaSPrice / (GridPrice − EaaSPrice)

Cena sieci ±20%:
  pessimistic = baseSavings × (1 − 0.20 × gridPriceRatio)
  optimistic  = baseSavings × (1 + 0.20 × gridPriceRatio)

Cena EaaS ±20%:
  pessimistic = baseSavings × (1 − 0.20 × eaasPriceRatio)
  optimistic  = baseSavings × (1 + 0.20 × eaasPriceRatio)

Yield PV ±15%:
  pessimistic = baseSavings × 0.85
  optimistic  = baseSavings × 1.15

Autokonsumpcja ±10%:
  pessimistic = baseSavings × 0.90
  optimistic  = baseSavings × 1.10
```

**Do weryfikacji:**
- `gridPriceRatio` odzwierciedla efekt dźwigni marży. Przy cenie sieci 961 i EaaS 398: ratio = 961/563 = 1.71. Zmiana ceny o −20% → zmiana marży o −34%.
- Yield PV ±15% — stosuje liniowy mnożnik do baseSavings. Czy to jest poprawne? W fazie ownership (po kontrakcie EaaS) klient ma stałe koszty O&M, więc efekt powinien być nieliniowy (spadek savings > spadek yield).
- baseTotalSavings = suma NOMINALNA (nie NPV). Czy to odpowiedni wskaźnik?

### 5.5 Macierz wrażliwości (capex-export.js:1266)

```
Formuła:
  savingsMultiplier = (1 + priceVar) × (1 + yieldVar)
  adjNPV = (NPV_base + CAPEX) × savingsMultiplier − CAPEX

Interpretacja:
  PV(savings) = NPV + CAPEX   ← zdyskontowane oszczędności (przed odjęciem CAPEX)
  Jeśli savings rosną proporcjonalnie do ceny × yield:
    nowe PV(savings) = stare PV(savings) × priceMultiplier × yieldMultiplier
    nowe NPV = nowe PV(savings) − CAPEX
```

**Do weryfikacji:**
- Formuła zakłada że `NPV + CAPEX ≈ PV(savings)`. Prawdziwe jest: `NPV + CAPEX = PV(savings) − PV(OPEX)`. Błąd = skalowanie OPEX wraz z ceną/yield (OPEX nie zależy od tych parametrów). Szacowany błąd: ~1-3% w ekstremalnych scenariuszach.
- Mnożniki cena × yield działają multiplikatywnie — czy to fizycznie poprawne? TAK: `savings = autokonsumpcja × cena_energii`, więc `Δsavings ∝ Δyield × Δcena`.

---

## 6. CENA ENERGII

### 6.1 Średnia stawka ToU (`calculateTouAverageRate` — economics.js:1539)

```
flat:       avgRate = flatRate                          (domyślnie 750 PLN/MWh)
two_zone:   avgRate = dayRate × 0.60 + nightRate × 0.40
three_zone: avgRate = peakRate × 0.35 + partialRate × 0.25 + offPeakRate × 0.40
```

**Do weryfikacji:**
- Wagi stref (60/40 dla two_zone, 35/25/40 dla three_zone) — czy odpowiadają typowemu profilowi zużycia przemysłowego? W rzeczywistości proporcje zależą od profilu.

### 6.2 Łączna cena energii (`calculateTotalEnergyPrice` — economics.js:1571)

```
total = energia_czynna + dystrybucja + jakościowa + OZE + kogeneracja + mocowa + akcyza
Domyślnie: 510 + 200 + 10 + 7 + 10 + 219 + 5 = 961 PLN/MWh
```

**Do weryfikacji:**
- Czy opłata mocowa powinna być w PLN/MWh? Regulatorowo jest to opłata za MWh pobrana w godzinach wybranych (stawka SOM × współczynnik K). Dodanie jej jako stałej stawki per MWh jest uproszczeniem.
- Czy 219 PLN/MWh za opłatę mocową jest realistyczne? SOM na 2026 = 0.2194 PLN/kWh = 219.4 PLN/MWh, ale to zakłada K4 (współczynnik 1.0).

---

## 7. ABONAMENT EaaS

### 7.1 Prosta formuła (`calculateEaasSubscription` — economics.js:2148)

```
Tryb FIXED:
  A = O + I₀ × [r(1+r)^N] / [(1+r)^N − 1]

  A = roczny abonament [PLN]
  O = roczny OPEX (O&M + ubezpieczenie + dzierżawa + BESS OPEX) [PLN]
  I₀ = łączny CAPEX (PV + BESS) [PLN]
  r = docelowa IRR inwestora (np. 0.12)
  N = czas trwania kontraktu [lata]

Tryb CPI:
  r_real = (1+r)/(1+g) − 1
  A_real = O_real + I₀ × [r_real(1+r_real)^N] / [(1+r_real)^N − 1]
  A_rok1 = A_real (rośnie z CPI w kolejnych latach)
```

### 7.2 Pełny model inwestora (`calculateEaasFullModel` — economics.js:1750)

Miesięczny cash flow z: CIT, amortyzacją, finansowaniem dłużnym, indeksacją CPI.

```
Binary search: szuka rocznego abonamentu dającego docelową IRR inwestora.
Wewnętrznie: Newton-Raphson XIRR na annualizowanych miesięcznych CF.

Miesięczna pętla:
  subscription = (annualSub / 12) × cumulativeCPI × (1 − expectedLossRate)
  monthlyOpex = (baseOpex / 12) × cumulativeCPI
  EBITDA = subscription − monthlyOpex
  EBIT = EBITDA − monthlyDepreciation
  taxBase = max(0, EBIT − interest)
  tax = taxBase × citRate
  cfProject = EBITDA − tax
  cfEquity = EBITDA − tax − interest − principal
```

**Do weryfikacji:**
- Czy `expectedLossRate` (strata na windykacji) jest poprawnie stosowana do subscription?
- Czy amortyzacja (depreciation) jest liniowa i na właściwy okres?
- Czy wartość rezydualna (1 PLN/kWp contractual) wpływa na CF w ostatnim miesiącu?
- Czy dług (annuity/linear/bullet) jest poprawnie spłacany z grace periodem?

---

## 8. OPŁATA MOCOWA I KLASY K

### 8.1 Klasyfikacja K (`get_k_class` — profile-analysis/app.py:2429)

```
Per Rozporządzenie Ministra Klimatu i Środowiska (Dz.U. 2023 poz. 503):

  Δs < −10%   → K1, współczynnik 0.17
  −10% ≤ Δs < 10%  → K2, współczynnik 0.50
  10% ≤ Δs < 30%   → K3, współczynnik 0.83
  Δs ≥ 30%    → K4, współczynnik 1.00
```

### 8.2 Obliczenie opłaty (`calculate_capacity_fee` — app.py:2510)

```
Godziny wybrane: 7:00–21:59 (15h)
Godziny pozostałe: 22:00–6:59 (9h)
Dni robocze: poniedziałek–piątek bez świąt polskich

Dla każdego dnia roboczego:
  selected_sum = Σ(grid_import[7:22])        [kWh]
  outside_sum = Σ(grid_import[0:7] + grid_import[22:24])  [kWh]
  avg_selected = selected_sum / 15
  avg_outside = outside_sum / 9
  delta_s = (avg_selected / avg_outside − 1) × 100  [%]
  (k_name, k_coeff) = get_k_class(delta_s)
  day_fee = k_coeff × SOM × selected_sum    [PLN]

Opłata roczna = Σ(day_fee) dla wszystkich dni roboczych
```

**Do weryfikacji:**
- Czy godziny wybrane to 7:00–21:59 (15 godzin), nie 7:00–22:00 (16 godzin)?
  → Rozporządzenie: „od godziny 7:00 do godziny 22:00" = 7:00-7:59, 8:00-8:59, ..., 21:00-21:59 = 15 godzin.
- Czy `avg_outside` jest dzielone przez 9 (24−15=9)?
- Czy grid_import = max(0, load − pv) (nie ujemny)?
- Czy SOM = 0.2194 PLN/kWh na 2026?
- Czy polskie święta są poprawnie uwzględnione (lista świąt)?
- Czy `data_start_date` jest prawidłowo mapowane na kalendarz (nie domyślnie 1 stycznia)?

### 8.3 Korekta stochastyczna (`_estimate_stochastic_k_class` — app.py:2462)

```
Dla profili uśrednionych (std(Δs) < 2%):
  sigma_delta_s = 25.0 / (max(avg_R, 0.5) + 0.4)
  gdzie R = avg_selected / avg_outside (średni stosunek godzinowy)

  Oblicz P(K1..K4) z rozkładu normalnego N(mean_Δs, sigma_Δs) na granicach [-10, 10, 30]
  effective_coefficient = Σ(prob_i × coeff_i)
```

**Do weryfikacji:**
- Formuła na sigma — czy kalibracja (25.0 i 0.4) jest oparta na danych empirycznych?
- Czy rozkład normalny jest dobrym przybliżeniem rozkładu Δs?
- Czy aktywuje się tylko gdy std < 2% (wykrywa uśrednione profile)?

---

## 9. TCSL (Total Cost to Serve Load)

### 9.1 `compute_tcsl_for_scenario` (app.py:2743)

```
TCSL = Koszty_zmienne + Opłata_mocowa + Koszty_stałe

Koszty_zmienne = Σ_h( grid_import[h] × (active_price[h] + fees_var_sum) / 1000 )
  gdzie: grid_import[h] = max(0, load[h] − pv[h])
         active_price[h] = cena godzinowa taryfowa lub RDN [PLN/MWh]
         fees_var_sum = dystrybucja + jakość + OZE + kogeneracja + akcyza [PLN/MWh]

Opłata_mocowa = calculate_capacity_fee(grid_import, SOM, ...)

Koszty_stałe = fixed_monthly × 12
  gdzie: fixed_monthly = dist_rate × contracted_power + osd_subscription + transition_fee + supplier_fee
```

**Do weryfikacji:**
- Czy `active_price[h]` może być ujemna (ceny RDN bywają ujemne)? Jeśli tak, czy grid_import[h] × ujemna cena = przychód?
- Czy `fees_var_sum` jest dodawane do ceny per MWh, a nie per kWh?
- Czy koszty stałe są naprawdę stałe (nie zależą od PV)?

### 9.2 Endpoint `/compute-tcsl` (app.py:2951)

Oblicza 4 scenariusze:
1. Taryfa bez PV
2. Taryfa z PV
3. RDN bez PV
4. RDN z PV

Oszczędności = TCSL(bez PV) − TCSL(z PV)

---

## 10. BANKOWALNOŚĆ (DSCR)

### 10.1 Harmonogram spłaty (`generateDebtSchedule` — bankability.js:45)

3 typy spłaty:
- **Annuity:** `rata = principal × [r(1+r)^n] / [(1+r)^n − 1]`, grace period: interest-only lub capitalize
- **Bullet:** odsetki co rok, kapitał w ostatnim roku
- **Linear:** equal principal = principal / n, plus interest

### 10.2 CFADS (`calculateCFADS` — bankability.js:273)

```
CFADS = Revenue − OPEX − Taxes_cash − MaintCapex − BessReplacement − ΔWorkingCapital
```

### 10.3 DSCR (`calculateDSCR` — bankability.js:299)

```
DSCR = CFADS / DebtService
DebtService = principal_payment + interest_payment
```

### 10.4 Metryki (`calculateBankabilityMetrics` — bankability.js:355)

```
minDSCR:        min rocznych DSCR (dla lat z DebtService > 0)
avgDSCR:        średnia arytmetyczna rocznych DSCR
avgDSCRWeighted: Σ(CFADS) / Σ(DebtService)     ← średnia ważona
headroom:       (minDSCR / covenant) − 1        ← zapas powyżej covenantu (domyślnie 1.20)
yearsBelowCovenant: lista lat gdzie DSCR < covenant
```

**Do weryfikacji:**
- Czy CFADS jest PRZED obsługą długu (a nie po)?
- Czy grace period prawidłowo wpływa na DSCR (okres karencji = brak kapitału, ale odsetki)?
- Czy wymiana BESS/falownika jest odliczona od CFADS (jako CapEx maintenance)?

---

## 11. DEGRADACJA I REINVESTYCJE

### 11.1 Wymiana BESS (`calculateBessReplacementSchedule` — economics.js:168)

```
Co bessLifetimeYears (domyślnie 15 lat):
  Koszt = initialBessCapex × replacementCostValue × replacementFraction
  lub: bessEnergyKwh × replacementCostPerKwh × replacementFraction
```

### 11.2 Wymiana falownika (`calculateInverterReplacementSchedule` — economics.js:220)

```
Co inverterLifetimeYears (domyślnie 12 lat):
  Koszt = pvCapex × inverterReplacementCostPercent   (domyślnie 15%)
```

### 11.3 Wartość rezydualna (`calculateResidualValue` — economics.js:321)

```
zero:        wartość = 0
contractual: wartość = capacityKwp × contractualPerKwp (domyślnie 1 PLN/kWp)
fmv:         wartość = totalCapex × fmvPercent (domyślnie 20%)
```

---

## 12. KONWERSJA STÓP PROCENTOWYCH

```
nominalToReal(nominal, inflation) = (1+nominal)/(1+inflation) − 1
realToNominal(real, inflation)    = (1+real)×(1+inflation) − 1

Tryb nominalny: CF rosną z inflacją, dyskontowanie stopą nominalną
Tryb realny:    CF stałe, dyskontowanie stopą realną
Oba tryby powinny dawać identyczny NPV (Fisher equation)
```

**Do weryfikacji:**
- Czy portal poprawnie przełącza tryb nominalny/realny?
- Czy LCOE i inne metryki są spójne z wybranym trybem?

---

## 13. LISTA ŚWIĄT POLSKICH (używana w K-class)

Polskie święta ustawowo wolne od pracy (powinny być wyłączone z dni roboczych przy obliczaniu Δs):
- 1 stycznia (Nowy Rok)
- 6 stycznia (Trzech Króli)
- Wielkanoc (zmienna data) — poniedziałek wielkanocny
- 1 maja (Święto Pracy)
- 3 maja (Święto Konstytucji)
- Boże Ciało (zmienna, 60 dni po Wielkanocy)
- 15 sierpnia (Wniebowzięcie NMP)
- 1 listopada (Wszystkich Świętych)
- 11 listopada (Święto Niepodległości)
- 25–26 grudnia (Boże Narodzenie)

**Do weryfikacji:**
- Czy Wielkanoc i Boże Ciało są poprawnie obliczane algorytmicznie?
- Czy Wielki Piątek NIE jest świętem ustawowym (nie powinien być wyłączony)?

---

## ZNANE OGRANICZENIA I APROKSYMACJE

1. **Macierz wrażliwości**: Formuła `(NPV+CAPEX) × multiplier − CAPEX` traktuje `NPV+CAPEX` jako PV(savings), ale pomija PV(OPEX). Błąd ~1-3% w ekstremalnych scenariuszach.

2. **EaaS Tornado — Yield PV**: Stosuje liniowy mnożnik do baseSavings. W fazie ownership (stałe koszty O&M) efekt powinien być nieliniowy. Wpływ mały jeśli marża ownership >> O&M.

3. **Średnie wagi ToU**: three_zone: 35/25/40% — założone na typowy profil przemysłowy. Rzeczywiste proporcje zależą od konkretnego profilu zużycia.

4. **Opłata mocowa jako stała stawka**: `calculateTotalEnergyPrice` dodaje opłatę mocową jako stałą stawkę PLN/MWh. W rzeczywistości zależy ona od klasy K i godzin wybranych. TCSL backend oblicza ją prawidłowo godzinowo.

5. **EaaS NPV po kontrakcie**: `calculateEaaSNPV` (prosta wersja) ustawia costs=0 po kontrakcie. Master function `calculateCentralizedFinancialMetrics` poprawnie nalicza O&M+ubezpieczenie po kontrakcie.

---

## ZADANIE DLA AUDYTORA

Proszę o:

1. **Weryfikację matematyczną** — czy formuły NPV, IRR, LCOE, DPP są poprawne ekonomicznie?
2. **Weryfikację spójności** — czy te same parametry dają te same wyniki w różnych funkcjach (np. `calculateCapexNPV` vs `calculateCentralizedFinancialMetrics`)?
3. **Weryfikację jednostek** — czy konwersje kWh↔MWh, PLN↔tys.PLN↔mln PLN są poprawne?
4. **Weryfikację regulacyjną** — czy klasy K, godziny wybrane, stawka SOM, lista świąt są zgodne z polskimi przepisami?
5. **Identyfikację ryzyk** — czy są scenariusze brzegowe (division by zero, ujemne ceny RDN, brak danych) które mogą dać błędne wyniki?
6. **Ocenę aproksymacji** — czy znane uproszczenia (macierz wrażliwości, EaaS tornado) wprowadzają akceptowalny błąd?
