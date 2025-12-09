# Pagra ENERGY Studio v3.1 - Micro-Frontend Architecture

**PRODUCE. STORE. PERFORM.**

## Architektura

System zbudowany jest w architekturze **micro-frontend** z **14 niezaleznymi kontenerami frontend** + **10 kontenerami backend**:

### Frontend Modules (Micro-Frontends)

| Module | Port | Responsibility | Container Name |
|--------|------|----------------|----------------|
| **Shell** | 80 | Main application shell, nginx reverse proxy, routing, inter-module communication | `pv-frontend-shell` |
| **Admin** | 9001 | System administration, user management | `pv-frontend-admin` |
| **Configuration** | 9002 | Data upload, PV configuration, PVGIS integration | `pv-frontend-config` |
| **Consumption** | 9003 | Consumption analysis, charts, heatmaps | `pv-frontend-consumption` |
| **Production** | 9004 | PV production analysis, P50/P75/P90 scenarios | `pv-frontend-production` |
| **Comparison** | 9005 | Scenario comparison, variant analysis | `pv-frontend-comparison` |
| **Economics** | 9006 | Economic analysis (EaaS/Ownership), NPV, IRR | `pv-frontend-economics` |
| **Settings** | 9007 | System settings, parameters configuration | `pv-frontend-settings` |
| **ESG** | 9008 | Environmental indicators (CO2, trees, water) | `pv-frontend-esg` |
| **Energy Prices** | 9009 | Energy prices from TGE/ENTSO-E | `pv-frontend-energy-prices` |
| **Reports** | 9010 | PDF report generation | `pv-frontend-reports` |
| **Projects** | 9011 | Project management, save/load | `pv-frontend-projects` |
| **Estimator** | 9012 | Quick PV estimation calculator | `pv-frontend-estimator` |
| **BESS** | 9013 | Battery Energy Storage System module | `pv-frontend-bess` |

### Backend Services

| Service | Port | Responsibility |
|---------|------|----------------|
| data-analysis | 8001 | Data processing, statistics, CSV/Excel parsing |
| pv-calculation | 8002 | PV generation calculations (pvlib), PVGIS integration, BESS simulation |
| economics | 8003 | Economic analysis, NPV, IRR, LCOE, BESS economics |
| advanced-analytics | 8004 | Advanced KPI, load duration curves |
| typical-days | 8005 | Typical day patterns, seasonal analysis |
| energy-prices | 8010 | TGE/ENTSO-E price fetching |
| reports | 8011 | PDF generation with ReportLab |
| projects-db | 8012 | Project persistence (SQLite) |
| pvgis-proxy | 8020 | PVGIS API proxy with logging |
| geo-service | 8021 | Geolocation (Nominatim + Polish DB) |

## Communication Pattern

### Important: postToActiveModule (not true broadcast)

Shell uses `postToActiveModule()` function (alias: `broadcastToModules`) to send messages.
**Note**: This is NOT a true broadcast - only the currently loaded module in the iframe receives the message.
Other modules request data via `REQUEST_SHARED_DATA` when they load.

```
┌─────────────────────────────────────────────────────────────────┐
│              Frontend Shell (Port 80)                            │
│  - Navigation tabs                                               │
│  - Module Routing via iframe                                     │
│  - Inter-module Communication (postMessage API)                  │
│  - Shared Data Storage (sharedData object)                       │
│  - Scenario Synchronization (P50/P75/P90)                        │
└────────┬────────────────────────────────────────────────────────┘
         │
         ├───► Admin Module (9001)
         ├───► Config Module (9002) ────┐
         ├───► Consumption Module (9003) │
         ├───► Production Module (9004) ─┼──► Backend APIs (8001-8022)
         ├───► Comparison Module (9005)  │
         ├───► Economics Module (9006) ──┤
         ├───► Settings Module (9007)    │
         ├───► ESG Module (9008) ────────┤
         ├───► Energy Prices (9009) ─────┤
         ├───► Reports Module (9010) ────┤
         ├───► Projects Module (9011) ───┤ ──► projects-db (8012)
         ├───► Estimator Module (9012) ──┤ ──► geo-service (8021)
         └───► BESS Module (9013) ───────┘ ──► pv-calculation (8002)
```

