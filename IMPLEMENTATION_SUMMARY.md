# PV Optimizer v1.8 - Implementation Summary

## Overview

Professional PV analysis system with micro-frontend architecture, advanced physics-based modeling, and comprehensive economic analysis.

## Version 1.8 New Features

### 1. Production Scenario Selector (P50/P75/P90)

**Module**: `frontend-production`

**Features**:
- Floating scenario selector in top-right corner
- Three probability scenarios:
  - **P50** (100%) - Median expected production
  - **P75** (97%) - 75% probability of achieving
  - **P90** (94%) - Conservative estimate
- Real-time recalculation of all statistics
- Synchronization with Economics module via Shell

**Key Code** (production.js):
```javascript
// Scenario factors
const SCENARIO_FACTORS = {
  'P50': 1.00,
  'P75': 0.97,
  'P90': 0.94
};

// Dynamic calculation from hourly data
for (let i = 0; i < production.length; i++) {
  const prod = production[i];
  const cons = consumption[i];

  if (prod >= cons) {
    selfConsumedKwh += cons;
    gridExportKwh += (prod - cons);
  } else {
    selfConsumedKwh += prod;
    gridImportKwh += (cons - prod);
  }
}
```

### 2. ESG Module

**Module**: `frontend-esg` (Port 9008)

**Features**:
- CO2 emission reduction calculation
- Tree equivalent calculation
- Water savings estimation
- Environmental impact reporting

### 3. European Number Formatting

**Function**: `formatNumberEU()`
```javascript
function formatNumberEU(value, decimals = 2) {
  return value.toLocaleString('pl-PL', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}
// Result: "1 234,56" instead of "1,234.56"
```

### 4. Inter-Module Scenario Synchronization

**Flow**:
```
Production → PRODUCTION_SCENARIO_CHANGED → Shell
Shell → localStorage + sharedData update
Shell → SCENARIO_CHANGED → All Modules
Economics → Recalculate with new factor
```

## Architecture (v1.8)

### Frontend Modules (11 containers)

| Module | Port | Key Features |
|--------|------|--------------|
| Shell | 9000 | Routing, scenario sync, shared data |
| Admin | 9001 | User management |
| Config | 9002 | Data upload, PVGIS integration |
| Consumption | 9003 | Charts, heatmaps |
| **Production** | 9004 | **P50/P75/P90 scenarios** |
| Comparison | 9005 | Variant analysis |
| Economics | 9006 | EaaS/Ownership models |
| Settings | 9007 | System parameters |
| **ESG** | 9008 | **Environmental indicators** |
| Energy Prices | 9009 | TGE/ENTSO-E data |
| Reports | 9010 | PDF generation |

### Backend Services (7 containers)

| Service | Port | Technology |
|---------|------|------------|
| data-analysis | 8001 | Python/FastAPI, Pandas |
| pv-calculation | 8002 | Python/FastAPI, pvlib |
| economics | 8003 | Python/FastAPI, NumPy |
| advanced-analytics | 8004 | Python/FastAPI |
| typical-days | 8005 | Python/FastAPI |
| energy-prices | 8010 | Python/FastAPI |
| reports | 8011 | Python/FastAPI, ReportLab |

## Key Technical Improvements

### 1. Accurate Statistics Calculation

**Before** (static from variant):
```javascript
// Used fixed values from variant
selfConsumption: variant.autoconsumption,
gridImport: 0 // Always zero!
```

**After** (dynamic from hourly data):
```javascript
// Loop through 8760 hourly values
for (let i = 0; i < production.length; i++) {
  const prod = production[i];
  const cons = consumption[i];

  totalProductionFromHourly += prod;

  if (prod >= cons) {
    selfConsumedKwh += cons;
    gridExportKwh += (prod - cons);
  } else {
    selfConsumedKwh += prod;
    gridImportKwh += (cons - prod);
  }
  totalConsumptionKwh += cons;
}

// Accurate percentages
const selfConsumptionPct = (selfConsumedKwh / actualProduction) * 100;
const selfSufficiencyPct = (selfConsumedKwh / totalConsumptionKwh) * 100;
```

