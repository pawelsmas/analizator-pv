# Dokumentacja Techniczna Modułu Monte Carlo
## Symulacja Stochastyczna Ryzyka Finansowego PV/BESS

**Wersja:** 1.0
**Data:** 2025-12-24
**Autor:** Analizator PV
**Engine Version:** 1.0.0
**Frontend Version:** 1.1.0
**Service:** pv-economics (port 8003)

---

## Spis Treści

1. [Przegląd Systemu](#1-przegląd-systemu)
2. [Teoria Monte Carlo](#2-teoria-monte-carlo)
3. [Parametry i Rozkłady](#3-parametry-i-rozkłady)
4. [Algorytm Symulacji](#4-algorytm-symulacji)
5. [Korelacje między Parametrami](#5-korelacje-między-parametrami)
6. [Metryki Ryzyka](#6-metryki-ryzyka)
7. [API i Endpointy](#7-api-i-endpointy)
8. [Interpretacja Wyników](#8-interpretacja-wyników)
9. [Przykłady Obliczeń](#9-przykłady-obliczeń)
10. [Ograniczenia i Założenia](#10-ograniczenia-i-założenia)

---

## 1. Przegląd Systemu

### 1.1 Cel Modułu

Moduł Monte Carlo służy do **oceny ryzyka finansowego** inwestycji fotowoltaicznych i magazynów energii. Zamiast pojedynczej deterministycznej wartości NPV/IRR, generuje **rozkład prawdopodobieństwa** możliwych wyników uwzględniając niepewność kluczowych parametrów.

### 1.2 Architektura

```
┌─────────────────────────────────────────────────────────────────┐
│                     MODUŁ MONTE CARLO                           │
├─────────────────────────────────────────────────────────────────┤
│  Backend: services/economics/monte_carlo/                       │
│  ├── models.py        - Modele Pydantic (request/response)      │
│  ├── distributions.py - Rozkłady prawdopodobieństwa             │
│  └── engine.py        - Silnik symulacji (NumPy vectorized)     │
├─────────────────────────────────────────────────────────────────┤
│  Frontend: services/frontend-economics/                         │
│  ├── monte-carlo.js   - Logika UI i wywołania API               │
│  └── index.html       - Sekcja Monte Carlo                      │
├─────────────────────────────────────────────────────────────────┤
│  API: /api/economics/monte-carlo/*                              │
│  ├── POST /monte-carlo       - Pełna symulacja                  │
│  ├── POST /monte-carlo/quick - Szybka symulacja (domyślne)      │
│  └── GET  /monte-carlo/presets - Presety konfiguracji           │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 Kluczowe Cechy

| Cecha | Opis |
|-------|------|
| **Wektoryzacja** | Obliczenia NumPy - 10,000 symulacji w ~20ms |
| **Korelacje** | Dekompozycja Cholesky'ego dla skorelowanych parametrów |
| **Rozkłady** | Normal, Lognormal, Triangular, Uniform |
| **Metryki** | NPV, IRR, Payback, VaR, CVaR, Sharpe ratio |
| **Insights** | Automatyczne wnioski w języku polskim |

---

## 2. Teoria Monte Carlo

### 2.1 Podstawy Metody

Symulacja Monte Carlo polega na:

1. **Zdefiniowaniu niepewnych parametrów** z ich rozkładami prawdopodobieństwa
2. **Losowaniu N zestawów wartości** z tych rozkładów (z uwzględnieniem korelacji)
3. **Obliczeniu wskaźników finansowych** dla każdego zestawu
4. **Analizie statystycznej** otrzymanych rozkładów wyników

```
       PARAMETRY WEJŚCIOWE                    WYNIKI
    ┌─────────────────────┐               ┌─────────────────┐
    │ Cena energii        │──┐            │ NPV rozkład     │
    │ σ = ±15%           │  │            │ P10, P50, P90   │
    ├─────────────────────┤  │            ├─────────────────┤
    │ Produkcja PV        │  │  N=10,000  │ IRR rozkład     │
    │ σ = ±10%           │──┼──────────► │ P10, P50, P90   │
    ├─────────────────────┤  │  symulacji ├─────────────────┤
    │ CAPEX               │  │            │ Payback rozkład │
    │ σ = ±10%           │──┤            │ P10, P50, P90   │
    ├─────────────────────┤  │            ├─────────────────┤
    │ Inflacja            │──┘            │ Metryki ryzyka  │
    │ σ = ±2pp           │               │ VaR, CVaR       │
    └─────────────────────┘               └─────────────────┘
```

### 2.2 Dlaczego Monte Carlo?

| Podejście deterministyczne | Podejście Monte Carlo |
|----------------------------|----------------------|
| NPV = 4.5 mln PLN | NPV: 2.1 - 6.8 mln PLN (P10-P90) |
| "Projekt opłacalny" | "95% szans na zysk, VaR₉₅ = 1.2 mln PLN" |
| Brak informacji o ryzyku | Pełna analiza ryzyka |

---

## 3. Parametry i Rozkłady

### 3.1 Parametry Symulowane

Moduł symuluje niepewność następujących parametrów:

| Parametr | Zmienna | Rozkład | Wartość bazowa | Niepewność |
|----------|---------|---------|----------------|------------|
| **Cena energii** | `electricity_price` | Normal | 450-782 PLN/MWh | ±15% |
| **Produkcja PV** | `production_factor` | Normal | 1.0 (mnożnik) | ±10% |
| **CAPEX** | `investment_cost` | Lognormal | 3500 PLN/kWp | ±10% |
| **Inflacja** | `inflation_rate` | Normal | 2.5% | ±2pp |
| **Degradacja** | `degradation_rate` | Triangular | 0.5%/rok | 0.3-0.8% |
| **Stopa dyskontowa** | `discount_rate` | Triangular | 7% | 5-10% |

### 3.2 Typy Rozkładów

#### Rozkład Normalny (Normal)
```
Użycie: Cena energii, produkcja PV, inflacja
Parametry: μ (średnia), σ (odchylenie standardowe)
Cechy: Symetryczny, może przyjmować wartości ujemne
```

**Wzór gęstości:**
```
f(x) = (1 / σ√2π) × exp(-(x-μ)² / 2σ²)
```

#### Rozkład Log-normalny (Lognormal)
```
Użycie: CAPEX (koszty są zawsze dodatnie)
Parametry: μ_ln, σ_ln (parametry ln(X))
Cechy: Asymetryczny, tylko wartości dodatnie
```

**Transformacja parametrów:**
```python
# Chcemy E[X] = base_value, Std[X] = std_dev
sigma_ln² = ln(1 + (std_dev / base_value)²)
mu_ln = ln(base_value) - sigma_ln² / 2
sigma_ln = sqrt(sigma_ln²)
```

#### Rozkład Trójkątny (Triangular)
```
Użycie: Degradacja, stopa dyskontowa (ekspertowe szacunki)
Parametry: a (min), b (max), c (moda)
Cechy: Ograniczony, intuicyjny dla ekspertów
```

#### Rozkład Jednostajny (Uniform)
```
Użycie: Gdy brak wiedzy o kształcie rozkładu
Parametry: a (min), b (max)
Cechy: Wszystkie wartości równie prawdopodobne
```

### 3.3 Profile Ryzyka (Presety)

Moduł oferuje trzy presety konfiguracji:

#### Umiarkowany (moderate) - Domyślny
```python
parameters = {
    "electricity_price": Normal(base=450, std_pct=15%),
    "production_factor": Normal(base=1.0, std_pct=10%),
    "investment_cost": Lognormal(base=3500, std_pct=10%),
    "inflation_rate": Normal(base=2.5%, std=2pp),
    "degradation_rate": Triangular(min=0.3%, mode=0.5%, max=0.8%),
    "discount_rate": Triangular(min=5%, mode=7%, max=10%),
}
```

#### Konserwatywny (conservative)
- Niższe wartości bazowe (cena 400 PLN/MWh, produkcja 0.95x)
- Wyższa niepewność (±20% dla ceny)
- Wyższy CAPEX bazowy (3800 PLN/kWp)
- Wyższa stopa dyskontowa (8%)

#### Optymistyczny (optimistic)
- Wyższe wartości bazowe (cena 500 PLN/MWh, produkcja 1.05x)
- Niższa niepewność (±10% dla ceny)
- Niższy CAPEX bazowy (3200 PLN/kWp)
- Niższa stopa dyskontowa (6%)

---

## 4. Algorytm Symulacji

### 4.1 Schemat Główny

```python
def run_simulation(n_simulations, parameters, correlations, base_economics):
    # 1. Generuj skorelowane próbki parametrów
    samples = generate_correlated_samples(parameters, correlations, n_simulations)

    # 2. Dla każdej symulacji oblicz przepływy pieniężne
    for sim in range(n_simulations):
        # Parametry dla tej symulacji
        price = samples["electricity_price"][sim]
        prod_factor = samples["production_factor"][sim]
        capex_per_kwp = samples["investment_cost"][sim]
        inflation = samples["inflation_rate"][sim]
        degradation = samples["degradation_rate"][sim]
        discount = samples["discount_rate"][sim]

        # Inwestycja
        investment = capacity * capex_per_kwp

        # Cash flow dla każdego roku
        npv = -investment
        for year in range(1, analysis_period + 1):
            # Degradacja
            degrad_factor = (1 - degradation) ** year

            # Produkcja z degradacją i niepewnością
            production = base_production * degrad_factor * prod_factor

            # Cena z inflacją
            price_year = price * (1 + inflation) ** year

            # Oszczędności
            savings = self_consumed * degrad_factor * prod_factor * price_year / 1000

            # OPEX z inflacją
            opex = capacity * opex_per_kwp * (1 + inflation) ** year

            # Cash flow
            net_cf = savings - opex

            # NPV contribution
            npv += net_cf / (1 + discount) ** year

        npv_results[sim] = npv

    # 3. Oblicz statystyki i metryki ryzyka
    return compute_statistics(npv_results, irr_results, payback_results)
```

### 4.2 Obliczenia NPV (Wektoryzowane)

```python
def _calculate_economics_vectorized(samples, variant, params, n_simulations):
    # Extract base data
    capacity = variant["capacity"]  # kWp
    base_production = variant["production"]  # kWh/rok
    self_consumed = variant["self_consumed"]  # kWh/rok

    # Get sampled arrays (shape: n_simulations)
    prices = samples["electricity_price"]        # PLN/MWh
    prod_factors = samples["production_factor"]  # mnożnik
    capex = samples["investment_cost"]           # PLN/kWp
    inflation = samples["inflation_rate"]        # decimal
    degradation = samples["degradation_rate"]    # decimal
    discount = samples["discount_rate"]          # decimal

    # Investment (Year 0)
    investments = capacity * capex  # PLN

    # Initialize results
    npv_results = -investments.copy()

    # Calculate for each year
    for year in range(1, analysis_period + 1):
        # Degradation factor (broadcast across simulations)
        degrad = (1 - degradation) ** year

        # Production with degradation and uncertainty
        production_year = base_production * degrad * prod_factors

        # Energy price with inflation
        price_year = prices * (1 + inflation) ** year

        # Self-consumption savings (kWh → MWh)
        self_cons_year = self_consumed * degrad * prod_factors
        savings = (self_cons_year / 1000) * price_year

        # OPEX with inflation
        opex = capacity * opex_per_kwp * (1 + inflation) ** year

        # Net cash flow
        net_cf = savings - opex

        # Discount factor
        df = (1 + discount) ** year

        # NPV contribution (vectorized)
        npv_results += net_cf / df

    return npv_results
```

### 4.3 Obliczenia IRR

IRR jest obliczane metodą **Newtona-Raphsona** zaimplementowaną wektorowo:

```python
def _estimate_irr_vectorized(cash_flows_matrix, max_iterations=50, tolerance=1e-4):
    """
    cash_flows_matrix: shape (n_simulations, n_years+1)
    cash_flows_matrix[:, 0] = -investment
    cash_flows_matrix[:, 1:] = annual cash flows
    """
    n_simulations, n_years = cash_flows_matrix.shape
    irr = np.full(n_simulations, 0.1)  # Initial guess: 10%

    years = np.arange(n_years)  # [0, 1, 2, ..., 25]

    for iteration in range(max_iterations):
        # NPV at current IRR guess (vectorized)
        discount_factors = (1 + irr[:, np.newaxis]) ** years
        npv = np.sum(cash_flows_matrix / discount_factors, axis=1)

        # Derivative of NPV
        dnpv = np.sum(
            -years * cash_flows_matrix / ((1 + irr[:, np.newaxis]) ** (years + 1)),
            axis=1
        )

        # Newton-Raphson step
        irr_new = irr - npv / dnpv

        # Clamp to reasonable range
        irr_new = np.clip(irr_new, -0.99, 10.0)

        # Check convergence
        converged = np.abs(npv) < tolerance
        irr = np.where(converged, irr, irr_new)

        if np.all(converged):
            break

    # Mark invalid IRRs
    irr[(irr < -0.99) | (irr > 5.0)] = np.nan

    return irr
```

---

## 5. Korelacje między Parametrami

### 5.1 Macierz Korelacji

Parametry ekonomiczne nie są niezależne. System uwzględnia następujące korelacje:

| Parametr 1 | Parametr 2 | Korelacja | Uzasadnienie |
|------------|------------|-----------|--------------|
| Cena energii | Inflacja | +0.6 | Wysoka inflacja → wyższe ceny energii |
| CAPEX | Produkcja | -0.2 | Efekt skali (większe systemy → niższy koszt/kWp) |
| Produkcja | Degradacja | -0.15 | Wysokowydajne panele mogą szybciej degradować |

### 5.2 Implementacja (Dekompozycja Cholesky'ego)

```python
def generate_correlated_samples(parameters, correlations, n_samples, random_seed=None):
    """
    Generuje skorelowane próbki używając dekompozycji Cholesky'ego.

    Metoda:
    1. Generuj niezależne próbki z rozkładu N(0,1)
    2. Zastosuj transformację Cholesky'ego aby wprowadzić korelacje
    3. Transformuj do docelowych rozkładów (inverse CDF)
    """
    n_params = len(parameters)

    # 1. Build correlation matrix
    corr_matrix = np.eye(n_params)  # Identity matrix
    for corr in correlations:
        i = param_index[corr.param1]
        j = param_index[corr.param2]
        corr_matrix[i, j] = corr.correlation
        corr_matrix[j, i] = corr.correlation

    # 2. Cholesky decomposition: Σ = L × L^T
    L = np.linalg.cholesky(corr_matrix)

    # 3. Generate independent standard normal samples
    z_independent = rng.standard_normal((n_params, n_samples))

    # 4. Apply correlation: z_correlated = L × z_independent
    z_correlated = L @ z_independent

    # 5. Transform to target distributions using inverse CDF
    samples = {}
    for i, param in enumerate(parameters):
        # Transform standard normal to uniform [0, 1]
        u = stats.norm.cdf(z_correlated[i, :])

        # Transform uniform to target distribution
        if param.dist_type == "normal":
            samples[param.name] = stats.norm.ppf(u, loc=param.base_value, scale=param.std_dev)
        elif param.dist_type == "lognormal":
            samples[param.name] = stats.lognorm.ppf(u, s=sigma_ln, scale=np.exp(mu_ln))
        # ... other distributions

    return samples
```

### 5.3 Wizualizacja Korelacji

```
         Cena    Prod    CAPEX   Inflacja
Cena     1.00    0.00   -0.00    0.60
Prod     0.00    1.00   -0.20   -0.00
CAPEX   -0.00   -0.20    1.00   -0.00
Inflacja 0.60   -0.00   -0.00    1.00
```

---

## 6. Metryki Ryzyka

### 6.1 Prawdopodobieństwo Zysku

```python
probability_positive = np.sum(npv_results > 0) / n_simulations
```

**Interpretacja:**
- > 95%: Bardzo wysoka pewność zysku
- 80-95%: Wysoka pewność
- 50-80%: Umiarkowane ryzyko
- < 50%: Wysokie ryzyko straty

### 6.2 Value at Risk (VaR)

**Definicja:** Maksymalna strata przy danym poziomie ufności.

```python
var_95 = np.percentile(npv_results, 5)   # 5-ty percentyl
var_99 = np.percentile(npv_results, 1)   # 1-szy percentyl
```

**Interpretacja:**
- VaR₉₅ = -500,000 PLN oznacza: "Z 95% prawdopodobieństwem strata nie przekroczy 500 tys. PLN"
- VaR₉₅ > 0 oznacza: "Nawet w najgorszych 5% scenariuszy NPV jest dodatnie"

### 6.3 Conditional VaR (CVaR / Expected Shortfall)

**Definicja:** Średnia strata w najgorszych X% scenariuszy.

```python
cvar_95 = np.mean(npv_results[npv_results <= var_95])
```

**Interpretacja:**
- CVaR₉₅ jest zawsze ≤ VaR₉₅
- Uwzględnia "ogon" rozkładu (skrajne straty)
- Preferowana metryka w regulacjach bankowych

### 6.4 Współczynnik Zmienności (CV)

```python
cv = np.std(npv_results) / np.abs(np.mean(npv_results))
```

**Interpretacja:**
- CV < 0.3: Niska zmienność (stabilne wyniki)
- CV 0.3-0.6: Umiarkowana zmienność
- CV > 0.6: Wysoka zmienność (duża niepewność)

### 6.5 Downside Risk (Semi-odchylenie)

**Definicja:** Odchylenie tylko dla wyników poniżej średniej.

```python
negative_deviations = np.minimum(npv_results - np.mean(npv_results), 0)
downside_risk = np.sqrt(np.mean(negative_deviations ** 2))
```

**Interpretacja:**
- Mierzy tylko "złe" odchylenia
- Bardziej odpowiednia dla asymetrycznych rozkładów

### 6.6 Sharpe Ratio (uproszczone)

```python
sharpe = np.mean(npv_results) / np.std(npv_results)
```

**Interpretacja:**
- Sharpe > 1: Dobry stosunek zysku do ryzyka
- Sharpe > 2: Bardzo dobry
- Sharpe < 0.5: Słaby

---

## 7. API i Endpointy

### 7.1 POST /api/economics/monte-carlo/quick

**Szybka symulacja z domyślnymi parametrami.**

**Request:**
```json
{
    "n_simulations": 5000,
    "electricity_price_uncertainty_pct": 15,
    "production_uncertainty_pct": 10,
    "capex_uncertainty_pct": 10,
    "inflation_uncertainty_pct": 2,
    "use_default_correlations": true,
    "base_economics": {
        "variant": {
            "capacity": 1700,
            "production": 1914260,
            "self_consumed": 981799,
            "exported": 932461,
            "auto_consumption_pct": 51.3,
            "coverage_pct": 25.4
        },
        "parameters": {
            "energy_price": 782,
            "feed_in_tariff": 0,
            "investment_cost": 3500,
            "export_mode": "zero",
            "discount_rate": 0.07,
            "degradation_rate": 0.005,
            "opex_per_kwp": 15,
            "analysis_period": 25,
            "inflation_rate": 0.025
        }
    }
}
```

**Response:**
```json
{
    "n_simulations": 5000,
    "parameters_analyzed": ["electricity_price", "production_factor", "investment_cost", "inflation_rate"],
    "computation_time_ms": 18.5,

    "npv_mean": 4470000,
    "npv_std": 1250000,
    "npv_percentiles": {
        "p5": 2100000,
        "p10": 2650000,
        "p25": 3600000,
        "p50": 4450000,
        "p75": 5350000,
        "p90": 6100000,
        "p95": 6800000
    },
    "npv_histogram": {
        "bins": [1500000, 2000000, ...],
        "counts": [12, 45, 89, ...],
        "bin_centers": [1750000, 2250000, ...]
    },

    "irr_mean": 0.142,
    "irr_std": 0.035,
    "irr_percentiles": { "p10": 0.098, "p50": 0.141, "p90": 0.187 },
    "irr_valid_pct": 99.8,

    "payback_mean": 7.2,
    "payback_percentiles": { "p10": 5.8, "p50": 7.1, "p90": 9.2 },

    "risk_metrics": {
        "probability_positive": 0.95,
        "var_95": 2100000,
        "var_99": 1500000,
        "cvar_95": 1800000,
        "expected_value": 4470000,
        "standard_deviation": 1250000,
        "coefficient_of_variation": 0.28,
        "downside_risk": 650000,
        "sharpe_ratio": 3.58
    },

    "insights": [
        "Bardzo wysoka pewność zysku: 95.0% symulacji daje dodatnie NPV",
        "Niska zmienność NPV - wyniki są stabilne",
        "VaR 95%: W najgorszych 5% scenariuszy NPV nadal dodatnie (2100 tys. PLN)",
        "IRR: mediana 14.1% (zakres P10-P90: 9.8% - 18.7%)",
        "Nawet w pesymistycznym scenariuszu (P10) IRR przekracza typową stopę dyskontową 7%",
        "Zwrot inwestycji: mediana 7.1 lat (90% przypadków < 9.2 lat)",
        "electricity_price silnie dodatnio skorelowany z NPV (r=0.78)"
    ],

    "breakeven_price": 285.5,

    "scenario_base": { "npv": 4450000, "irr": 0.141, "payback": 7.1 },
    "scenario_pessimistic": { "npv": 2650000, "irr": 0.098, "payback": 9.2 },
    "scenario_optimistic": { "npv": 6100000, "irr": 0.187, "payback": 5.8 }
}
```

### 7.2 GET /api/economics/monte-carlo/presets

**Zwraca dostępne presety konfiguracji.**

**Response:**
```json
{
    "moderate": {
        "name": "moderate",
        "description": "Umiarkowane założenia - domyślna konfiguracja",
        "parameters": [...],
        "correlations": [...]
    },
    "conservative": {
        "name": "conservative",
        "description": "Konserwatywne założenia - wyższa niepewność",
        "parameters": [...],
        "correlations": [...]
    },
    "optimistic": {
        "name": "optimistic",
        "description": "Optymistyczne założenia - niższa niepewność",
        "parameters": [...],
        "correlations": [...]
    }
}
```

### 7.3 POST /api/economics/monte-carlo

**Pełna symulacja z własną konfiguracją parametrów.**

**Request:**
```json
{
    "n_simulations": 10000,
    "parameters": [
        {
            "name": "electricity_price",
            "dist_type": "normal",
            "base_value": 500,
            "std_dev_pct": 20,
            "clip_min": 200,
            "clip_max": 1000
        },
        {
            "name": "production_factor",
            "dist_type": "triangular",
            "base_value": 1.0,
            "min_val": 0.85,
            "max_val": 1.15,
            "mode_val": 1.0
        }
    ],
    "correlations": [
        {
            "param1": "electricity_price",
            "param2": "inflation_rate",
            "correlation": 0.7
        }
    ],
    "base_economics": { ... },
    "return_distributions": false,
    "histogram_bins": 50,
    "random_seed": 42
}
```

---

## 8. Interpretacja Wyników

### 8.1 Scenariusze P10/P50/P90

| Scenariusz | Percentyl NPV | Interpretacja |
|------------|---------------|---------------|
| **Pesymistyczny (P10)** | 10-ty | 10% wyników jest gorszych |
| **Bazowy (P50)** | 50-ty (mediana) | Najbardziej prawdopodobny wynik |
| **Optymistyczny (P90)** | 90-ty | Tylko 10% wyników jest lepszych |

### 8.2 Przykład Interpretacji

```
Wyniki dla instalacji 1700 kWp:

NPV:
  P10 (pesymistyczny): 2.65 mln PLN
  P50 (mediana):       4.45 mln PLN
  P90 (optymistyczny): 6.10 mln PLN

Interpretacja:
- Mediana NPV wynosi 4.45 mln PLN
- Z 80% prawdopodobieństwem NPV będzie między 2.65 a 6.10 mln PLN
- Nawet w pesymistycznym scenariuszu (P10) NPV jest dodatnie

Prawdopodobieństwo zysku: 95%
- 95 na 100 losowych scenariuszy daje dodatnie NPV
- Tylko 5% scenariuszy skutkuje stratą

VaR 95% = 2.10 mln PLN (dodatnie!)
- Nawet w najgorszych 5% przypadków NPV wynosi co najmniej 2.10 mln PLN
- Inwestycja jest bardzo bezpieczna
```

### 8.3 Histogram NPV

```
    Scenariuszy
        │
   800  │          ████
        │        ████████
   600  │      ████████████
        │    ████████████████
   400  │  ████████████████████
        │████████████████████████
   200  │██████████████████████████
        │████████████████████████████
     0  │─────────────────────────────────────────
        0    1    2    3    4    5    6    7    8
                      NPV [mln PLN]

        █ NPV > 0 (zielone)    █ NPV < 0 (czerwone)
```

---

## 9. Przykłady Obliczeń

### 9.1 Przykład: Instalacja 1700 kWp

**Dane wejściowe:**
```
Capacity:        1,700 kWp
Production:      1,914,260 kWh/rok (1,126 kWh/kWp)
Self-consumed:   981,799 kWh/rok (51.3%)
Energy price:    782 PLN/MWh
CAPEX:          3,500 PLN/kWp → 5,950,000 PLN
OPEX:           15 PLN/kWp/rok
Discount rate:   7%
Analysis period: 25 lat
```

**Parametry Monte Carlo:**
```
Symulacji:       5,000
Cena energii:    Normal(782, σ=15%)
Produkcja:       Normal(1.0, σ=10%)
CAPEX:           Lognormal(3500, σ=10%)
Inflacja:        Normal(2.5%, σ=2pp)
```

**Wyniki:**
```
Computation time: 18 ms

NPV:
  Mean:   4,470,000 PLN
  Std:    1,250,000 PLN
  P10:    2,650,000 PLN
  P50:    4,450,000 PLN
  P90:    6,100,000 PLN

IRR:
  Mean:   14.2%
  P10:    9.8%
  P50:    14.1%
  P90:    18.7%

Payback:
  Mean:   7.2 lat
  P10:    5.8 lat
  P50:    7.1 lat
  P90:    9.2 lat

Risk Metrics:
  Probability positive: 95.0%
  VaR 95%:             2,100,000 PLN
  CVaR 95%:            1,800,000 PLN
  Coefficient of var:  0.28

Breakeven price: 285 PLN/MWh
```

### 9.2 Ręczna Weryfikacja (jedna symulacja)

```python
# Parametry dla pojedynczej symulacji
price = 820          # +5% od bazowej
prod_factor = 0.95   # -5% produkcji
capex_per_kwp = 3600 # +3% CAPEX
inflation = 0.028    # +0.3pp
discount = 0.07      # bazowa

# Inwestycja
investment = 1700 * 3600 = 6,120,000 PLN

# Rok 1
production_y1 = 1,914,260 * 0.995 * 0.95 = 1,808,547 kWh
self_cons_y1 = 981,799 * 0.995 * 0.95 = 927,751 kWh
price_y1 = 820 * 1.028 = 842.96 PLN/MWh
savings_y1 = 927,751 / 1000 * 842.96 = 781,970 PLN
opex_y1 = 1700 * 15 * 1.028 = 26,214 PLN
net_cf_y1 = 781,970 - 26,214 = 755,756 PLN
pv_cf_y1 = 755,756 / 1.07 = 706,315 PLN

# ... podobnie dla lat 2-25 ...

NPV = -6,120,000 + sum(pv_cash_flows) ≈ 4,200,000 PLN
```

---

## 10. Ograniczenia i Założenia

### 10.1 Założenia Modelu

| Założenie | Opis | Wpływ na wynik |
|-----------|------|----------------|
| **Rozkład normalny cen** | Ceny energii mają rozkład normalny | Może nie uwzględniać ekstremalnych skoków |
| **Korelacje stałe** | Korelacje nie zmieniają się w czasie | Uproszczenie - korelacje mogą się zmieniać |
| **Brak sezonowości** | Model nie uwzględnia sezonowości cen | Może zaniżać zmienność |
| **Degradacja liniowa** | Stała roczna degradacja | W rzeczywistości może być nieliniowa |
| **Brak kosztów finansowania** | Model nie uwzględnia odsetek od kredytu | Może zawyżać NPV dla projektów kredytowanych |

### 10.2 Ograniczenia Techniczne

1. **Maksymalnie 50,000 symulacji** - ograniczenie dla wydajności
2. **Brak symulacji BESS** - Monte Carlo obecnie tylko dla PV
3. **Uproszczone IRR** - estymacja może nie być dokładna dla nietypowych przepływów
4. **Brak korelacji czasowych** - parametry losowane raz na cały okres analizy

### 10.3 Zalecenia Użycia

1. **Minimalnie 1,000 symulacji** dla stabilnych wyników
2. **5,000-10,000 symulacji** dla raportów biznesowych
3. **50,000 symulacji** dla dokładnych percentyli ogona (VaR 99%)
4. **Używaj profilu "konserwatywnego"** dla due diligence
5. **Weryfikuj wyniki** z analizą wrażliwości (jednoczynnikową)

### 10.4 Różnice względem Analizy Deterministycznej

| Aspekt | Deterministyczna | Monte Carlo |
|--------|------------------|-------------|
| NPV | Pojedyncza wartość | Rozkład prawdopodobieństwa |
| Ryzyko | Niewidoczne | VaR, CVaR, probability of loss |
| Decyzja | "NPV > 0 → inwestuj" | "95% szans na zysk, max strata 500k PLN" |
| Złożoność | Prosta | Wymaga definicji niepewności |

---

## Changelog

### v1.0.0 (2025-12-24)
- Pierwsza wersja modułu Monte Carlo
- Backend: silnik wektoryzowany NumPy
- Korelacje: dekompozycja Cholesky'ego
- Frontend: histogram, metryki ryzyka, insights
- API: `/monte-carlo/quick`, `/monte-carlo/presets`
- Wskaźnik postępu dla długich symulacji