## Nginx Reverse Proxy (Production Mode)

W trybie produkcyjnym (`USE_PROXY = true` w shell.js), wszystkie requesty idą przez nginx:

```
Frontend Modules:  /modules/{name}/  → http://pv-frontend-{name}/
Backend APIs:      /api/{service}/   → http://pv-{service}:{port}/
```

## BESS (Battery Energy Storage System)

### BESS Modes

| Mode | Description |
|------|-------------|
| **OFF** | No battery, backward compatible |
| **LIGHT/AUTO** | 0-Export mode with automatic sizing |

### BESS Configuration (Settings Module)

```javascript
{
  bessMode: 'LIGHT',              // OFF, LIGHT
  bessCapexPerKwh: 1500,          // PLN/kWh
  bessCapexPerKw: 300,            // PLN/kW
  bessOpexPct: 2.0,               // % of CAPEX/year
  bessDuration: 2,                // hours (C-rate)
  bessRoundtripEfficiency: 90,    // %
  bessSocMin: 10,                 // % minimum state of charge
  bessSocMax: 90,                 // % maximum state of charge
  bessDegradationYear1: 3.0,      // % degradation first year
  bessDegradation: 2.0,           // % degradation per year (years 2+)
  bessLifetime: 15                // years
}
```

### BESS Data Flow

```
Settings Module                pv-calculation (8002)           BESS Module (9013)
      │                              │                              │
      │ BESS config in settings      │                              │
      ├─────────────────────────────►│                              │
      │                              │                              │
      │         Config Module        │                              │
      │              │               │                              │
      │              │ POST /analyze │                              │
      │              │ with bess_*   │                              │
      │              ├──────────────►│                              │
      │              │               │ Simulate 8760h               │
      │              │               │ 0-export logic               │
      │              │◄──────────────│                              │
      │              │               │                              │
      │         Shell (sharedData)   │                              │
      │              │               │                              │
      │              │ SHARED_DATA_RESPONSE                         │
      │              ├─────────────────────────────────────────────►│
      │              │               │                              │
      │              │               │              Display BESS KPIs
      │              │               │              Degradation table
      │              │               │              Economics
```

### BESS Output Fields

```javascript
{
  bess_power_kw: 500,                    // Auto-sized power [kW]
  bess_energy_kwh: 1000,                 // Auto-sized capacity [kWh]
  bess_charged_kwh: 450000,              // Energy charged per year [kWh]
  bess_discharged_kwh: 405000,           // Energy discharged per year [kWh]
  bess_curtailed_kwh: 120000,            // Curtailed energy [kWh]
  bess_cycles_equivalent: 405,           // Equivalent full cycles/year
  bess_self_consumed_direct_kwh: 800000, // Direct PV consumption [kWh]
  bess_self_consumed_from_bess_kwh: 405000, // From battery [kWh]
  bess_grid_import_kwh: 200000,          // Grid import [kWh]
  baseline_no_bess: {                    // Baseline for comparison
    auto_consumption_pct: 45.0,
    self_consumed: 800000,
    exported: 980000
  }
}
```

### BESS Module Features

1. **Variant Selector** - Switch between A/B/C/D variants
2. **Energy Metrics KPIs**:
   - Autoconsumption increase (%)
   - Energy from battery (MWh/year)
   - Curtailment loss (MWh/year)
   - Equivalent cycles/year
3. **Energy Flow**:
   - Charging (MWh)
   - Discharging (MWh)
   - Round-trip efficiency (%)
4. **Comparison Table**: PV+BESS vs Only PV
5. **Economics KPIs**:
   - BESS CAPEX (PLN)
   - BESS OPEX/year (PLN)
   - Battery replacement year
   - Lifetime energy (MWh)
6. **Degradation Table**:
   - Year-by-year capacity
   - Cumulative energy
   - EOL status indicators

### EOL Status Thresholds

