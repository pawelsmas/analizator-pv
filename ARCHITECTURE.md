# PV Optimizer v1.8 - Architecture Documentation

## Overview

PV Optimizer is a micro-frontend application for photovoltaic system analysis and optimization. The system consists of 11 frontend modules and 7 backend services running in Docker containers.

## System Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                        Frontend Shell (Port 9000)                           │
│                    Nginx + HTML/JS + postMessage Hub                        │
│                    Scenario Sync | Shared Data | Routing                    │
└─────────────────────────────────┬──────────────────────────────────────────┘
                                  │
     ┌────────────────────────────┼────────────────────────────┐
     │                            │                            │
     ▼                            ▼                            ▼
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│  Config  │  │Consumption│  │Production│  │Economics │  │   ESG    │
│  :9002   │  │  :9003   │  │  :9004   │  │  :9006   │  │  :9008   │
└────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
     │             │             │             │             │
     └─────────────┴─────────────┴─────────────┴─────────────┘
                                  │
                           HTTP/REST API
                                  │
     ┌────────────────────────────┼────────────────────────────┐
     │             │              │              │             │
     ▼             ▼              ▼              ▼             ▼
┌──────────┐ ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│   Data   │ │    PV    │  │Economics │  │ Energy   │  │ Reports  │
│ Analysis │ │Calculation│  │ Service  │  │ Prices   │  │ Service  │
│  :8001   │ │  :8002   │  │  :8003   │  │  :8010   │  │  :8011   │
└──────────┘ └──────────┘  └──────────┘  └──────────┘  └──────────┘
   Python/FastAPI + NumPy/Pandas/pvlib
```

## Services Description

### Frontend Modules

#### 1. Shell (Port 9000)
**Technology**: Nginx + HTML/CSS/JavaScript
**Responsibilities**:
- Main application container with navigation tabs
- Module routing via iframe
- Inter-module communication hub (postMessage API)
- Shared data storage (sharedData object)
- Scenario synchronization (P50/P75/P90)
- Settings persistence (localStorage)

**Key Files**:
- `shell.js` - Communication hub, message handlers
- `index.html` - Navigation tabs, iframe container

#### 2. Configuration Module (Port 9002)
**Responsibilities**:
- Data file upload (CSV/Excel)
- PV system configuration
- PVGIS integration for irradiance data
- Analysis trigger

#### 3. Consumption Module (Port 9003)
**Responsibilities**:
- Consumption data visualization
- Hourly/daily/monthly charts
- Heatmap generation
- Load profile analysis

#### 4. Production Module (Port 9004)
**Responsibilities**:
- PV production analysis
- **P50/P75/P90 scenario selector**
- Monthly production table with EU formatting
- Auto-consumption statistics
- Grid export/import calculations

**Key Features**:
- Floating scenario selector (top-right)
- Dynamic hourly calculations
- Scenario synchronization with Shell

#### 5. Economics Module (Port 9006)
**Responsibilities**:
- EaaS (Energy as a Service) model
- Ownership model analysis
- NPV, IRR, LCOE calculations
- 25-year cash flow projection
- Scenario-aware calculations

#### 6. ESG Module (Port 9008)
**Responsibilities**:
- CO2 emission reduction
- Tree equivalent calculation
- Water savings estimation
- Environmental impact reporting

#### 7. Other Modules
- **Admin** (9001) - User management
- **Comparison** (9005) - Variant analysis
- **Settings** (9007) - System parameters
- **Energy Prices** (9009) - TGE/ENTSO-E data
- **Reports** (9010) - PDF generation

### Backend Services

#### 1. Data Analysis Service (Port 8001)
**Technology**: Python 3.11 + FastAPI + Pandas
**Responsibilities**:
- Process CSV/Excel files
- Parse various timestamp formats
- Aggregate to hourly intervals
- Calculate consumption statistics
- Generate heatmap data

**API Endpoints**:
- `POST /upload/csv` - Upload CSV file
- `POST /upload/excel` - Upload Excel file
- `GET /statistics` - Consumption statistics
- `GET /hourly-data` - Hourly data
- `GET /heatmap` - Heatmap matrices
- `GET /health` - Health check

#### 2. PV Calculation Service (Port 8002)
**Technology**: Python 3.11 + FastAPI + pvlib
**Responsibilities**:
- PV generation simulation
- PVGIS data integration
- Multi-variant analysis
- Scenario factor application (P50/P75/P90)

**Key Features**:
- Kasten-Young air mass model
- Ineichen clear sky model
- Temperature derating
- Incidence Angle Modifier (IAM)

**API Endpoints**:
- `POST /analyze` - Full analysis
- `POST /generate-profile` - PV profile
- `GET /monthly-production` - Monthly breakdown
- `GET /health` - Health check (includes pvlib version)

#### 3. Economics Service (Port 8003)
**Technology**: Python 3.11 + FastAPI + NumPy
**Responsibilities**:
- NPV calculation with degradation
- IRR calculation (Newton-Raphson)
- LCOE calculation
- Sensitivity analysis

**API Endpoints**:
- `POST /analyze` - Economic analysis
- `POST /comprehensive-sensitivity` - Multi-parameter sensitivity
- `GET /default-parameters` - Default values
- `GET /health` - Health check

#### 4. Energy Prices Service (Port 8010)
**Responsibilities**:
- TGE price fetching
- ENTSO-E integration
- Historical price data
- Price caching

#### 5. Reports Service (Port 8011)
**Technology**: Python + ReportLab
**Responsibilities**:
- PDF report generation
- Charts and visualizations
- Data export

#### 6. Supporting Services
- **Advanced Analytics** (8004) - Load duration curves, KPIs
- **Typical Days** (8005) - Daily pattern analysis

## Data Flow

### Upload and Analysis Flow
```
User → Config Module → Data Analysis API
                          ↓
                   Parse & Validate
                          ↓
                   Store in Memory
                          ↓
