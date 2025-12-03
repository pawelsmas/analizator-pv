# PV Optimizer v1.8 - Micro-Frontend Architecture

## Architektura

System zbudowany jest w architekturze **micro-frontend** z **11 niezaleznymi kontenerami frontend** + **7 kontenerami backend**:

### Frontend Modules (Micro-Frontends)

| Module | Port | Responsibility | Container Name |
|--------|------|----------------|----------------|
| **Shell** | 9000 | Main application shell, routing, navigation, inter-module communication | `pv-frontend-shell` |
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

## Communication Pattern

```
┌─────────────────────────────────────────────────────────────────┐
│              Frontend Shell (Port 9000)                          │
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
         ├───► Production Module (9004) ─┼──► Backend APIs (8001-8011)
         ├───► Comparison Module (9005)  │
         ├───► Economics Module (9006) ──┤
         ├───► Settings Module (9007)    │
         ├───► ESG Module (9008) ────────┤
         ├───► Energy Prices (9009) ─────┤
         └───► Reports Module (9010) ────┘
```

## Inter-Module Communication

Modules communicate via **postMessage API** through Shell:

### Message Types (v1.8)

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
  currentScenario: 'P50'      // Current P50/P75/P90 scenario
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
│   └── styles.css           # Scenario button styles
│
├── frontend-comparison/     # Comparison module
├── frontend-economics/      # Economics module (EaaS/Ownership)
├── frontend-settings/       # Settings module
├── frontend-esg/            # ESG indicators module
├── frontend-energy-prices/  # Energy prices module
└── frontend-reports/        # Reports module
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
      - "9000:80"
    depends_on:
      - frontend-admin
      - frontend-config
      - frontend-consumption
      - frontend-production
      - frontend-comparison
      - frontend-economics
      - frontend-settings
      - frontend-esg

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

  # ... other modules ...
```

## Development Workflow

### Work on Single Module

```bash
# Develop only Production module
cd services/frontend-production

# Make changes to production.js, index.html, etc.

# Rebuild only this module
docker-compose build frontend-production
docker-compose up -d frontend-production

# Test at http://localhost:9004 (direct)
# Or http://localhost:9000 → Production tab (via shell)
```

### Cache Busting

After changes, update timestamp in index.html:
```html
<script src="production.js?t=1733222100"></script>
```

Or rebuild with --no-cache:
```bash
docker-compose build frontend-production --no-cache
```

## Shared State Management

Modules share data via:
1. **Shell sharedData** - In-memory state in shell
2. **LocalStorage** - For persistence across page reloads
3. **postMessage** - For real-time communication
4. **Backend APIs** - For server-side data

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
curl http://localhost:9000

# Test Production Module (direct)
curl http://localhost:9004

# Test via shell
# Open http://localhost:9000 → click Production tab

# Test scenario synchronization
# Change scenario in Production → verify Economics updates
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

### Data not persisting
- Check sharedData in shell console
- Verify backend API calls succeed
- Check network tab for failed requests

---

**Version 1.8** - PV Optimizer Micro-Frontend Architecture
