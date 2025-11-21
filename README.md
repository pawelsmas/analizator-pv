# PV Optimizer Pro - Microservices Edition

Advanced PV (Photovoltaic) system optimization tool built with microservices architecture.

## 🏗️ Architecture

The application is divided into the following microservices:

### Backend Services (Python/FastAPI)
- **data-analysis** (Port 8001): Consumption data processing and analysis
- **pv-calculation** (Port 8002): PV generation simulations and calculations
- **economics** (Port 8003): Economic analysis and financial modeling

### Frontend Service
- **frontend** (Port 80): Web UI built with HTML/JS and Nginx

## 📋 Prerequisites

### For Docker Deployment
- Docker 20.10+
- Docker Compose 2.0+

### For Kubernetes Deployment
- Kubernetes cluster (minikube, k3s, or cloud provider)
- kubectl configured
- Docker for building images

## 🚀 Quick Start

### Option 1: Docker Compose (Recommended for Development)

1. **Build images:**
   ```bash
   # Linux/Mac
   ./deployment/build.sh

   # Windows
   deployment\build.bat
   ```

2. **Deploy with Docker Compose:**
   ```bash
   # Linux/Mac
   ./deployment/deploy-docker.sh

   # Windows
   docker-compose up -d
   ```

3. **Access the application:**
   - Frontend: http://localhost
   - Data Analysis API: http://localhost:8001/docs
   - PV Calculation API: http://localhost:8002/docs
   - Economics API: http://localhost:8003/docs

### Option 2: Kubernetes (Production)

1. **Build images:**
   ```bash
   ./deployment/build.sh
   ```

2. **Deploy to Kubernetes:**
   ```bash
   ./deployment/deploy-k8s.sh
   ```

3. **Add to /etc/hosts (Linux/Mac) or C:\Windows\System32\drivers\etc\hosts (Windows):**
   ```
   127.0.0.1 pv-optimizer.local
   ```

4. **Access the application:**
   - Frontend: http://pv-optimizer.local

## 📁 Project Structure

```
ANALIZATOR PV/
├── services/
│   ├── data-analysis/       # Data processing service
│   │   ├── app.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   ├── pv-calculation/      # PV calculation service
│   │   ├── app.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   ├── economics/           # Economics service
│   │   ├── app.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   └── frontend/            # Frontend service
│       ├── index.html
│       ├── styles.css
│       ├── api.js
│       ├── app.js
│       ├── nginx.conf
│       └── Dockerfile
├── k8s/                     # Kubernetes manifests
│   ├── namespace.yaml
│   ├── data-analysis-deployment.yaml
│   ├── pv-calculation-deployment.yaml
│   ├── economics-deployment.yaml
│   ├── frontend-deployment.yaml
│   ├── ingress.yaml
│   └── kustomization.yaml
├── deployment/              # Deployment scripts
│   ├── build.sh
│   ├── build.bat
│   ├── deploy-docker.sh
│   └── deploy-k8s.sh
├── docker-compose.yml       # Docker Compose configuration
└── README.md
```

## 🔧 Development

### Running Individual Services Locally

#### Data Analysis Service
```bash
cd services/data-analysis
pip install -r requirements.txt
python app.py
```

#### PV Calculation Service
```bash
cd services/pv-calculation
pip install -r requirements.txt
python app.py
```

#### Economics Service
```bash
cd services/economics
pip install -r requirements.txt
python app.py
```

#### Frontend Service
```bash
cd services/frontend
# Use any static file server, e.g.:
python -m http.server 8080
```

## 🐳 Docker Commands

### View logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f data-analysis
```

### Restart services
```bash
docker-compose restart
```

### Stop services
```bash
docker-compose down
```

### Rebuild specific service
```bash
docker-compose build data-analysis
docker-compose up -d data-analysis
```

## ☸️ Kubernetes Commands

### Check deployment status
```bash
kubectl get all -n pv-optimizer
```

### View logs
```bash
# Specific pod
kubectl logs -f <pod-name> -n pv-optimizer

# Deployment
kubectl logs -f deployment/data-analysis -n pv-optimizer
```

### Scale deployment
```bash
kubectl scale deployment/data-analysis --replicas=3 -n pv-optimizer
```

### Delete deployment
```bash
kubectl delete -f k8s/ -n pv-optimizer
```

### Port forward (for testing)
```bash
kubectl port-forward svc/frontend 8080:80 -n pv-optimizer
```

## 📊 API Documentation

Each backend service provides interactive API documentation via FastAPI:

- Data Analysis: http://localhost:8001/docs
- PV Calculation: http://localhost:8002/docs
- Economics: http://localhost:8003/docs

## 🔍 Health Checks

All services provide health check endpoints:

```bash
curl http://localhost:8001/health  # Data Analysis
curl http://localhost:8002/health  # PV Calculation
curl http://localhost:8003/health  # Economics
```

## 🧪 Testing

### Test Data Analysis Service
```bash
curl -X POST http://localhost:8001/upload/csv \
  -F "file=@sample_data.csv"
```

### Test PV Calculation Service
```bash
curl -X POST http://localhost:8002/generate-profile \
  -H "Content-Type: application/json" \
  -d '{"pv_type": "ground_s", "yield_target": 1050, "dc_ac_ratio": 1.2}'
```

### Test Economics Service
```bash
curl http://localhost:8003/default-parameters
```

## 🔐 Security Considerations

- All services run as non-root users in containers
- CORS is configured for local development (adjust for production)
- No sensitive data is stored in containers (stateless design)
- Health checks ensure service availability
- Resource limits are set in Kubernetes deployments

## 🌟 Features

- **Modular Architecture**: Each service can be developed, deployed, and scaled independently
- **Containerized**: Full Docker support for consistent deployments
- **Kubernetes Ready**: Production-ready Kubernetes manifests
- **Auto-scaling**: Horizontal Pod Autoscaling support in Kubernetes
- **Health Monitoring**: Built-in health checks and readiness probes
- **API Documentation**: Auto-generated API docs with FastAPI
- **Responsive UI**: Modern web interface with real-time charts

## 🛠️ Troubleshooting

### Services not starting
```bash
# Check logs
docker-compose logs

# Check service health
docker-compose ps
```

### Port conflicts
If ports 80, 8001, 8002, or 8003 are already in use, modify the port mappings in `docker-compose.yml`.

### Kubernetes pods not running
```bash
# Describe pod to see events
kubectl describe pod <pod-name> -n pv-optimizer

# Check events
kubectl get events -n pv-optimizer --sort-by='.lastTimestamp'
```

## 📝 License

This project is proprietary software.

## 👥 Authors

PV Optimizer Development Team

## 🔄 Version

**v2.0** - Microservices Edition

---

For more information, visit the project documentation or contact the development team.
