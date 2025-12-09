# Pagra ENERGY Studio v3.1 - Implementation Summary

**PRODUCE. STORE. PERFORM.**

## Overview

Professional PV and BESS analysis system with micro-frontend architecture, advanced physics-based modeling, and comprehensive economic analysis.

## Version 3.1 New Features

### 1. Pagra ENERGY Studio Branding
- New logo and tagline "PRODUCE. STORE. PERFORM."
- Updated UI with Pagra branding

### 2. Nginx Reverse Proxy
- All modules accessible via `/modules/{name}/`
- All APIs accessible via `/api/{service}/`
- `USE_PROXY = true` in shell.js for production
- Hetzner deployment with Tailscale VPN

### 3. BESS Module (v2.4)
**Module**: `frontend-bess` (Port 9013)
**Features**:
- Battery Energy Storage System analysis
- 0-export mode simulation
- Degradation tracking (3% year 1, 2%/year after)
- CAPEX/OPEX economics
- Comparison PV vs PV+BESS

---

## Version 1.9 Features

### 1. Project Management System

**Modules**: `frontend-projects` (Port 9011), `projects-db` (Port 8012)

**Features**:
- Create, save, load, and delete PV projects
- Automatic geolocation from postal code/city
- Project metadata (name, description, location)
- SQLite database for persistence

### 2. Quick Estimator

**Module**: `frontend-estimator` (Port 9012)

**Features**:
- Power presets: 50kWp, 100kWp, 200kWp, 500kWp, 1MWp
- Installation type selection (ground/roof/carport)
- P50/P75/P90 scenario selection
- Real-time financial calculations

### 3. Geo Service

**Service**: `geo-service` (Port 8021)

**Features**:
- OpenStreetMap Nominatim integration
- Offline Polish postal code database (100 regions)
- City lookup for major Polish cities
- Automatic elevation data
- In-memory caching

**Polish Postal Code Database**:
```python
POLISH_POSTAL_REGIONS = {
    "00": {"lat": 52.23, "lon": 21.01, "city": "Warszawa", "elev": 100},
    "30": {"lat": 50.06, "lon": 19.94, "city": "Krakow", "elev": 220},
    # ... 100 regions covering all of Poland
}
```

## Version 1.8 Features (Previous)

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

## Architecture (v3.1)

### Frontend Modules (14 containers)

| Module | Port | Key Features |
|--------|------|--------------|
| Shell | 80 | Nginx proxy, routing, scenario sync, shared data |
| Admin | 9001 | User management |
| Config | 9002 | Data upload, PVGIS integration |
| Consumption | 9003 | Charts, heatmaps |
| Production | 9004 | P50/P75/P90 scenarios |
| Comparison | 9005 | Variant analysis |
| Economics | 9006 | EaaS/Ownership models, BESS economics |
| Settings | 9007 | System parameters, BESS config |
| ESG | 9008 | Environmental indicators |
| Energy Prices | 9009 | TGE/ENTSO-E data |
| Reports | 9010 | PDF generation |
| Projects | 9011 | Project management |
| Estimator | 9012 | Quick estimation |
| **BESS** | 9013 | **Battery storage analysis** |

### Backend Services (10 containers)

| Service | Port | Technology |
|---------|------|------------|
| data-analysis | 8001 | Python/FastAPI, Pandas |
| pv-calculation | 8002 | Python/FastAPI, pvlib, BESS simulation |
| economics | 8003 | Python/FastAPI, NumPy |
| advanced-analytics | 8004 | Python/FastAPI |
| typical-days | 8005 | Python/FastAPI |
| energy-prices | 8010 | Python/FastAPI |
| reports | 8011 | Python/FastAPI, ReportLab |
| projects-db | 8012 | Python/FastAPI, SQLite |
| pvgis-proxy | 8020 | Python/FastAPI, httpx |
| geo-service | 8021 | Python/FastAPI, Nominatim |

## Key Technical Improvements

### 1. Geolocation System

```python
@app.get("/geo/location")
async def get_location(
    country: str = "PL",
    postal_code: str = None,
    city: str = None
):
    # 1. Check cache
    # 2. Try offline Polish database
    # 3. Fallback to Nominatim API
    return {
        "latitude": 52.23,
        "longitude": 21.01,
        "elevation": 100,
        "city": "Warszawa"
    }
```

### 2. Quick Estimator Calculations

```javascript
// Real-time NPV calculation
function calculateEstimate() {
  const annualProduction = powerKwp * yieldKwh;
  const annualSavings = annualProduction * energyPrice / 1000;
  const investment = powerKwp * costPerKwp;

  // Simple payback
  const paybackYears = investment / annualSavings;

  // NPV over 25 years
  const npv = calculateNPV(annualSavings, investment, 25, discountRate);
}
```

### 3. Shell Port Change

**Before (v1.8)**: Port 9000
**After (v1.9)**: Port 80 (standard HTTP)

## Files Added in v1.9

### Estimator Module (NEW)
- `services/frontend-estimator/index.html`
- `services/frontend-estimator/estimator.js` - Calculation logic
- `services/frontend-estimator/styles.css`
- `services/frontend-estimator/Dockerfile`
- `services/frontend-estimator/nginx.conf`

### Projects Module (NEW)
- `services/frontend-projects/index.html`
- `services/frontend-projects/projects.js`
- `services/frontend-projects/styles.css`
- `services/frontend-projects/Dockerfile`
- `services/frontend-projects/nginx.conf`

### Geo Service (NEW)
- `services/geo-service/main.py` - FastAPI app with Nominatim
- `services/geo-service/requirements.txt`
- `services/geo-service/Dockerfile`

### Projects DB (NEW)
- `services/projects-db/main.py` - SQLite persistence
- `services/projects-db/requirements.txt`
- `services/projects-db/Dockerfile`

## API Documentation

All services provide OpenAPI docs at `http://localhost:PORT/docs`

### New Endpoints (v1.9)

**Geo Service**:
```bash
GET /geo/location?country=PL&postal_code=00-001
GET /geo/location?country=PL&city=Warszawa
GET /geo/elevation?lat=52.23&lon=21.01
GET /geo/polish-cities
GET /health
```

**Projects DB**:
```bash
GET /projects
POST /projects
GET /projects/{id}
PUT /projects/{id}
DELETE /projects/{id}
GET /health
```

## Deployment

### Docker Compose
```bash
# Build and run all
docker-compose up -d --build

# Rebuild single module
docker-compose build frontend-estimator
docker-compose up -d frontend-estimator
```

### Access Points
- Application: http://localhost (port 80)
- API Docs: http://localhost:800X/docs
- Geo Service: http://localhost:8021/docs
- Projects DB: http://localhost:8022/docs

## Version History

| Version | Features |
|---------|----------|
| **v3.1** | **Pagra ENERGY Studio, nginx proxy, Hetzner deploy** |
| v2.4 | BESS module, battery storage analysis |
| v1.9 | Projects, Estimator, Geo Service |
| v1.8 | P50/P75/P90 scenarios, ESG module, EU formatting |
| v1.7 | DC/AC Ratio management, Economics fixes |

## Summary

- 14 frontend micro-services
- 10 backend micro-services
- BESS (Battery Energy Storage) module
- Nginx reverse proxy for production
- Project management with geolocation
- Quick Estimator
- Offline Polish postal code database
- P50/P75/P90 production scenarios
- Dynamic hourly calculations
- ESG environmental indicators
- European number formatting
- Inter-module synchronization
- Professional-grade PV + BESS analysis

---

**v3.1** - Pagra ENERGY Studio Implementation Summary