| Status | Threshold | Color |
|--------|-----------|-------|
| ✅ OK | ≥85% capacity | Green |
| ⚠️ Near EOL | 80-85% capacity | Yellow |
| 🔄 Replace | <80% or lifetime exceeded | Red |

## Inter-Module Communication

Modules communicate via **postMessage API** through Shell:

### Message Types (v2.4)

```javascript
// Data uploaded from Configuration
{
  type: 'DATA_UPLOADED',
  data: { filename, rows, year }
}

// Analysis complete from Config/Production
{
  type: 'ANALYSIS_COMPLETE',
  data: {
    fullResults,      // Full analysis results with BESS data
    pvConfig,         // PV configuration
    hourlyData        // 8760 hourly values
  }
}

// Master variant selected
{
  type: 'MASTER_VARIANT_SELECTED',
  data: {
    variantKey: 'B',
    variantData: {...}
  }
}

// Production scenario changed (P50/P75/P90)
{
  type: 'PRODUCTION_SCENARIO_CHANGED',
  data: {
    scenario: 'P75',
    source: 'production'
  }
}

// Settings changed (includes BESS settings)
{
  type: 'SETTINGS_CHANGED',
  data: {
    energyPrice: 450,
    feedInTariff: 0,
    bessMode: 'LIGHT',
    bessDuration: 2,
    ...
  }
}

// Economics calculated
{
  type: 'ECONOMICS_CALCULATED',
  data: {
    variantKey: 'B',
    eaasPhaseSavings: [...],
    ownershipPhaseSavings: [...]
  }
}

// Project loaded
{
  type: 'PROJECT_LOADED',
  data: {
    projectId: 'abc123',
    projectName: 'Farma Solarna Krakow',
    location: {...}
  }
}

// Project saved
{
  type: 'PROJECT_SAVED',
  data: {
    projectId: 'abc123',
    savedAt: '2024-01-15T10:30:00Z'
  }
}

// Navigate to another module
{
  type: 'NAVIGATE',
  data: { module: 'bess' }  // NEW: can navigate to BESS module
}

// Request shared data
{
  type: 'REQUEST_SHARED_DATA'
}

// Response with shared data
{
  type: 'SHARED_DATA_RESPONSE',
  data: { analysisResults, hourlyData, masterVariantKey, ... }
}

// Settings update broadcast
{
  type: 'SETTINGS_UPDATED',
  data: { ... all settings ... }
}

// Scenario changed broadcast
{
  type: 'SCENARIO_CHANGED',
  data: { scenario: 'P75' }
}

// Variant changed (from any module)
{
  type: 'VARIANT_CHANGED',
  data: { variant: 'B', source: 'bess' }
}

// Data cleared
{
  type: 'DATA_CLEARED'
}
```

### Shell Shared Data Structure

```javascript
let sharedData = {
  analysisResults: null,      // Full PV analysis results (with key_variants)
  pvConfig: null,             // PV configuration
  consumptionData: null,      // Consumption data
  hourlyData: null,           // 8760 hourly values
  masterVariant: null,        // Selected master variant data
  masterVariantKey: null,     // 'A', 'B', 'C', or 'D'
  economics: null,            // Economics calculation results
  settings: null,             // System settings (incl. BESS)
  currentScenario: 'P50',     // Current P50/P75/P90 scenario
  currentProject: null        // Current project
};
```

### Analysis Results Structure (key_variants)

```javascript
{
  scenarios: [...],           // All scenarios array
  key_variants: {             // Key variants object
    A: {
      capacity: 1000,
      production: 1100000,
      self_consumed: 850000,
      exported: 250000,
      auto_consumption_pct: 77.3,
      coverage_pct: 45.0,
      threshold: 50,
      // BESS fields (if enabled)
      bess_power_kw: 200,
      bess_energy_kwh: 400,
      bess_discharged_kwh: 180000,
      bess_curtailed_kwh: 50000,
      bess_cycles_equivalent: 450,
      baseline_no_bess: {...}
    },
    B: {...},
    C: {...},
    D: {...}
  }
}
```

