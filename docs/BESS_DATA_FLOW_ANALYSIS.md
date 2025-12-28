# BESS Data Flow Analysis - Problem i Rozwiązanie

**Data**: 2025-12-27
**Wersja dokumentu**: 1.0
**Status**: KRYTYCZNY PROBLEM ARCHITEKTURY

---

## 1. PODSUMOWANIE PROBLEMU

### Obserwowane objawy:
| Źródło danych w UI | BESS Size | Savings/rok | CAPEX |
|-------------------|-----------|-------------|-------|
| Header EKONOMIA | 837 kW / 837 kWh | ? | ? |
| Delta PV+BESS | ? | 103.6 tys. PLN | 754 tys. PLN |
| BESS Variants S(1h) | 1223 kW / 1223 kWh | 183.6 tys. PLN | 1101 tys. PLN |
| BESS Variants M(2h) | 612 kW / 1223 kWh | 183.6 tys. PLN | 1009 tys. PLN |

**Problem fundamentalny**: Różne sekcje UI pokazują różne wartości BESS bo pobierają dane z różnych źródeł, które wywołują bess-dispatch z RÓŻNYMI parametrami.

---

## 2. ARCHITEKTURA - STAN OBECNY (PROBLEMATYCZNY)

### 2.1 Źródła danych BESS

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND ECONOMICS.JS                              │
│                                                                             │
│   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐            │
│   │ bessSizingData  │  │profileAnalysis  │  │ configBessData  │            │
│   │ (BESS PRO)      │  │  BessData       │  │ (pv-calculation)│            │
│   └────────┬────────┘  └────────┬────────┘  └────────┬────────┘            │
│            │                    │                    │                      │
│            └────────────────────┼────────────────────┘                      │
│                                 │                                           │
│                    ┌────────────▼────────────┐                              │
│                    │   currentBessSource     │                              │
│                    │   (przełącznik źródła)  │                              │
│                    └────────────┬────────────┘                              │
│                                 │                                           │
│                    ┌────────────▼────────────┐                              │
│                    │ applyBessSourceToVariant│                              │
│                    │ (aplikuje do UI)        │                              │
│                    └─────────────────────────┘                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Jak każde źródło pobiera dane

#### Źródło A: `configBessData` (pv-calculation)
**Lokalizacja**: `services/pv-calculation/app.py` linie 2280-2399

```python
# pv-calculation wywołuje bess-dispatch/sizing z tymi parametrami:
payload = {
    "mode": mode,  # Z settings.dispatch_mode lub 'pv_surplus'
    "peak_limit_kw": np.percentile(load_array, 95),  # AUTO-CALCULATED P95!
    "reserve_fraction": 0.3,
    "demand_charge_pln_kw_month": bess_settings.get('demand_charge_pln_kw_month', 0.0),
    "eol_capacity_factor": 0.70,
    "annual_degradation_pct": 2.0,
    # ... inne parametry
}
```

**Kiedy wywoływany**: Gdy user kliknie "Oblicz" w KONFIGURACJA

#### Źródło B: `bessSizingData` (frontend-bess)
**Lokalizacja**: `services/frontend-bess/bess.js` linie 2486-2574

```javascript
// bess.js wywołuje bess-dispatch/sizing z INNYMI parametrami:
const requestBody = {
    mode: bessConfig.stacked_mode ? 'stacked' : 'pv_surplus',
    peak_limit_kw: bessConfig.peak_limit_kw || null,  // Z UI lub NULL!
    reserve_fraction: bessConfig.reserve_fraction || 0.3,
    // NIE MA demand_charge_pln_kw_month!
    // NIE MA eol_capacity_factor!
    // ... inne parametry
};
```

**Kiedy wywoływany**: Automatycznie gdy dane PV/Load są załadowane do modułu BESS

#### Źródło C: `profileAnalysisBessData` (profile module)
**Lokalizacja**: `services/frontend-profile/` (osobny moduł)

