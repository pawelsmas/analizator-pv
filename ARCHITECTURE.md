# PV Optimizer - Architecture Documentation

## Overview

PV Optimizer is a microservices-based application for photovoltaic system analysis and optimization. The application is designed to run in containerized environments (Docker) and orchestrated platforms (Kubernetes).

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Frontend                             │
│                    (Nginx + HTML/JS)                         │
│                       Port: 80                               │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ HTTP/REST API
                       │
         ┌─────────────┼─────────────┐
         │             │             │
         ▼             ▼             ▼
┌────────────┐  ┌────────────┐  ┌────────────┐
│   Data     │  │     PV     │  │ Economics  │
│  Analysis  │  │Calculation │  │  Service   │
│  Service   │  │  Service   │  │            │
│  Port:8001 │  │ Port: 8002 │  │ Port: 8003 │
└────────────┘  └────────────┘  └────────────┘
     │               │                │
     └───────────────┴────────────────┘
              Python/FastAPI
```

## Services Description

### 1. Frontend Service
**Technology**: Nginx + HTML/CSS/JavaScript
**Port**: 80
**Responsibilities**:
- Serve static web application
- Client-side routing
- API gateway proxy
- User interface rendering

**Key Files**:
- `index.html` - Main application page
- `api.js` - API client library
- `app.js` - Application logic
- `styles.css` - Styling
- `nginx.conf` - Web server configuration

### 2. Data Analysis Service
**Technology**: Python 3.11 + FastAPI
**Port**: 8001
**Responsibilities**:
- Process uploaded consumption data (CSV/Excel)
- Parse various timestamp formats
- Aggregate data to hourly intervals
- Calculate consumption statistics
- Generate heatmap data
- Provide daily/monthly consumption analysis

**API Endpoints**:
- `POST /upload/csv` - Upload CSV file
- `POST /upload/excel` - Upload Excel file
- `GET /statistics` - Get consumption statistics
- `GET /hourly-data` - Get hourly consumption data
- `GET /daily-consumption` - Get daily aggregated data
- `GET /heatmap` - Get heatmap matrices
- `GET /health` - Health check

**Key Features**:
- Multi-format timestamp parsing
- Data validation and cleaning
- Memory-efficient processing
- Statistical analysis

### 3. PV Calculation Service
**Technology**: Python 3.11 + FastAPI
**Port**: 8002
**Responsibilities**:
- Generate realistic PV generation profiles
- Solar position calculations
- Irradiance modeling
- System simulation with DC/AC conversion
- Multi-variant analysis
- Optimization algorithms

**API Endpoints**:
- `POST /generate-profile` - Generate PV profile
- `POST /simulate` - Simulate single configuration
- `POST /analyze` - Full multi-variant analysis
- `GET /monthly-production` - Monthly production breakdown
- `GET /health` - Health check

**Key Features**:
- Solar declination and elevation calculations
- Air mass and irradiance modeling
- East-West configuration support
- DC/AC inverter clipping
- Auto-consumption optimization

### 4. Economics Service
**Technology**: Python 3.11 + FastAPI
**Port**: 8003
**Responsibilities**:
- Financial analysis (NPV, IRR, LCOE)
- Cash flow calculations
- Scenario comparison
- Sensitivity analysis
- Payback period calculation

**API Endpoints**:
- `POST /analyze` - Perform economic analysis
- `POST /compare-scenarios` - Compare multiple scenarios
- `POST /sensitivity-analysis` - Sensitivity analysis
- `GET /default-parameters` - Get default parameters
- `GET /health` - Health check

**Key Features**:
- NPV calculation with degradation
- IRR calculation (Newton-Raphson)
- LCOE (Levelized Cost of Energy)
- Multiple economic scenarios
- ROI and benefit-cost ratio

## Data Flow

### Upload and Analysis Flow
```
User → Frontend → Data Analysis Service
                    ↓
              Parse & Validate
                    ↓
              Store in Memory
                    ↓
              Return Statistics
                    ↓
                 Frontend
```

### PV Analysis Flow
```
Frontend → Data Analysis Service (get consumption)
    ↓
    → PV Calculation Service
         ↓
    Generate PV Profile
         ↓
    Run Simulations (multiple capacities)
         ↓
    Find Optimal Variants
         ↓
    Return Results → Frontend
```

### Economic Analysis Flow
```
Frontend → PV Calculation Service (get variant data)
    ↓
    → Economics Service
         ↓
    Calculate NPV, IRR, LCOE
         ↓
    Generate Cash Flows
         ↓
    Return Analysis → Frontend
