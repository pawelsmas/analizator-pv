# Quick Start Guide - PV Optimizer

## 🚀 5-Minute Setup

### Prerequisites Check
```bash
# Check Docker
docker --version
# Should output: Docker version 20.10+

# Check Docker Compose
docker-compose --version
# Should output: Docker Compose version 2.0+
```

### Step 1: Clone and Navigate
```bash
cd "ANALIZATOR PV"
```

### Step 2: Build Images (Windows)
```bash
deployment\build.bat
```

### Step 2: Build Images (Linux/Mac)
```bash
chmod +x deployment/build.sh
./deployment/build.sh
```

### Step 3: Start Services
```bash
docker-compose up -d
```

### Step 4: Verify Services
```bash
# Check all services are running
docker-compose ps

# Expected output:
# NAME                    STATUS
# pv-data-analysis        Up (healthy)
# pv-calculation          Up (healthy)
# pv-economics            Up (healthy)
# pv-frontend             Up (healthy)
```

### Step 5: Access Application
Open browser: **http://localhost**

## 📊 First Analysis

### 1. Upload Data
- Click "Upload Consumption Data"
- Select your CSV or XLSX file with consumption data
- File should contain timestamp and power columns

### 2. Configure PV System
- **Installation Type**: Select (Ground South, Roof E-W, Ground E-W)
- **Yield**: Set target yield (default: 1050 kWh/kWp/year)
- **DC/AC Ratio**: Set ratio (default: 1.2)

### 3. Set Analysis Range
- **Min Power**: Minimum PV capacity (e.g., 1000 kWp)
- **Max Power**: Maximum PV capacity (e.g., 50000 kWp)
- **Step**: Capacity increment (e.g., 500 kWp)

### 4. Define Variants
Set self-consumption thresholds:
- **Variant A**: 95% (most conservative)
- **Variant B**: 90%
- **Variant C**: 85%
- **Variant D**: 80% (most aggressive)

### 5. Run Analysis
Click **"RUN ANALYSIS"** button

### 6. View Results
Navigate through tabs:
- ⚙️ **Configuration**: Main results and variant table
- 📊 **Consumption Analysis**: Load patterns and statistics
- ☀️ **PV Production**: Generation profiles
- ⚡ **Comparison**: Variant comparison
- 💰 **Economics**: Financial analysis

### 7. Export Results
Click **"EXPORT TO EXCEL"** to download results

## 🛠️ Using Makefile (Linux/Mac)

```bash
# Build images
make build

# Start services
make up

# View logs
make logs

# Stop services
make down

# Run tests
make test

# Get help
make help
```

## ☸️ Kubernetes Deployment

### Quick K8s Deploy
```bash
# Build images first
./deployment/build.sh

# Deploy to Kubernetes
./deployment/deploy-k8s.sh

# Add to /etc/hosts:
echo "127.0.0.1 pv-optimizer.local" | sudo tee -a /etc/hosts

# Access at:
http://pv-optimizer.local
```

## 🔍 Verify Installation

### Check Service Health
```bash
# Data Analysis Service
curl http://localhost:8001/health

# PV Calculation Service
curl http://localhost:8002/health

# Economics Service
curl http://localhost:8003/health
```

Expected response:
```json
{
  "status": "healthy"
}
```

### View API Documentation
- Data Analysis: http://localhost:8001/docs
- PV Calculation: http://localhost:8002/docs
- Economics: http://localhost:8003/docs

## 🐛 Troubleshooting

### Services won't start
```bash
# View logs
docker-compose logs

# Check specific service
docker-compose logs data-analysis
```

### Port already in use
Edit `docker-compose.yml` and change ports:
```yaml
ports:
  - "8080:80"  # Change 80 to 8080
```

### Services healthy but frontend not loading
```bash
# Restart frontend
docker-compose restart frontend

# Check nginx logs
docker-compose logs frontend
```

### Clear everything and start fresh
```bash
# Stop and remove all
docker-compose down -v

# Rebuild
docker-compose build --no-cache

# Start again
docker-compose up -d
```

## 📝 Sample Data Format

### CSV Format
```csv
Timestamp,kW
2024-01-01 00:00,1250.5
2024-01-01 00:15,1180.3
2024-01-01 00:30,1120.8
...
```

### Excel Format
| Timestamp | kW |
|-----------|-----|
| 2024-01-01 00:00 | 1250.5 |
| 2024-01-01 00:15 | 1180.3 |
| 2024-01-01 00:30 | 1120.8 |

### Supported Columns
- **Time**: Timestamp, Data, Czas, Date, DateTime, Time
- **Power**: kW, Moc, Power
- **Energy**: kWh, Energia, Energy

## 🎯 Example Workflow

1. **Morning**: Upload year of consumption data
2. **Configure**: Set PV parameters for your location
3. **Analyze**: Run multi-variant analysis
4. **Compare**: Review different capacity scenarios
5. **Economics**: Calculate NPV, IRR, payback
6. **Export**: Download results for reporting

## 🔄 Updates and Maintenance

### Update single service
```bash
# Rebuild specific service
docker-compose build data-analysis

# Restart it
docker-compose up -d data-analysis
```

### View resource usage
```bash
docker stats
```

### Backup configuration
```bash
# Export current settings
docker-compose config > docker-compose.backup.yml
```

## 📞 Get Help

- Check [README.md](README.md) for detailed documentation
- Review [ARCHITECTURE.md](ARCHITECTURE.md) for system design
- View logs for error messages
- Check API docs at `/docs` endpoints

## ✅ Success Checklist

- [ ] Docker and Docker Compose installed
- [ ] All images built successfully
- [ ] All services show "healthy" status
- [ ] Frontend loads at http://localhost
- [ ] Can access API documentation
- [ ] Sample data uploaded successfully
- [ ] Analysis completes without errors
- [ ] Results can be exported to Excel

---

**Ready to optimize!** 🎉