- Wywołuje własną symulację godzinową
- Może używać innych parametrów BESS
- Przekazuje dane przez postMessage do economics.js

### 2.3 Dlaczego wyniki się różnią

| Parametr | pv-calculation | bess.js (BESS module) |
|----------|---------------|----------------------|
| `peak_limit_kw` | P95 load (auto) | `bessConfig.peak_limit_kw \|\| null` |
| `demand_charge_pln_kw_month` | Z settings (50 PLN) | **BRAK!** |
| `eol_capacity_factor` | 0.70 | **BRAK!** |
| `annual_degradation_pct` | 2.0 | **BRAK!** |
| `mode` | Z settings.dispatch_mode | `stacked_mode ? 'stacked' : 'pv_surplus'` |

**Konsekwencja**:
- pv-calculation: Sizing z peak_limit_kw = P95, EOL oversizing = większy BESS
- bess.js: Sizing bez peak_limit = mniejszy BESS optymalizowany tylko pod PV surplus

---

## 3. SZCZEGÓŁOWA ANALIZA PRZEPŁYWU DANYCH

### 3.1 Przepływ dla pv-calculation → configBessData

```
User clicks "Oblicz" in KONFIGURACJA
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ config-v2.js: runCalculation()                                │
│   - Pobiera settings z localStorage                           │
│   - Buduje payload z bess_settings                            │
│   - POST /api/pv-calculation/calculate                        │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ pv-calculation/app.py: /calculate endpoint                    │
│   - Generuje profile PV (PVGIS TMY)                           │
│   - Wywołuje call_bess_dispatch_sizing()                      │
│     - mode = settings.dispatch_mode lub 'pv_surplus'          │
│     - peak_limit_kw = P95(load) dla STACKED                   │
│     - demand_charge = settings.demand_charge (50 PLN)         │
│     - eol_capacity_factor = 0.70                              │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ bess-dispatch/app.py: /sizing endpoint                        │
│   - Wywołuje run_sizing_optimization()                        │
│   - Zwraca: variants[], recommended_power_kw, etc.            │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ pv-calculation: Zapisuje wynik do variant_result              │
│   - bess_power_kw = result.recommended_power_kw               │
│   - bess_energy_kwh = result.recommended_energy_kwh           │
│   - savings_breakdown = result.variants[0].savings_breakdown  │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ config-v2.js: Wysyła postMessage do shell.js                  │
│   type: 'CONFIG_DATA', data: { key_variants: [...] }          │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ economics.js: Odbiera dane w window.addEventListener          │
│   - Parsuje variant.bess_power_kw, variant.savings_breakdown  │
│   - Tworzy configBessData object                              │
│   - Wyświetla w Delta PV+BESS sekcji                          │
└───────────────────────────────────────────────────────────────┘
```

**Wynik**: Header EKONOMIA pokazuje np. 837 kW / 837 kWh

### 3.2 Przepływ dla bess.js → bessSizingData

```
User otwiera moduł BESS (klikając zakładkę)
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ bess.js: Moduł się ładuje                                     │
│   - Pobiera pvData i loadData z shell (postMessage)           │
│   - Pobiera bessConfig z UI (checkboxy, inputy)               │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ bess.js: fetchSizingVariants()                                │
│   - BUDUJE WŁASNY REQUEST BODY:                               │
│     mode: bessConfig.stacked_mode ? 'stacked' : 'pv_surplus'  │
│     peak_limit_kw: bessConfig.peak_limit_kw || null           │
│     (BRAK demand_charge!)                                     │
│     (BRAK eol_capacity_factor!)                               │
│   - POST /api/bess-dispatch/sizing                            │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ bess-dispatch/app.py: /sizing endpoint                        │
│   - RÓŻNE PARAMETRY = RÓŻNY WYNIK!                            │
│   - Bez peak_limit: większy BESS pod PV surplus               │
│   - Bez EOL: brak oversizing                                  │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ bess.js: displaySizingVariants()                              │
│   - Wyświetla warianty S/M/L w tabeli                         │
│   - Wysyła postMessage do economics.js                        │
│     type: 'BESS_SIZING_DATA'                                  │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ economics.js: Odbiera BESS_SIZING_DATA                        │
│   - Tworzy bessSizingData object                              │
│   - currentBessSource = 'bess-sizing'                         │
│   - Wyświetla w BESS Variants sekcji                          │
└───────────────────────────────────────────────────────────────┘
```