## Directory Structure

```
services/
├── frontend-shell/          # Main shell (routing, navigation)
│   ├── index.html
│   ├── shell.js             # Inter-module communication hub
│   ├── styles.css
│   ├── nginx.conf
│   └── Dockerfile
│
├── frontend-admin/          # Admin module
├── frontend-config/         # Configuration module
├── frontend-consumption/    # Consumption analysis module
├── frontend-production/     # PV production module (P50/P75/P90)
│   ├── index.html           # Floating scenario selector
│   ├── production.js        # Scenario handling, statistics
│   └── styles.css
│
├── frontend-comparison/     # Comparison module (with BESS columns)
├── frontend-economics/      # Economics module (EaaS/Ownership)
├── frontend-settings/       # Settings module (with BESS config)
│   ├── index.html           # BESS configuration section
│   ├── settings.js          # bessDegradationYear1, etc.
│   └── styles.css
│
├── frontend-esg/            # ESG indicators module
├── frontend-energy-prices/  # Energy prices module
├── frontend-reports/        # Reports module
├── frontend-projects/       # Project management
│   ├── index.html
│   ├── projects.js
│   └── styles.css
│
├── frontend-estimator/      # Quick estimator
│   ├── index.html
│   ├── estimator.js
│   └── styles.css
│
└── frontend-bess/           # BESS module (NEW v2.4)
    ├── index.html           # Full BESS dashboard
    ├── bess.js              # Variant handling, degradation table
    ├── styles.css           # Purple theme
    ├── nginx.conf
    └── Dockerfile
```

## Production Scenarios (P50/P75/P90)

### Scenario Factors
| Scenario | Factor | Description |
|----------|--------|-------------|
| P50 | 100% | Median expected production |
| P75 | 97% | 75% probability of achieving |
| P90 | 94% | Conservative estimate |

### Scenario Synchronization Flow

```
Production Module                 Shell                    Other Modules
      │                            │                            │
      │ PRODUCTION_SCENARIO_CHANGED│                            │
      ├───────────────────────────►│                            │
      │                            │ Save to localStorage       │
      │                            │ Update sharedData          │
      │                            │                            │
      │                            │ SCENARIO_CHANGED           │
      │                            ├───────────────────────────►│
      │                            │                            │
      │                            │                    Recalculate
      │                            │                    with new factor
```

## Geolocation Flow

```
Projects Module                 geo-service (8021)           External APIs
      │                              │                            │
      │ GET /geo/location            │                            │
      │ ?postal_code=30-001          │                            │
      ├─────────────────────────────►│                            │
      │                              │ Check Polish DB            │
      │                              │ (offline, instant)         │
      │                              │                            │
      │                              │ If not found:              │
      │                              │ Nominatim API ────────────►│
      │                              │◄────────────────────────────│
      │                              │                            │
      │◄─────────────────────────────│                            │
      │ { lat, lon, city, elev }     │                            │
```

## Benefits of Micro-Frontend Architecture

1. **Independent Development** - Each module can be developed/deployed separately
2. **Technology Flexibility** - Each module can use different frameworks
3. **Scalability** - Modules can scale independently
4. **Team Autonomy** - Different teams can own different modules
5. **Isolated Failures** - If one module fails, others continue working
6. **Faster Builds** - Only changed modules need to be rebuilt
7. **Scenario Synchronization** - Global state managed by Shell
8. **BESS Integration** - Dedicated module for battery storage analysis

## Docker Compose Configuration