### 2. Scenario-Aware Hourly Production

**Backend applies scenario factor**:
```python
# In pv-calculation service
hourly_production = base_hourly * scenario_factor
```

**Frontend uses pre-adjusted values**:
```javascript
// production[] already has scenario factor applied
const prod = production[i];
```

### 3. Shell Shared Data Management

```javascript
let sharedData = {
  analysisResults: null,
  pvConfig: null,
  consumptionData: null,
  hourlyData: null,
  masterVariant: null,
  masterVariantKey: null,
  economics: null,
  settings: null,
  currentScenario: 'P50'  // NEW in v1.8
};
```

## PV Calculation Accuracy (from v2.1)

### Solar Position
- Equation of Time correction
- Cooper's equation for declination
- Local solar time with longitude correction

### Irradiance Modeling
- Kasten-Young air mass model (NREL standard)
- Ineichen clear sky model (DNI, DHI, GHI)
- Linke turbidity factor for Poland (3.5)

### Loss Factors
- Incidence Angle Modifier (IAM) - Fresnel equations
- Temperature derating (-0.4%/C)
- System losses: soiling (2%), mismatch (2%), wiring (2%)
- Inverter efficiency: 98%

## Economic Analysis

### EaaS Model (Energy as a Service)
- 10-year service agreement
- Monthly fee calculation
- No upfront investment

### Ownership Model
- Full investment analysis
- NPV, IRR, LCOE calculation
- 25-year cash flow projection

### Sensitivity Analysis
- Multi-parameter analysis
- Tornado chart data
- Risk assessment

## Files Modified in v1.8

### Frontend Production
- `services/frontend-production/production.js` (v16)
  - `calculateStatistics()` - dynamic hourly calculation
  - `generateMonthlyProduction()` - EU number formatting
  - `setProductionScenario()` - scenario handling

- `services/frontend-production/index.html`
  - Floating scenario selector
  - Cache busting timestamp

- `services/frontend-production/styles.css`
  - Scenario button styles (P50 green, P75 blue, P90 red)

### Shell
- `services/frontend-shell/shell.js`
  - `PRODUCTION_SCENARIO_CHANGED` handler
  - `REQUEST_SCENARIO` handler
  - `loadScenarioFromShell()` function
  - Scenario persistence in localStorage

### ESG Module (NEW)
- `services/frontend-esg/index.html`
- `services/frontend-esg/esg.js`
- `services/frontend-esg/styles.css`
- `services/frontend-esg/Dockerfile`
- `services/frontend-esg/nginx.conf`

### Docker
- `docker-compose.yml`
  - Added frontend-esg service
  - Updated shell dependencies

## API Documentation

All services provide OpenAPI docs at `http://localhost:PORT/docs`

### Key Endpoints

**PV Calculation**:
```bash
POST /analyze
POST /generate-profile
GET /monthly-production
```

**Economics**:
```bash
POST /analyze
POST /comprehensive-sensitivity
GET /default-parameters
```

**Energy Prices**:
```bash
GET /tge/current
GET /tge/historical
GET /entso-e/prices
```

## Deployment

### Docker Compose
```bash
# Build and run
docker-compose up -d --build

# Rebuild single module
docker-compose build frontend-production
docker-compose up -d frontend-production
```

### Access Points
- Application: http://localhost:9000
- API Docs: http://localhost:800X/docs

## Version History

| Version | Features |
|---------|----------|
| v1.8 | P50/P75/P90 scenarios, ESG module, EU formatting |
| v1.7 | DC/AC Ratio management, Economics fixes |
| v1.6 | PVGIS integration for scenarios |
| v1.5 | Global scenario selector |
| v1.4 | PDF Reports, Energy Prices |

## Summary

- 11 frontend micro-services
- 7 backend micro-services
- P50/P75/P90 production scenarios
- Dynamic hourly calculations
- ESG environmental indicators
- European number formatting
- Inter-module synchronization
- Professional-grade PV analysis

---

**v1.8** - PV Optimizer Implementation Summary