**Wynik**: BESS Variants pokazuje np. 1223 kW / 1223 kWh (INNY ROZMIAR!)

---

## 4. ZMIENNE GLOBALNE W economics.js

### 4.1 Definicje (linie 80-89)

```javascript
let profileAnalysisBessData = null; // BESS data from Profile Analysis module
let configBessData = null; // BESS data from pv-calculation (via key_variants) - ESTIMATED
let bessSizingData = null; // BESS data from BESS PRO /sizing endpoint - AUTHORITATIVE
let currentBessSource = 'pv-calculation'; // Przełącznik źródła

// CENTRALIZED FINANCIAL METRICS STORAGE
let centralizedMetrics = {};
```

### 4.2 Struktura danych dla każdego źródła

#### configBessData (z pv-calculation):
```javascript
{
  bess_power_kw: 837,
  bess_energy_kwh: 837,
  bess_cycles_equivalent: 250,
  bess_self_consumed_from_bess_kwh: 156000,
  bess_discharged_kwh: 156000,
  schema_version: 'bess_economics_v2',
  savings_breakdown: {
    energy_savings_pln: 121836,
    demand_charge_savings_pln: 0,  // MOŻE BYĆ 0 JEŚLI BUG!
    capacity_fee_savings_pln: 23867,
    arbitrage_savings_pln: 69894,
    degradation_cost_pln: -32026,
    net_savings_pln: 183571,
    source: 'bess_dispatch_lp'
  },
  dispatch_metadata: {
    dispatch_mode: 'stacked',
    topology: 'pv_load',
    peak_shaving_enabled: true
  }
}
```

#### bessSizingData (z bess.js/BESS module):
```javascript
{
  bess_power_kw: 1223,
  bess_energy_kwh: 1223,
  bess_cycles_equivalent: 180,
  annual_discharge_mwh: 220,
  annual_savings_pln: 183600,
  savings_breakdown: {
    energy_savings_pln: 176000,
    demand_charge_savings_pln: 0,  // BRAK W REQUEST!
    capacity_fee_savings_pln: 7600,
    arbitrage_savings_pln: 0,
    degradation_cost_pln: 0,
    net_savings_pln: 183600,
    source: 'bess_dispatch_lp'
  }
}
```

### 4.3 Funkcja applyBessSourceToVariant() (linie 6443-6508)

Ta funkcja przełącza dane BESS w zależności od `currentBessSource`:

```javascript
function applyBessSourceToVariant() {
  const variant = variants[currentVariant];

  if (currentBessSource === 'bess-sizing' && bessSizingData) {
    // Użyj danych z BESS module (bess.js)
    variant.bess_power_kw = bessSizingData.bess_power_kw;
    variant.bess_energy_kwh = bessSizingData.bess_energy_kwh;
    variant.savings_breakdown = bessSizingData.savings_breakdown;
    // ...
  } else if (currentBessSource === 'profile-analysis' && profileAnalysisBessData) {
    // Użyj danych z Profile Analysis
    variant.bess_power_kw = profileAnalysisBessData.bess_power_kw;
    // ...
  } else if (currentBessSource === 'pv-calculation' && configBessData) {
    // Użyj danych z KONFIGURACJA (pv-calculation)
    variant.bess_power_kw = configBessData.bess_power_kw;
    // ...
  }
}
```

---

## 5. ANALIZA KODU - BESS.JS