Config Module → PV Calculation API
                          ↓
                   Generate Profile
                          ↓
                   Run Simulations
                          ↓
                   Find Variants (A/B/C/D)
                          ↓
Shell ← ANALYSIS_COMPLETE ← Config Module
  │
  └──► Broadcast to All Modules
```

### Scenario Change Flow
```
Production Module
      │
      │ setProductionScenario('P75')
      ▼
      │ PRODUCTION_SCENARIO_CHANGED
      │ { scenario: 'P75', source: 'production' }
      ▼
Shell (port 9000)
      │
      │ sharedData.currentScenario = 'P75'
      │ localStorage.setItem('pv_current_scenario', 'P75')
      │
      │ SCENARIO_CHANGED
      │ { scenario: 'P75', source: 'production' }
      ▼
All Modules (via iframe postMessage)
      │
      │ Economics: recalculate with 0.97 factor
      │ ESG: recalculate CO2 savings
      │ Production: update statistics
      ▼
```

## Docker Deployment

### Container Architecture
```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Host                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │           pv-optimizer-network (bridge)                │ │
│  │                                                        │ │
│  │  Frontend Containers        Backend Containers         │ │
│  │  ┌──────────────────┐      ┌──────────────────┐       │ │
│  │  │ shell      :9000 │      │ data-analysis:8001│       │ │
│  │  │ config     :9002 │      │ pv-calc      :8002│       │ │
│  │  │ consumption:9003 │      │ economics    :8003│       │ │
│  │  │ production :9004 │      │ adv-analytics:8004│       │ │
│  │  │ comparison :9005 │      │ typical-days :8005│       │ │
│  │  │ economics  :9006 │      │ energy-prices:8010│       │ │
│  │  │ settings   :9007 │      │ reports      :8011│       │ │
│  │  │ esg        :9008 │      └──────────────────┘       │ │
│  │  │ prices     :9009 │                                  │ │
│  │  │ reports    :9010 │                                  │ │
│  │  └──────────────────┘                                  │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Resource Allocation

| Service | CPU Request | Memory Limit |
|---------|-------------|--------------|
| Frontend modules | 100m | 128Mi |
| Data Analysis | 250m | 512Mi |
| PV Calculation | 250m | 512Mi |
| Economics | 250m | 512Mi |
| Energy Prices | 100m | 256Mi |
| Reports | 250m | 512Mi |

## Security

### Container Security
- All services run as non-root users
- Minimal base images (python:3.11-slim, nginx:alpine)
- Health checks for all services
- No hardcoded credentials

### Network Security
- Services communicate within private Docker network
- Only frontend modules exposed externally
- CORS configured for API access

### Data Security
- Stateless design (no persistent data in containers)
- Uploaded data stored in memory only
- Settings in browser localStorage

## Monitoring & Health

### Health Checks
All services implement `/health` endpoints:
```bash
curl http://localhost:8001/health  # Data Analysis
curl http://localhost:8002/health  # PV Calculation (+ pvlib version)
curl http://localhost:8003/health  # Economics
curl http://localhost:8010/health  # Energy Prices
curl http://localhost:8011/health  # Reports
```

### Shell Health Display
Backend service status shown in shell footer.

## Technology Stack

### Backend
- **Python 3.11**: Modern Python with type hints
- **FastAPI**: High-performance async API framework
- **Pandas**: Data processing
- **NumPy**: Numerical calculations
- **pvlib**: PV system modeling
- **ReportLab**: PDF generation
- **Uvicorn**: ASGI server

### Frontend
- **HTML5/CSS3/ES6**: Modern web standards
- **Chart.js**: Interactive charts
- **Nginx**: Web server
- **postMessage API**: Inter-module communication

### Infrastructure
- **Docker**: Containerization
- **Docker Compose**: Orchestration
- **Nginx**: Reverse proxy and static serving

## Development Workflow

### Local Development
```bash
# Run single module
cd services/frontend-production
python -m http.server 9004
```

### Docker Development
```bash
# Build and run all
docker-compose up -d --build

# Rebuild single module
docker-compose build frontend-production
docker-compose up -d frontend-production

# View logs
docker-compose logs -f frontend-production
```

### Cache Busting
Update timestamp in index.html after changes:
```html
<script src="production.js?t=1733222100"></script>
```

## Troubleshooting

### Common Issues

1. **Module not loading**:
   ```bash
   docker ps | grep pv-
   docker logs pv-frontend-production
   ```

2. **Scenario not syncing**:
   - Check browser console for postMessage errors
   - Verify `localStorage.getItem('pv_current_scenario')`

3. **Data not appearing**:
   - Check sharedData in shell console
   - Verify ANALYSIS_COMPLETE message sent

4. **API errors**:
   - Check backend logs: `docker-compose logs pv-calculation`
   - Verify CORS headers

---

**v1.8** - PV Optimizer Architecture Documentation