```yaml
services:
  # Frontend Shell
  frontend-shell:
    build: ./services/frontend-shell
    container_name: pv-frontend-shell
    ports:
      - "80:80"
    depends_on:
      - frontend-admin
      - frontend-config
      - frontend-consumption
      - frontend-production
      - frontend-comparison
      - frontend-economics
      - frontend-settings
      - frontend-esg
      - frontend-projects
      - frontend-estimator
      - frontend-bess

  # Production Module (P50/P75/P90)
  frontend-production:
    build: ./services/frontend-production
    container_name: pv-frontend-production
    ports:
      - "9004:80"

  # ESG Module
  frontend-esg:
    build: ./services/frontend-esg
    container_name: pv-frontend-esg
    ports:
      - "9008:80"

  # Projects Module
  frontend-projects:
    build: ./services/frontend-projects
    container_name: pv-frontend-projects
    ports:
      - "9011:80"

  # Estimator Module
  frontend-estimator:
    build: ./services/frontend-estimator
    container_name: pv-frontend-estimator
    ports:
      - "9012:80"

  # BESS Module (NEW v2.4)
  frontend-bess:
    build: ./services/frontend-bess
    container_name: pv-frontend-bess
    ports:
      - "9013:80"

  # Geo Service
  geo-service:
    build: ./services/geo-service
    container_name: pv-geo-service
    ports:
      - "8021:8021"

  # Projects DB
  projects-db:
    build: ./services/projects-db
    container_name: pv-projects-db
    ports:
      - "8022:8022"
    volumes:
      - projects-data:/app/data

  # ... other modules ...
```

## Development Workflow

### Work on Single Module

```bash
# Develop only BESS module
cd services/frontend-bess

# Make changes to bess.js, index.html, etc.

# Rebuild only this module
docker-compose build frontend-bess
docker-compose up -d frontend-bess

# Test at http://localhost:9013 (direct)
# Or http://localhost → BESS tab (via shell)
```

### Cache Busting

After changes, update timestamp in index.html:
```html
<script src="bess.js?v=1.1"></script>
```

Or rebuild with --no-cache:
```bash
docker-compose build frontend-bess --no-cache
```

## Shared State Management

Modules share data via:
1. **Shell sharedData** - In-memory state in shell
2. **LocalStorage** - For persistence across page reloads
3. **postMessage** - For real-time communication
4. **Backend APIs** - For server-side data
5. **projects-db** - For project persistence

```javascript
// Module requests data from shell
window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');

// Module listens for shared data
window.addEventListener('message', (event) => {
  if (event.data.type === 'SHARED_DATA_RESPONSE') {
    const data = event.data.data;
    // Use data.analysisResults.key_variants, data.masterVariantKey, etc.
  }

  if (event.data.type === 'SETTINGS_UPDATED') {
    const settings = event.data.data;
    // Use settings.bessMode, settings.bessDuration, etc.
  }
});

// Module notifies shell of changes
window.parent.postMessage({
  type: 'VARIANT_CHANGED',
  data: { variant: 'B', source: 'bess' }
}, '*');
```

## Testing

```bash
# Test Shell
curl http://localhost

# Test Production Module (direct)
curl http://localhost:9004

# Test BESS Module (direct)
curl http://localhost:9013

# Test Estimator Module (direct)
curl http://localhost:9012

# Test Geo Service
curl "http://localhost:8021/geo/location?country=PL&postal_code=30-001"

# Test Projects DB
curl http://localhost:8022/projects

# Test via shell
# Open http://localhost → click tabs
```

## Troubleshooting

### Module not loading in iframe
- Check CORS headers in nginx.conf
- Verify module is running: `docker ps`
- Check browser console for errors

### postMessage not working
- Verify origin in message handler
- Check iframe src matches MODULES config
- Use browser DevTools → Console to debug

### BESS module shows "Brak danych"
- Ensure BESS is enabled in Settings module
- Run analysis in Configuration module
- Check console for `SHARED_DATA_RESPONSE` message
- Verify `key_variants` exists in analysisResults

### Scenario not synchronizing
- Check shell.js console logs
- Verify localStorage: `localStorage.getItem('pv_current_scenario')`
- Check if module handles SCENARIO_CHANGED event

### Geolocation not working
- Check geo-service logs: `docker logs pv-geo-service`
- Verify internet connection for Nominatim
- Polish postal codes work offline

### Data not persisting
- Check sharedData in shell console
- Verify backend API calls succeed
- Check network tab for failed requests

---

**Version 3.1** - Pagra ENERGY Studio Micro-Frontend Architecture