```

## Deployment Architecture

### Docker Compose Deployment
```
┌─────────────────────────────────────────┐
│         Docker Host                     │
│  ┌────────────────────────────────────┐ │
│  │    pv-optimizer-network (bridge)   │ │
│  │                                    │ │
│  │  ┌──────────┐  ┌──────────┐      │ │
│  │  │  data-   │  │   pv-    │      │ │
│  │  │ analysis │  │calculation│     │ │
│  │  └──────────┘  └──────────┘      │ │
│  │                                    │ │
│  │  ┌──────────┐  ┌──────────┐      │ │
│  │  │economics │  │ frontend │      │ │
│  │  └──────────┘  └──────────┘      │ │
│  └────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### Kubernetes Deployment
```
┌───────────────────────────────────────────────┐
│          Kubernetes Cluster                   │
│  ┌─────────────────────────────────────────┐  │
│  │       Namespace: pv-optimizer           │  │
│  │                                         │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │         Ingress Controller        │  │  │
│  │  │    (pv-optimizer.local)           │  │  │
│  │  └─────────────┬────────────────────┘  │  │
│  │                │                        │  │
│  │         ┌──────┴──────┐                │  │
│  │         │             │                │  │
│  │         ▼             ▼                │  │
│  │  ┌───────────┐  ┌───────────┐         │  │
│  │  │ Frontend  │  │  Backend  │         │  │
│  │  │  Service  │  │ Services  │         │  │
│  │  │   (LB)    │  │(ClusterIP)│         │  │
│  │  └─────┬─────┘  └─────┬─────┘         │  │
│  │        │              │                │  │
│  │  ┌─────▼──────┐ ┌────▼─────┐          │  │
│  │  │ Frontend   │ │   Data   │          │  │
│  │  │Deployment  │ │ Analysis │          │  │
│  │  │ (2 pods)   │ │(2 pods)  │          │  │
│  │  └────────────┘ └──────────┘          │  │
│  │                                        │  │
│  │  ┌────────────┐ ┌──────────┐          │  │
│  │  │    PV      │ │Economics │          │  │
│  │  │Calculation │ │ Service  │          │  │
│  │  │ (2 pods)   │ │(2 pods)  │          │  │
│  │  └────────────┘ └──────────┘          │  │
│  └─────────────────────────────────────────┘  │
└───────────────────────────────────────────────┘
```

## Scaling Strategy

### Horizontal Scaling
Each service can be scaled independently:

```bash
# Scale data analysis service
kubectl scale deployment/data-analysis --replicas=5 -n pv-optimizer

# Scale with auto-scaling
kubectl autoscale deployment/data-analysis \
  --cpu-percent=70 \
  --min=2 \
  --max=10 \
  -n pv-optimizer
```

### Resource Allocation

| Service | CPU Request | CPU Limit | Memory Request | Memory Limit |
|---------|-------------|-----------|----------------|--------------|
| Frontend | 100m | 200m | 64Mi | 128Mi |
| Data Analysis | 250m | 500m | 256Mi | 512Mi |
| PV Calculation | 250m | 500m | 256Mi | 512Mi |
| Economics | 250m | 500m | 256Mi | 512Mi |

## Security

### Container Security
- All services run as non-root users
- Minimal base images (python:3.11-slim, nginx:alpine)
- No unnecessary packages
- Health checks for all services

### Network Security
- Services communicate within private network
- Only frontend exposed externally
- CORS configured for API access
- No hardcoded credentials

### Data Security
- Stateless design (no persistent data in containers)
- Uploaded data stored in memory only
- No logging of sensitive information

## Monitoring & Health

### Health Checks
All services implement health endpoints:
- `/health` - Basic health status
- Kubernetes liveness probes
- Kubernetes readiness probes

### Metrics
- Container resource usage
- Request/response times
- Error rates
- API endpoint statistics

## Development Workflow

1. **Local Development**:
   ```bash
   # Run services individually
   cd services/data-analysis
   python app.py
   ```

2. **Docker Development**:
   ```bash
   # Build and run with compose
   docker-compose up --build
   ```

3. **Kubernetes Testing**:
   ```bash
   # Deploy to local cluster
   ./deployment/deploy-k8s.sh
   ```

## CI/CD Pipeline (Recommended)

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│   Code   │───▶│  Build   │───▶│   Test   │───▶│  Deploy  │
│  Commit  │    │  Images  │    │ Services │    │   to K8s │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
                      │                               │
                      ▼                               ▼
              Docker Registry                   Production
```

## Technology Stack

### Backend
- **Python 3.11**: Modern Python with type hints
- **FastAPI**: High-performance async API framework
- **Pandas**: Data processing
- **NumPy**: Numerical calculations
- **Uvicorn**: ASGI server

### Frontend
- **HTML5/CSS3/ES6**: Modern web standards
- **Plotly.js**: Interactive charts
- **Nginx**: Web server and reverse proxy

### Infrastructure
- **Docker**: Containerization
- **Docker Compose**: Local orchestration
- **Kubernetes**: Production orchestration
- **Nginx Ingress**: Kubernetes ingress controller

## Future Enhancements

1. **Database Integration**:
   - PostgreSQL for persistent storage
   - Redis for caching

2. **Message Queue**:
   - RabbitMQ or Kafka for async processing
   - Background job processing

3. **Authentication**:
   - OAuth2/JWT authentication
   - Role-based access control

4. **Monitoring**:
   - Prometheus metrics
   - Grafana dashboards
   - ELK stack for logging

5. **Advanced Features**:
   - Machine learning predictions
   - Weather data integration
   - Real-time monitoring

## Troubleshooting

### Common Issues

1. **Service not responding**:
   - Check logs: `docker-compose logs <service>`
   - Verify health: `curl http://localhost:<port>/health`

2. **Port conflicts**:
   - Change ports in `docker-compose.yml`
   - Check running services: `netstat -an | grep LISTEN`

3. **Memory issues**:
   - Increase Docker memory limits
   - Scale down replicas
   - Optimize data processing

4. **Kubernetes deployment fails**:
   - Check events: `kubectl get events -n pv-optimizer`
   - Verify images are built
   - Check resource availability

## Contact

For questions or issues, contact the development team.