### 5.1 fetchSizingVariants() (linie 2486-2574)

```javascript
async function fetchSizingVariants(pvData, loadData, bessConfig) {
  const bessDispatchUrl = '/api/bess-dispatch';

  // PROBLEM: Buduje WŁASNY request body - nie używa ustawień systemowych!
  const requestBody = {
    pv_generation_kw: pvData,
    load_kw: loadData,
    interval_minutes: 60,

    // MODE: Z lokalnego UI checkbox, nie z systemSettings!
    mode: bessConfig.stacked_mode ? 'stacked' : 'pv_surplus',

    // PEAK_LIMIT: Z lokalnego inputa lub NULL!
    // pv-calculation używa P95(load) automatycznie!
    peak_limit_kw: bessConfig.peak_limit_kw || null,

    reserve_fraction: bessConfig.reserve_fraction || 0.3,
    durations_h: [1.0, 2.0, 4.0],
    roundtrip_efficiency: bessConfig.roundtrip_efficiency || 0.90,
    soc_min: bessConfig.soc_min || 0.10,
    soc_max: bessConfig.soc_max || 0.90,
    capex_per_kwh: bessConfig.capex_per_kwh || 1500,
    capex_per_kw: bessConfig.capex_per_kw || 300,
    import_price_pln_mwh: 800,
    max_efc_per_year: bessConfig.max_efc_per_year || null,
    max_throughput_mwh_per_year: bessConfig.max_throughput_mwh_per_year || null,

    // BRAK: demand_charge_pln_kw_month!
    // BRAK: eol_capacity_factor!
    // BRAK: annual_degradation_pct!
  };

  // Arbitrage (tylko jeśli włączony w UI)
  if (arbitrageConfig && bessConfig.stacked_mode) {
    requestBody.arbitrage_config = { ... };
  }

  const response = await fetch(`${bessDispatchUrl}/sizing`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(requestBody),
  });

  // ...
}
```

---

## 6. ANALIZA KODU - PV-CALCULATION

### 6.1 call_bess_dispatch_sizing() (linie 2260-2399)

```python
def call_bess_dispatch_sizing(load_kw, pv_generation_kw, bess_settings, interval_minutes=60):
    """Call bess-dispatch service for BESS sizing optimization"""

    # Określenie trybu (topology i mode)
    if not pv_generation_kw or len(pv_generation_kw) == 0:
        topology = 'load_only'
        mode = 'load_only'
        peak_limit_kw = float(np.percentile(load_array, 90))
    else:
        mode = bess_settings.get('dispatch_mode', 'pv_surplus')
        peak_limit_kw = bess_settings.get('peak_limit_kw')

        # AUTO-CALCULATE peak_limit dla STACKED mode!
        if mode == 'stacked' and not peak_limit_kw:
            load_array = np.array(load_kw)
            peak_limit_kw = float(np.percentile(load_array, 95))  # P95!

    # Budowanie payload - PEŁNY ZESTAW PARAMETRÓW
    payload = {
        "pv_generation_kw": pv_generation_kw,
        "load_kw": load_kw,
        "interval_minutes": interval_minutes,
        "mode": mode,

        # Peak shaving
        "peak_limit_kw": peak_limit_kw,  # P95 dla STACKED!
        "reserve_fraction": bess_settings.get('reserve_fraction', 0.3),

        # EOL degradation sizing - BRAK W BESS.JS!
        "eol_capacity_factor": bess_settings.get('eol_capacity_factor', 0.70),
        "annual_degradation_pct": bess_settings.get('annual_degradation_pct', 2.0),

        # Ceny i demand charge
        "import_price_pln_mwh": bess_settings.get('import_price_pln_mwh', 800.0),
        "demand_charge_pln_kw_month": bess_settings.get('demand_charge_pln_kw_month', 0.0),

        # Capacity fee
        "prices": {
            "capacity_fee_method": 'polish_som',
            "capacity_fee_som_pln_kwh": 0.2194
        }
    }

    response = requests.post(f"{BESS_DISPATCH_URL}/sizing", json=payload, timeout=300)
    return response.json()
```

