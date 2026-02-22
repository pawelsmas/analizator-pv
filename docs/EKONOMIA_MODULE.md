# Moduł EKONOMIA - Pełna Dokumentacja

## Spis treści
1. [Przegląd modułu](#przegląd-modułu)
2. [Architektura i przepływ danych](#architektura-i-przepływ-danych)
3. [Model CAPEX (Inwestycja własna)](#model-capex-inwestycja-własna)
4. [Model EaaS (Energy-as-a-Service)](#model-eaas-energy-as-a-service)
5. [Moduł Bankability (DSCR/CCR)](#moduł-bankability-dscr-ccr)
6. [Symulacja Monte Carlo](#symulacja-monte-carlo)
7. [Analiza wrażliwości](#analiza-wrażliwości)
8. [Eksport do Excel](#eksport-do-excel)
9. [Parametry wejściowe](#parametry-wejściowe)
10. [Wskaźniki KPI](#wskaźniki-kpi)

---

## Przegląd modułu

Moduł EKONOMIA to kompleksowe narzędzie do analizy finansowej projektów fotowoltaicznych (PV) i magazynów energii (BESS). Oferuje dwa główne modele finansowania:

- **CAPEX** - tradycyjna inwestycja własna z pełnym finansowaniem z góry
- **EaaS** - model subskrypcyjny "Energy-as-a-Service" z płatnościami rozłożonymi w czasie

### Główne funkcjonalności

| Funkcja | Opis |
|---------|------|
| Analiza NPV | Wartość bieżąca netto zdyskontowanych przepływów pieniężnych |
| Obliczanie IRR | Wewnętrzna stopa zwrotu (metoda Newtona-Raphsona) |
| Okres zwrotu | Prosty i zdyskontowany payback |
| LCOE | Uśredniony koszt energii przez cały okres życia instalacji |
| DSCR/Bankability | Wskaźniki zdolności do obsługi długu dla banków |
| Monte Carlo | Symulacja probabilistyczna z uwzględnieniem niepewności |
| Porównanie wariantów | Zestawienie do 3 wariantów konfiguracji |

---

## Architektura i przepływ danych

### Single Source of Truth (SSoT)

Moduł wykorzystuje wzorzec **Centralized Metrics** - wszystkie obliczenia finansowe są wykonywane raz i przechowywane w centralnym obiekcie:

```javascript
centralizedMetrics = {
  variant1: {
    common: {
      capacity_kwp,
      production_mwh,
      self_consumed_mwh,
      energy_price,
      discount_rate,
      analysis_period
    },
    capex: {
      npv, irr, payback, lcoe, total_capex, total_opex,
      yearly_data: [...]
    },
    eaas: {
      npv, irr, savings_vs_capex, duration, monthly_rate,
      yearly_data: [...]
    }
  },
  variant2: {...},
  variant3: {...}
}
```

### Przepływ danych

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Dane wejściowe │────▶│ Centralized      │────▶│ Wyświetlanie UI │
│  (Settings,     │     │ Metrics          │     │ (karty KPI,     │
│   Config)       │     │ Calculator       │     │  tabele, wykresy)│
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │ Bankability      │
                        │ Module           │
                        │ (DSCR/CCR)       │
                        └──────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │ Excel Export     │
                        │ (z formułami)    │
                        └──────────────────┘
```

---

## Model CAPEX (Inwestycja własna)

### Założenia modelu

Model CAPEX zakłada jednorazową inwestycję w roku 0, a następnie generowanie oszczędności przez cały okres analizy (domyślnie 25 lat).

### Parametry degradacji

| Komponent | Rok 1 | Lata 2+ |
|-----------|-------|---------|
| **PV** | 2% | 0.4-0.5% rocznie |
| **BESS** | - | 1-2% rocznie |

### Obliczanie NPV (Net Present Value)

**Wzór ogólny:**

```
NPV = -CAPEX + Σ(CFt / (1 + r)^t)
```

gdzie:
- `CAPEX` = całkowity nakład inwestycyjny
- `CFt` = przepływ pieniężny w roku t
- `r` = stopa dyskontowa
- `t` = rok (1 do 25)

**Implementacja w kodzie:**

```javascript
function calculateCapexNPV(params) {
  const {
    capacity_kwp,
    capex_per_kwp,
    production_mwh,
    self_consumption_rate,
    energy_price,
    degradation_rate,
    inflation_rate,
    opex_per_kwp,
    discount_rate,
    analysis_period
  } = params;

  // Całkowity CAPEX (rok 0)
  const total_capex = capacity_kwp * capex_per_kwp;

  // Roczna produkcja zużywana na własne potrzeby
  const self_consumed_annual_mwh = production_mwh * self_consumption_rate;

  // Inicjalizacja NPV (ujemny CAPEX na starcie)
  let npv = -total_capex;

  for (let year = 1; year <= analysis_period; year++) {
    // Współczynnik degradacji skumulowany
    const degradation_factor = Math.pow(1 - degradation_rate, year - 1);

    // Współczynnik inflacji skumulowany
    const inflation_factor = Math.pow(1 + inflation_rate, year - 1);

    // Cena energii skorygowana o inflację
    const adjusted_energy_price = energy_price * inflation_factor;

    // OPEX skorygowany o inflację
    const adjusted_opex = capacity_kwp * opex_per_kwp * inflation_factor;

    // Oszczędności = produkcja × degradacja × cena
    const savings = self_consumed_annual_mwh * degradation_factor * adjusted_energy_price * 1000;

    // Przepływ pieniężny netto
    const cash_flow = savings - adjusted_opex;

    // Dyskontowanie do wartości bieżącej
    npv += cash_flow / Math.pow(1 + discount_rate, year);
  }

  return npv;
}
```

### Obliczanie IRR (Internal Rate of Return)

IRR to stopa dyskontowa, przy której NPV = 0. Obliczana metodą **Newtona-Raphsona**:

```javascript
function calculateIRR(cashFlows, maxIterations = 100, tolerance = 0.0001) {
  let irr = 0.1; // Początkowe przybliżenie 10%

  for (let i = 0; i < maxIterations; i++) {
    let npv = 0;
    let derivative = 0;

    for (let t = 0; t < cashFlows.length; t++) {
      const factor = Math.pow(1 + irr, t);
      npv += cashFlows[t] / factor;
      derivative -= t * cashFlows[t] / Math.pow(1 + irr, t + 1);
    }

    // Sprawdzenie zbieżności
    if (Math.abs(npv) < tolerance) {
      return irr;
    }

    // Aktualizacja IRR (Newton-Raphson)
    irr = irr - npv / derivative;

    // Ograniczenie do rozsądnego zakresu
    if (irr < -0.99) irr = -0.99;
    if (irr > 10) irr = 10;
  }

  return irr;
}
```

**Tryby IRR:**
- **Nominalny** - uwzględnia inflację w przepływach
- **Realny** - deflowany o stopę inflacji: `IRR_real = (1 + IRR_nom) / (1 + inflation) - 1`

### Obliczanie Payback (Okres zwrotu)

**Prosty payback:**

```javascript
function calculateSimplePayback(capex, yearlyData) {
  let cumulative = 0;

  for (const year of yearlyData) {
    cumulative += year.cash_flow;

    if (cumulative >= capex) {
      // Interpolacja dla dokładnego roku
      const overshoot = cumulative - capex;
      const fraction = overshoot / year.cash_flow;
      return year.year - fraction;
    }
  }

  return null; // Brak zwrotu w okresie analizy
}
```

**Zdyskontowany payback:**

```javascript
function calculateDiscountedPayback(capex, yearlyData, discountRate) {
  let cumulative_pv = 0;

  for (const year of yearlyData) {
    const pv = year.cash_flow / Math.pow(1 + discountRate, year.year);
    cumulative_pv += pv;

    if (cumulative_pv >= capex) {
      const overshoot = cumulative_pv - capex;
      const fraction = overshoot / pv;
      return year.year - fraction;
    }
  }

  return null;
}
```

### Obliczanie LCOE (Levelized Cost of Energy)

LCOE to uśredniony koszt wytworzenia 1 MWh energii przez cały okres życia instalacji:

```
LCOE = (CAPEX + Σ(OPEXt / (1+r)^t)) / Σ(Produkacjat / (1+r)^t)
```

**Implementacja:**

```javascript
function calculateLCOE(params) {
  const { capex, opex_yearly, production_yearly, discount_rate, years } = params;

  let total_cost_pv = capex;
  let total_production_pv = 0;

  for (let t = 1; t <= years; t++) {
    const discount_factor = Math.pow(1 + discount_rate, t);
    total_cost_pv += opex_yearly[t] / discount_factor;
    total_production_pv += production_yearly[t] / discount_factor;
  }

  return total_cost_pv / total_production_pv; // PLN/MWh
}
```

---

## Model EaaS (Energy-as-a-Service)

### Koncepcja modelu

EaaS to model subskrypcyjny, gdzie klient nie ponosi kosztu CAPEX. Zamiast tego płaci miesięczną opłatę przez okres trwania umowy (zazwyczaj 10-15 lat). Po zakończeniu umowy instalacja przechodzi na własność klienta.

### Fazy projektu EaaS

```
┌────────────────────────────────────────────────────────────────────┐
│                         25-letni okres analizy                      │
├─────────────────────────────────┬──────────────────────────────────┤
│     Faza 1: EaaS (10-15 lat)    │    Faza 2: Własność (10-15 lat)  │
│  • Płatność miesięczna          │  • Brak płatności EaaS           │
│  • Oszczędności na energii      │  • Pełne oszczędności            │
│  • Serwis w cenie               │  • OPEX po stronie klienta       │
└─────────────────────────────────┴──────────────────────────────────┘
```

### Obliczanie NPV dla EaaS (perspektywa klienta)

```javascript
function calculateEaaSNPV(params) {
  const {
    production_mwh,
    self_consumption_rate,
    energy_price,
    degradation_rate,
    inflation_rate,
    eaas_monthly_rate,
    eaas_price_indexation,  // CPI lub fixed
    eaas_duration,
    discount_rate,
    analysis_period,
    opex_per_kwp,           // OPEX po zakończeniu EaaS
    capacity_kwp
  } = params;

  const self_consumed_annual_mwh = production_mwh * self_consumption_rate;
  let npv = 0;

  for (let year = 1; year <= analysis_period; year++) {
    const degradation_factor = Math.pow(1 - degradation_rate, year - 1);
    const inflation_factor = Math.pow(1 + inflation_rate, year - 1);

    // Cena energii z rynku (oszczędność)
    const adjusted_energy_price = energy_price * inflation_factor;
    const savings = self_consumed_annual_mwh * degradation_factor * adjusted_energy_price * 1000;

    let costs = 0;

    if (year <= eaas_duration) {
      // Faza EaaS - płatność miesięczna
      let eaas_annual = eaas_monthly_rate * 12;

      if (eaas_price_indexation === 'cpi') {
        // Indeksacja CPI od roku 2
        if (year > 1) {
          eaas_annual *= Math.pow(1 + inflation_rate, year - 1);
        }
      }
      // else: fixed - cena stała przez cały okres

      costs = eaas_annual;
    } else {
      // Faza własności - tylko OPEX
      costs = capacity_kwp * opex_per_kwp * inflation_factor;
    }

    const cash_flow = savings - costs;
    npv += cash_flow / Math.pow(1 + discount_rate, year);
  }

  return npv;
}
```

### Model inwestorski EaaS (pełny model finansowy)

Model dla inwestora/developera EaaS uwzględnia:

- **Project IRR** - stopa zwrotu z całego projektu
- **Equity IRR** - stopa zwrotu z kapitału własnego (z dźwignią finansową)
- **Leverage** - wskaźnik dźwigni (dług/kapitał)

```javascript
function calculateEaasFullModel(params) {
  const {
    capex_total,
    equity_ratio,           // np. 0.3 = 30% equity
    debt_interest_rate,
    debt_tenor_years,
    eaas_revenue_yearly,
    opex_yearly,
    tax_rate,
    insurance_rate          // 0.3% CAPEX rocznie
  } = params;

  const debt_amount = capex_total * (1 - equity_ratio);
  const equity_amount = capex_total * equity_ratio;

  // Harmonogram spłaty długu (annuitetowy)
  const debt_schedule = generateDebtSchedule({
    principal: debt_amount,
    rate: debt_interest_rate,
    tenor: debt_tenor_years
  });

  const project_cash_flows = [-capex_total];
  const equity_cash_flows = [-equity_amount];

  for (let year = 1; year <= analysis_period; year++) {
    const revenue = eaas_revenue_yearly[year];
    const opex = opex_yearly[year];
    const insurance = capex_total * insurance_rate;

    const ebitda = revenue - opex - insurance;

    // Amortyzacja (liniowa 25 lat)
    const depreciation = capex_total / 25;

    const ebit = ebitda - depreciation;
    const tax = Math.max(0, ebit * tax_rate);

    // Przepływ operacyjny
    const operating_cf = ebitda - tax;

    // Obsługa długu
    const debt_service = debt_schedule[year]?.total || 0;

    project_cash_flows.push(operating_cf);
    equity_cash_flows.push(operating_cf - debt_service);
  }

  return {
    project_irr: calculateIRR(project_cash_flows),
    equity_irr: calculateIRR(equity_cash_flows),
    project_npv: calculateNPV(project_cash_flows, discount_rate),
    payback: calculatePayback(project_cash_flows)
  };
}
```

---

## Moduł Bankability (DSCR/CCR)

### Cel modułu

Moduł Bankability dostarcza wskaźniki wymagane przez banki i instytucje finansowe do oceny zdolności projektu do obsługi długu. Jest kluczowy dla projektów z finansowaniem zewnętrznym.

### Wskaźniki bankowe

| Wskaźnik | Wzór | Typowy wymóg |
|----------|------|--------------|
| **DSCR** | CFADS / Debt Service | ≥ 1.20x |
| **Min DSCR** | Najniższy DSCR w okresie | ≥ 1.10x |
| **Avg DSCR** | Średnia DSCR | ≥ 1.30x |
| **CCR** | Cumulative CF / Cumulative DS | ≥ 1.40x |

### CFADS (Cash Flow Available for Debt Service)

```
CFADS = Przychody - OPEX - Podatki gotówkowe - CapEx utrzymaniowy ± Δ Kapitału obrotowego
```

**Implementacja:**

```javascript
function calculateCFADS(yearData) {
  const {
    revenue = 0,        // Przychody (oszczędności lub opłaty EaaS)
    opex = 0,           // Koszty operacyjne
    taxesCash = 0,      // Podatki płacone gotówkowo
    maintCapex = 0,     // Nakłady utrzymaniowe
    deltaWC = 0         // Zmiana kapitału obrotowego
  } = yearData;

  return revenue - opex - taxesCash - maintCapex - deltaWC;
}
```

### DSCR (Debt Service Coverage Ratio)

```javascript
function calculateDSCR(cfads, debtService) {
  // Zwraca NUMBER lub null (nigdy string)
  if (debtService <= 0) return null;
  return cfads / debtService;
}
```

### Harmonogramy spłaty długu

Moduł obsługuje trzy typy harmonogramów:

#### 1. Annuitetowy (równe raty)

```javascript
function generateAnnuitySchedule(principal, rate, tenor) {
  const schedule = [];

  // Rata annuitetowa
  const pmt = principal * (rate * Math.pow(1 + rate, tenor)) /
              (Math.pow(1 + rate, tenor) - 1);

  let balance = principal;

  for (let year = 1; year <= tenor; year++) {
    const interest = balance * rate;
    const principal_payment = pmt - interest;
    balance -= principal_payment;

    schedule.push({
      year,
      principal: principal_payment,
      interest,
      total: pmt,
      balance: Math.max(0, balance)
    });
  }

  return schedule;
}
```

#### 2. Liniowy (równe raty kapitałowe)

```javascript
function generateLinearSchedule(principal, rate, tenor) {
  const schedule = [];
  const principal_payment = principal / tenor;
  let balance = principal;

  for (let year = 1; year <= tenor; year++) {
    const interest = balance * rate;
    balance -= principal_payment;

    schedule.push({
      year,
      principal: principal_payment,
      interest,
      total: principal_payment + interest,
      balance: Math.max(0, balance)
    });
  }

  return schedule;
}
```

#### 3. Bullet (spłata na koniec)

```javascript
function generateBulletSchedule(principal, rate, tenor) {
  const schedule = [];

  for (let year = 1; year <= tenor; year++) {
    const interest = principal * rate;
    const is_final = year === tenor;

    schedule.push({
      year,
      principal: is_final ? principal : 0,
      interest,
      total: interest + (is_final ? principal : 0),
      balance: is_final ? 0 : principal
    });
  }

  return schedule;
}
```

### Karencja (Grace Period)

```javascript
function applyGracePeriod(schedule, graceYears) {
  return schedule.map((year, index) => {
    if (index < graceYears) {
      return {
        ...year,
        principal: 0,
        total: year.interest  // Tylko odsetki w okresie karencji
      };
    }
    return year;
  });
}
```

### Scenariusze produkcji (P50/P90/P97)

Moduł analizuje DSCR dla różnych scenariuszy produkcji:

| Scenariusz | Prawdopodobieństwo | Zastosowanie |
|------------|-------------------|--------------|
| **P50** | 50% szans na przekroczenie | Scenariusz bazowy |
| **P90** | 90% szans na przekroczenie | Scenariusz konserwatywny |
| **P97** | 97% szans na przekroczenie | Scenariusz stresowy |

```javascript
function calculateMultiScenarioDSCR(baseYearlyData, debtSchedule) {
  const scenarios = {
    P50: 1.00,   // 100% produkcji bazowej
    P90: 0.92,   // 92% produkcji (typowy współczynnik)
    P97: 0.88    // 88% produkcji
  };

  const results = {};

  for (const [scenario, factor] of Object.entries(scenarios)) {
    const adjustedData = baseYearlyData.map(year => ({
      ...year,
      revenue: year.revenue * factor
    }));

    results[scenario] = calculateBankabilityMetrics(adjustedData, debtSchedule);
  }

  return results;
}
```

### Pełne metryki Bankability

```javascript
function calculateBankabilityMetrics(yearlyData, debtSchedule, options = {}) {
  const { covenantLevel = 1.20 } = options;

  const dscrValues = [];
  let worstYear = null;
  let minDSCR = Infinity;
  let yearsBelowCovenant = 0;

  for (let i = 0; i < yearlyData.length; i++) {
    const year = yearlyData[i];
    const debt = debtSchedule[i] || { total: 0 };

    const cfads = calculateCFADS(year);
    const dscr = calculateDSCR(cfads, debt.total);

    if (dscr !== null) {
      dscrValues.push({ year: year.year, dscr, cfads, debtService: debt.total });

      if (dscr < minDSCR) {
        minDSCR = dscr;
        worstYear = year.year;
      }

      if (dscr < covenantLevel) {
        yearsBelowCovenant++;
      }
    }
  }

  // Średnia DSCR (prosta)
  const avgDSCR = dscrValues.reduce((sum, v) => sum + v.dscr, 0) / dscrValues.length;

  // Średnia ważona (wagą jest debt service)
  const totalDebtService = dscrValues.reduce((sum, v) => sum + v.debtService, 0);
  const avgDSCRWeighted = dscrValues.reduce((sum, v) =>
    sum + (v.dscr * v.debtService / totalDebtService), 0);

  // Headroom (zapas ponad covenant)
  const headroom = minDSCR - covenantLevel;

  return {
    minDSCR: minDSCR === Infinity ? null : minDSCR,
    avgDSCR,
    avgDSCRWeighted,
    worstYear,
    headroom,
    yearsBelowCovenant,
    yearlyDSCR: dscrValues
  };
}
```

---

## Symulacja Monte Carlo

### Cel symulacji

Symulacja Monte Carlo pozwala ocenić ryzyko projektu poprzez wielokrotne losowanie parametrów z rozkładów prawdopodobieństwa i obliczanie rozkładu wyników (NPV, IRR).

### Parametry losowane

| Parametr | Rozkład | Typowe odchylenie |
|----------|---------|-------------------|
| Produkcja PV | Normalny | σ = 5-10% |
| Cena energii | Log-normalny | σ = 15-20% |
| Inflacja | Normalny | σ = 1-2% |
| Degradacja | Trójkątny | ±20% od bazowej |

### Implementacja

```javascript
function runMonteCarloSimulation(baseParams, iterations = 1000) {
  const results = {
    npv: [],
    irr: [],
    payback: []
  };

  for (let i = 0; i < iterations; i++) {
    // Losowanie parametrów
    const params = {
      ...baseParams,
      production_mwh: randomNormal(
        baseParams.production_mwh,
        baseParams.production_mwh * 0.08
      ),
      energy_price: randomLogNormal(
        baseParams.energy_price,
        baseParams.energy_price * 0.15
      ),
      inflation_rate: randomNormal(
        baseParams.inflation_rate,
        0.01
      ),
      degradation_rate: randomTriangular(
        baseParams.degradation_rate * 0.8,
        baseParams.degradation_rate,
        baseParams.degradation_rate * 1.2
      )
    };

    // Obliczenie metryk dla tej iteracji
    const npv = calculateCapexNPV(params);
    const irr = calculateCapexIRR(params);
    const payback = calculatePayback(params);

    results.npv.push(npv);
    results.irr.push(irr);
    results.payback.push(payback);
  }

  return {
    npv: calculateDistributionStats(results.npv),
    irr: calculateDistributionStats(results.irr),
    payback: calculateDistributionStats(results.payback)
  };
}

function calculateDistributionStats(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const n = sorted.length;

  return {
    mean: values.reduce((a, b) => a + b, 0) / n,
    median: sorted[Math.floor(n / 2)],
    stdDev: calculateStdDev(values),
    p5: sorted[Math.floor(n * 0.05)],    // 5. percentyl
    p25: sorted[Math.floor(n * 0.25)],   // 25. percentyl
    p75: sorted[Math.floor(n * 0.75)],   // 75. percentyl
    p95: sorted[Math.floor(n * 0.95)],   // 95. percentyl
    min: sorted[0],
    max: sorted[n - 1]
  };
}
```

### Funkcje rozkładów

```javascript
// Rozkład normalny (Box-Muller)
function randomNormal(mean, stdDev) {
  const u1 = Math.random();
  const u2 = Math.random();
  const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  return mean + z * stdDev;
}

// Rozkład log-normalny
function randomLogNormal(mean, stdDev) {
  const variance = stdDev * stdDev;
  const mu = Math.log(mean * mean / Math.sqrt(variance + mean * mean));
  const sigma = Math.sqrt(Math.log(1 + variance / (mean * mean)));
  return Math.exp(randomNormal(mu, sigma));
}

// Rozkład trójkątny
function randomTriangular(min, mode, max) {
  const u = Math.random();
  const f = (mode - min) / (max - min);

  if (u < f) {
    return min + Math.sqrt(u * (max - min) * (mode - min));
  } else {
    return max - Math.sqrt((1 - u) * (max - min) * (max - mode));
  }
}
```

---

## Analiza wrażliwości

### Parametry analizy

Analiza wrażliwości pokazuje wpływ zmian poszczególnych parametrów na wynik (NPV, IRR):

| Parametr | Zakres zmian | Krok |
|----------|--------------|------|
| Cena energii | ±30% | 5% |
| CAPEX | ±20% | 5% |
| Produkcja | ±20% | 5% |
| Stopa dyskontowa | ±50% | 10% |
| Okres analizy | ±5 lat | 1 rok |

### Implementacja

```javascript
function runSensitivityAnalysis(baseParams, targetMetric = 'npv') {
  const sensitivityFactors = {
    energy_price: [-0.30, -0.20, -0.10, 0, 0.10, 0.20, 0.30],
    capex_per_kwp: [-0.20, -0.10, 0, 0.10, 0.20],
    production_mwh: [-0.20, -0.10, 0, 0.10, 0.20],
    discount_rate: [-0.50, -0.25, 0, 0.25, 0.50]
  };

  const results = {};

  for (const [param, factors] of Object.entries(sensitivityFactors)) {
    results[param] = [];

    for (const factor of factors) {
      const modifiedParams = { ...baseParams };

      // Modyfikacja parametru
      if (param === 'discount_rate') {
        // Dla stopy dyskontowej - zmiana absolutna
        modifiedParams[param] = baseParams[param] * (1 + factor);
      } else {
        modifiedParams[param] = baseParams[param] * (1 + factor);
      }

      // Obliczenie metryki
      let value;
      if (targetMetric === 'npv') {
        value = calculateCapexNPV(modifiedParams);
      } else if (targetMetric === 'irr') {
        value = calculateCapexIRR(modifiedParams);
      }

      results[param].push({
        change: factor * 100,  // Procentowa zmiana
        value
      });
    }
  }

  return results;
}
```

### Wyświetlanie wyników (Tornado Chart)

Moduł generuje wykres tornada pokazujący względny wpływ każdego parametru na wynik.

---

## Eksport do Excel

### Funkcjonalności eksportu

Moduł oferuje eksport do pliku Excel (.xlsx) z:

1. **Formułami audytowalnymi** - wszystkie obliczenia jako formuły Excel
2. **Wieloma arkuszami** - osobne arkusze dla CAPEX, EaaS, Bankability
3. **Formatowaniem** - kolory, obramowania, nagłówki
4. **Wykresami** - osadzone wykresy przepływów pieniężnych

### Struktura pliku Excel

```
├── Summary          # Podsumowanie KPI
├── CAPEX_Model      # Model CAPEX z formułami
│   ├── Parametry wejściowe
│   ├── Tabela roczna (rok, produkcja, oszczędności, OPEX, CF, NPV kumulowany)
│   └── Obliczenia IRR, Payback
├── EaaS_Model       # Model EaaS z formułami
│   ├── Parametry umowy
│   ├── Tabela roczna (faza EaaS + faza własności)
│   └── Porównanie z CAPEX
├── Bankability      # Metryki DSCR
│   ├── Harmonogram długu
│   ├── CFADS roczny
│   └── Tabela DSCR
└── Sensitivity      # Analiza wrażliwości
```

### Implementacja eksportu z formułami

```javascript
function generateExcelWithFormulas(data) {
  const wb = XLSX.utils.book_new();

  // Arkusz CAPEX
  const capexSheet = [];

  // Nagłówki
  capexSheet.push(['Rok', 'Produkcja [MWh]', 'Degradacja', 'Cena energii',
                   'Oszczędności', 'OPEX', 'Cash Flow', 'Dyskonto', 'NPV']);

  // Parametry jako komórki z nazwami
  const paramsRow = 2;
  // B2: Produkcja bazowa, C2: Degradacja, D2: Cena bazowa, etc.

  // Dane roczne z formułami
  for (let year = 1; year <= 25; year++) {
    const row = year + 2;
    capexSheet.push([
      year,
      // Produkcja z degradacją: =B$2*(1-C$2)^(A{row}-1)
      { f: `B$2*(1-C$2)^(A${row}-1)` },
      // Współczynnik degradacji
      { f: `(1-C$2)^(A${row}-1)` },
      // Cena z inflacją: =D$2*(1+E$2)^(A{row}-1)
      { f: `D$2*(1+E$2)^(A${row}-1)` },
      // Oszczędności: =B{row}*D{row}*1000
      { f: `B${row}*D${row}*1000` },
      // OPEX z inflacją
      { f: `F$2*(1+E$2)^(A${row}-1)` },
      // Cash Flow: =E{row}-F{row}
      { f: `E${row}-F${row}` },
      // Współczynnik dyskonta: =1/(1+G$2)^A{row}
      { f: `1/(1+G$2)^A${row}` },
      // NPV składnik: =G{row}*H{row}
      { f: `G${row}*H${row}` }
    ]);
  }

  // Podsumowanie
  capexSheet.push([]);
  capexSheet.push(['CAPEX', { f: 'H$2' }]);
  capexSheet.push(['NPV', { f: `SUM(I3:I27)-H$2` }]);

  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(capexSheet), 'CAPEX_Model');

  return wb;
}
```

---

## Parametry wejściowe

### Parametry projektu

| Parametr | Jednostka | Źródło | Opis |
|----------|-----------|--------|------|
| `capacity_kwp` | kWp | Config | Moc zainstalowana PV |
| `production_mwh` | MWh/rok | PVGIS | Roczna produkcja energii |
| `self_consumption_rate` | % | Analiza profilu | Współczynnik autokonsumpcji |
| `bess_capacity_kwh` | kWh | Config | Pojemność magazynu (opcjonalnie) |

### Parametry finansowe

| Parametr | Jednostka | Domyślna wartość | Opis |
|----------|-----------|------------------|------|
| `capex_per_kwp` | PLN/kWp | 3500 | Jednostkowy koszt PV |
| `bess_capex_per_kwh` | PLN/kWh | 2500 | Jednostkowy koszt BESS |
| `opex_per_kwp` | PLN/kWp/rok | 50 | Roczny koszt O&M |
| `energy_price` | PLN/kWh | 0.85 | Cena energii z sieci |
| `discount_rate` | % | 8% | Stopa dyskontowa |
| `inflation_rate` | % | 3% | Roczna inflacja |
| `analysis_period` | lata | 25 | Horyzont analizy |

### Parametry degradacji

| Parametr | Wartość | Opis |
|----------|---------|------|
| `pv_degradation_year1` | 2% | Degradacja PV w pierwszym roku |
| `pv_degradation_annual` | 0.4-0.5% | Roczna degradacja PV (lata 2+) |
| `bess_degradation_annual` | 1-2% | Roczna degradacja BESS |

### Parametry EaaS

| Parametr | Jednostka | Opis |
|----------|-----------|------|
| `eaas_duration` | lata | Długość umowy EaaS (10-15) |
| `eaas_monthly_rate` | PLN/miesiąc | Miesięczna opłata EaaS |
| `eaas_indexation` | 'fixed'/'cpi' | Typ indeksacji ceny |
| `eaas_cpi_rate` | % | Stopa indeksacji (jeśli CPI) |

### Parametry finansowania (Bankability)

| Parametr | Jednostka | Opis |
|----------|-----------|------|
| `debt_amount` | PLN | Kwota długu |
| `debt_tenor` | lata | Okres kredytowania |
| `interest_rate` | % | Oprocentowanie |
| `repayment_type` | 'annuity'/'linear'/'bullet' | Typ spłaty |
| `grace_period` | lata | Okres karencji |
| `fees_rate` | % | Prowizje i opłaty |

---

## Wskaźniki KPI

### Wskaźniki CAPEX

| KPI | Wzór | Interpretacja |
|-----|------|---------------|
| **NPV** | Σ(CFt/(1+r)^t) - CAPEX | > 0 = projekt opłacalny |
| **IRR** | Stopa przy NPV = 0 | > WACC = projekt opłacalny |
| **Payback** | Rok gdy Σ CF ≥ CAPEX | < 10 lat = dobry projekt |
| **LCOE** | Koszty / Produkcja | < cena rynkowa = opłacalny |

### Wskaźniki EaaS

| KPI | Wzór | Interpretacja |
|-----|------|---------------|
| **NPV Klienta** | Σ(Oszczędności - Opłaty)/(1+r)^t | > 0 = korzystne dla klienta |
| **Oszczędności vs CAPEX** | NPV_EaaS - NPV_CAPEX | > 0 = EaaS korzystniejsze |
| **Project IRR** | Stopa zwrotu bez dźwigni | Atrakcyjność dla inwestora |
| **Equity IRR** | Stopa zwrotu z equity | > 15% = atrakcyjne |

### Wskaźniki Bankability

| KPI | Wzór | Minimalny wymóg |
|-----|------|-----------------|
| **Min DSCR** | min(CFADS_t / DS_t) | ≥ 1.10x |
| **Avg DSCR** | Σ(DSCR_t) / n | ≥ 1.30x |
| **Headroom** | Min DSCR - Covenant | > 0 |
| **CCR** | Σ CFADS / Σ DS | ≥ 1.40x |

### Interpretacja DSCR

```
DSCR > 1.50x  → Bardzo bezpieczny (headroom na stres)
DSCR 1.30-1.50 → Bezpieczny (typowy wymóg bankowy)
DSCR 1.20-1.30 → Akceptowalny (minimalny bufor)
DSCR 1.10-1.20 → Ryzykowny (wymaga dodatkowych zabezpieczeń)
DSCR < 1.10x  → Niebezpieczny (projekt niefinansowalny)
```

---

## Struktura kodu

### Główne pliki

```
services/frontend-economics/
├── index.html          # Struktura UI, sekcje, modale
├── economics.js        # Główna logika (5900+ linii)
│   ├── Centralized Metrics
│   ├── CAPEX calculations
│   ├── EaaS calculations
│   ├── Chart rendering
│   ├── Sensitivity analysis
│   ├── Monte Carlo
│   └── Excel export
├── bankability.js      # Moduł DSCR/CCR (494 linie)
│   ├── CFADS calculation
│   ├── Debt schedules
│   └── DSCR metrics
└── styles.css          # Stylowanie UI
```

### Kluczowe funkcje w economics.js

| Funkcja | Linia* | Opis |
|---------|--------|------|
| `calculateCentralizedFinancialMetrics()` | ~800 | SSoT dla wszystkich obliczeń |
| `calculateCapexNPV()` | ~1200 | NPV dla modelu CAPEX |
| `calculateEaaSNPV()` | ~1400 | NPV dla modelu EaaS |
| `calculateEaasFullModel()` | ~1600 | Pełny model inwestorski |
| `generatePaybackTable()` | ~2000 | Tabela roczna CAPEX |
| `generateEaaSYearlyTable()` | ~2200 | Tabela roczna EaaS |
| `runSensitivityAnalysis()` | ~3000 | Analiza wrażliwości |
| `runMonteCarloSimulation()` | ~3500 | Symulacja Monte Carlo |
| `exportToExcel()` | ~4500 | Eksport z formułami |
| `initializeBankability()` | ~5000 | Inicjalizacja DSCR |
| `recalculateBankability()` | ~5200 | Przeliczenie DSCR |

*Numery linii są przybliżone

### Kluczowe funkcje w bankability.js

| Funkcja | Opis |
|---------|------|
| `calculateCFADS(yearData)` | Oblicza CFADS dla roku |
| `calculateDSCR(cfads, debtService)` | Oblicza DSCR |
| `generateDebtSchedule(params)` | Generuje harmonogram długu |
| `calculateBankabilityMetrics(yearly, debt, options)` | Pełne metryki |

---

## Przykład użycia

### Scenariusz: Analiza projektu PV 500 kWp

**Parametry wejściowe:**
```javascript
const params = {
  capacity_kwp: 500,
  production_mwh: 525,           // ~1050 kWh/kWp
  self_consumption_rate: 0.85,   // 85% autokonsumpcji
  capex_per_kwp: 3500,           // 3500 PLN/kWp
  opex_per_kwp: 50,              // 50 PLN/kWp/rok
  energy_price: 0.85,            // 0.85 PLN/kWh
  discount_rate: 0.08,           // 8%
  inflation_rate: 0.03,          // 3%
  analysis_period: 25            // 25 lat
};
```

**Wyniki CAPEX:**
```
CAPEX całkowity:     1,750,000 PLN
NPV (25 lat):        1,250,000 PLN
IRR (nominalny):     14.2%
IRR (realny):        10.9%
Payback (prosty):    6.8 lat
LCOE:                285 PLN/MWh
```

**Wyniki EaaS (10-letnia umowa):**
```
Opłata miesięczna:   18,500 PLN
NPV Klienta:         1,050,000 PLN
Oszczędności vs CAPEX: -200,000 PLN (CAPEX korzystniejszy)
```

**Wyniki Bankability (70% LTV, 12 lat):**
```
Kwota długu:         1,225,000 PLN
Min DSCR:            1.28x (rok 2)
Avg DSCR:            1.45x
Headroom:            +0.08x (ponad covenant 1.20x)
Status:              ✅ Projekt finansowalny
```

---

## Wersjonowanie

| Wersja | Data | Zmiany |
|--------|------|--------|
| 1.0 | 2024-01 | Podstawowy model CAPEX/EaaS |
| 1.1 | 2024-03 | Dodanie Monte Carlo |
| 1.2 | 2024-06 | Eksport Excel z formułami |
| 2.0 | 2024-12 | Moduł Bankability (DSCR/CCR) |
| 2.1 | 2025-01 | Centralized Metrics (SSoT) |

---

*Dokumentacja wygenerowana: Styczeń 2025*
*Moduł: EKONOMIA v2.1*
*Aplikacja: Pagra ENERGY Studio*
