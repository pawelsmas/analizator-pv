# PV Optimizer v1.9 - Micro-Frontend Architecture

## Architektura

System zbudowany jest w architekturze **micro-frontend** z **13 niezaleznymi kontenerami frontend** + **9 kontenerami backend**:

### Frontend Modules (Micro-Frontends)

| Module | Port | Responsibility | Container Name |
|--------|------|----------------|----------------|
| **Shell** | 80 | Main application shell, routing, navigation, inter-module communication | `pv-frontend-shell` |
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

### Backend Services

| Service | Port | Responsibility |
|---------|------|----------------|
| data-analysis | 8001 | Data processing, statistics, CSV/Excel parsing |
| pv-calculation | 8002 | PV generation calculations (pvlib), PVGIS integration |
| economics | 8003 | Economic analysis, NPV, IRR, LCOE |
| advanced-analytics | 8004 | Advanced KPI, load duration curves |
| typical-days | 8005 | Typical day patterns, seasonal analysis |
| energy-prices | 8010 | TGE/ENTSO-E price fetching |
| reports | 8011 | PDF generation with ReportLab |
| **geo-service** | 8021 | **Geolocation (Nominatim + Polish DB)** |
| **projects-db** | 8022 | **Project persistence (SQLite)** |

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
         ├───► Projects Module (9011) ───┤ ──► projects-db (8022)
         └───► Estimator Module (9012) ──┘ ──► geo-service (8021)
```

## Inter-Module Communication

Modules communicate via **postMessage API** through Shell:

### Message Types (v1.9)

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
    fullResults,      // Full analysis results
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

// Settings changed
{
  type: 'SETTINGS_CHANGED',
  data: {
    energyPrice: 450,
    feedInTariff: 0,
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

// Project loaded (NEW in v1.9)
{
  type: 'PROJECT_LOADED',
  data: {
    projectId: 'abc123',
    projectName: 'Farma Solarna Krakow',
    location: {...}
  }
}

// Project saved (NEW in v1.9)
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
  data: { module: 'economics' }
}

// Request shared data
{
  type: 'REQUEST_SHARED_DATA'
}

// Request current scenario
{
  type: 'REQUEST_SCENARIO'
}

// Data cleared
{
  type: 'DATA_CLEARED'
}
```

### Shell Shared Data Structure

```javascript
let sharedData = {
  analysisResults: null,      // Full PV analysis results
  pvConfig: null,             // PV configuration
  consumptionData: null,      // Consumption data
  hourlyData: null,           // 8760 hourly values
  masterVariant: null,        // Selected master variant data
  masterVariantKey: null,     // 'A', 'B', 'C', or 'D'
  economics: null,            // Economics calculation results
  settings: null,             // System settings
  currentScenario: 'P50',     // Current P50/P75/P90 scenario
  currentProject: null        // Current project (NEW in v1.9)
};
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
├── frontend-comparison/     # Comparison module
├── frontend-economics/      # Economics module (EaaS/Ownership)
├── frontend-settings/       # Settings module
├── frontend-esg/            # ESG indicators module
├── frontend-energy-prices/  # Energy prices module
├── frontend-reports/        # Reports module
├── frontend-projects/       # Project management (NEW)
│   ├── index.html
│   ├── projects.js
│   └── styles.css
│
└── frontend-estimator/      # Quick estimator (NEW)
    ├── index.html
    ├── estimator.js         # Calculation logic
    └── styles.css
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

## Geolocation Flow (v1.9)

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

## Docker Compose Configuration

```yaml
services:
  # Frontend Shell
  frontend-shell:
    build: ./services/frontend-shell
    container_name: pv-frontend-shell
    ports:
      - "80:80"  # Changed from 9000 in v1.9
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

  # Projects Module (NEW)
  frontend-projects:
    build: ./services/frontend-projects
    container_name: pv-frontend-projects
    ports:
      - "9011:80"

  # Estimator Module (NEW)
  frontend-estimator:
    build: ./services/frontend-estimator
    container_name: pv-frontend-estimator
    ports:
      - "9012:80"

  # Geo Service (NEW)
  geo-service:
    build: ./services/geo-service
    container_name: pv-geo-service
    ports:
      - "8021:8021"

  # Projects DB (NEW)
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
# Develop only Estimator module
cd services/frontend-estimator

# Make changes to estimator.js, index.html, etc.

# Rebuild only this module
docker-compose build frontend-estimator
docker-compose up -d frontend-estimator

# Test at http://localhost:9012 (direct)
# Or http://localhost → Szybka Wycena tab (via shell)
```

### Cache Busting

After changes, update timestamp in index.html:
```html
<script src="estimator.js?t=1733222100"></script>
```

Or rebuild with --no-cache:
```bash
docker-compose build frontend-estimator --no-cache
```

## Shared State Management

Modules share data via:
1. **Shell sharedData** - In-memory state in shell
2. **LocalStorage** - For persistence across page reloads
3. **postMessage** - For real-time communication
4. **Backend APIs** - For server-side data
5. **projects-db** - For project persistence (NEW)

```javascript
// Module requests data from shell
window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');

// Module listens for shared data
window.addEventListener('message', (event) => {
  if (event.data.type === 'SHARED_DATA_RESPONSE') {
    const data = event.data.data;
    // Use data.analysisResults, data.hourlyData, etc.
  }
});

// Module notifies shell of changes
window.parent.postMessage({
  type: 'PRODUCTION_SCENARIO_CHANGED',
  data: { scenario: 'P75', source: 'production' }
}, '*');
```

## Testing

```bash
# Test Shell
curl http://localhost

# Test Production Module (direct)
curl http://localhost:9004

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

**Version 1.9** - PV Optimizer Micro-Frontend Architecture