---

## 7. PROBLEMY ZIDENTYFIKOWANE

### Problem 1: Dwa niezależne wywołania bess-dispatch
- **pv-calculation** wywołuje `/sizing` z pełnymi parametrami (P95 peak_limit, demand_charge, EOL)
- **bess.js** wywołuje `/sizing` z niepełnymi parametrami (bez demand_charge, bez EOL)
- **Wynik**: Różne rozmiary BESS dla tego samego profilu!

### Problem 2: Brak single source of truth
- `configBessData` - z pv-calculation
- `bessSizingData` - z bess.js
- `profileAnalysisBessData` - z profile module
- UI przełącza między nimi przez `currentBessSource`
- Użytkownik widzi różne wartości w różnych miejscach

### Problem 3: demand_charge_pln_kw_month = 0
- W config-v2.js był bug: `??` zamiast `||`
- `0 ?? 50 = 0` (bo 0 nie jest null/undefined)
- `0 || 50 = 50` (bo 0 jest falsy)
- **Naprawione**, ale bess.js nadal nie wysyła tego parametru!

### Problem 4: Brak per-service EFC breakdown
- bess-dispatch zwraca `efc_per_service` ale frontend tego nie wyświetla
- Użytkownik chce widzieć: PV Surplus: X cykli, Peak Shaving: Y cykli, Arbitrage: Z cykli

### Problem 5: EOL oversizing tylko w pv-calculation
- pv-calculation: `eol_capacity_factor=0.70` → oversizing ~43%
- bess.js: BRAK tego parametru → brak oversizing
- **Wynik**: pv-calculation daje większy BESS

---

## 8. PROPONOWANE ROZWIĄZANIE

### Opcja A: Single Source of Truth (REKOMENDOWANA)

```
┌─────────────────────────────────────────────────────────────────┐
│                    NOWA ARCHITEKTURA                            │
│                                                                 │
│   KONFIGURACJA (config-v2.js)                                   │
│         │                                                       │
│         ▼                                                       │
│   pv-calculation/app.py                                         │
│         │                                                       │
│         ├── call_bess_dispatch_sizing()                         │
│         │         │                                             │
│         │         ▼                                             │
│         │   bess-dispatch/sizing                                │
│         │         │                                             │
│         │         ▼                                             │
│         │   sizing_result (AUTHORITATIVE)                       │
│         │                                                       │
│         ▼                                                       │
│   variant_result.bess_* + variant_result.savings_breakdown      │
│         │                                                       │
│         ▼                                                       │
│   postMessage → shell.js (centralny broker)                     │
│         │                                                       │
│         ├────────────────────────────────────────────┐          │
│         │                                            │          │
│         ▼                                            ▼          │
│   economics.js                               bess.js            │
│   (READ ONLY)                               (READ ONLY)         │
│   - Wyświetla dane                          - Wyświetla dane    │
│   - NIE wywołuje /sizing                    - NIE wywołuje      │
│                                               /sizing!          │
└─────────────────────────────────────────────────────────────────┘
```

**Zmiany wymagane**:

1. **bess.js**: Usunąć `fetchSizingVariants()` - nie wywołuje już bess-dispatch
2. **bess.js**: Pobierać dane BESS z shell.js przez postMessage
3. **shell.js**: Przechowywać centralnie `bessData` z pv-calculation
4. **economics.js**: Usunąć `bessSizingData` i `profileAnalysisBessData` - używać tylko `configBessData`

### Opcja B: Synchronizacja parametrów

Jeśli bess.js MUSI wywołać własny sizing:

1. **bess.js**: Pobierać `systemSettings` z shell.js
2. **bess.js**: Używać TYCH SAMYCH parametrów co pv-calculation:
   ```javascript
   const requestBody = {
     // ... istniejące parametry ...
     demand_charge_pln_kw_month: systemSettings.bessPowerChargePlnPerKwMonth || 50,
     eol_capacity_factor: systemSettings.bessEolCapacityFactor || 0.70,
     annual_degradation_pct: systemSettings.bessAnnualDegradationPct || 2.0,
     peak_limit_kw: bessConfig.peak_limit_kw || calculateP95(loadData),
   };
   ```

### Opcja C: Hybrid - pv-calculation jako source, bess.js jako "what-if"

1. **pv-calculation** pozostaje single source of truth
2. **bess.js** umożliwia eksperymentowanie z różnymi parametrami (warianty S/M/L)
3. **economics.js** zawsze używa danych z pv-calculation, ale może pokazać porównanie

---

## 9. REKOMENDACJA

**Rekomendowana opcja: A (Single Source of Truth)**

**Uzasadnienie**:
1. Eliminuje niespójność danych
2. Upraszcza architekturę
3. Redukuje złożoność debugowania
4. Użytkownik widzi spójne wartości we wszystkich miejscach

**Ryzyko opcji B/C**:
- Trudne do utrzymania synchronizacji
- Bug w jednym miejscu = niespójność
- Więcej kodu = więcej bugów

---

## 10. PLIKI DO MODYFIKACJI

### Dla opcji A (Single Source of Truth):

| Plik | Zmiana | Priorytet |
|------|--------|-----------|
| `services/frontend-bess/bess.js` | Usunąć fetchSizingVariants(), pobierać dane z shell | WYSOKI |
| `services/frontend-shell/shell.js` | Dodać centralny storage dla bessData | WYSOKI |
| `services/frontend-economics/economics.js` | Usunąć wielość źródeł, używać tylko configBessData | ŚREDNI |
| `services/frontend-config/config-v2.js` | Upewnić się że wysyła kompletne dane | NISKI |

### Quick fixes (niezależnie od opcji):

| Plik | Zmiana | Priorytet |
|------|--------|-----------|
| `services/frontend-bess/bess.js` | Dodać demand_charge_pln_kw_month do requestBody | WYSOKI |
| `services/frontend-bess/bess.js` | Dodać eol_capacity_factor do requestBody | WYSOKI |
| `services/frontend-bess/bess.js` | Dodać peak_limit_kw auto-calculation (P95) | WYSOKI |
| `services/frontend-economics/economics.js` | Dodać display dla efc_per_service | ŚREDNI |

---

## 11. APPENDIX: Logi debugowania

### Z pv-calculation:
```
🚀 Calling bess-dispatch /sizing at http://bess-dispatch:8000/sizing
   Mode: stacked, Topology: pv_load, dispatch_mode from settings: stacked
   Load points: 8760, PV points: 8760
   demand_charge: 50.0 PLN/kW/month, peak_limit: 1456.3 kW
✅ bess-dispatch sizing successful:
   Recommended: 837 kW / 837 kWh
   Annual savings: 183571 PLN
   Savings breakdown: energy=121836, demand=0, capacity=23867
```

### Z bess.js (BESS module):
```
🔄 Fetching sizing variants from bess-dispatch...
✅ Sizing variants received:
   recommended_power_kw: 1223
   recommended_energy_kwh: 1223
   annual_savings_pln: 183600
```

**Różnica**: 837 kWh vs 1223 kWh = 46% różnicy!

---

## 12. KONTAKT / PYTANIA

Ten dokument opisuje stan na dzień 2025-12-27.

Agent powinien przeanalizować:
1. Czy opcja A jest akceptowalna?
2. Czy są dodatkowe wymagania biznesowe dla bess.js?
3. Czy moduł BESS ma być "kalkulatorem" czy tylko "wyświetlaczem"?
4. Jakie warianty sizing powinny być dostępne w UI?

---

**KONIEC DOKUMENTU**
