# Testing Guide - PV Optimizer

## 🧪 Testing Strategy

This document describes how to test the PV Optimizer microservices.

## Unit Testing (Individual Services)

### Data Analysis Service

```bash
cd services/data-analysis

# Test health endpoint
curl http://localhost:8001/health

# Test statistics (after data upload)
curl http://localhost:8001/statistics

# Test upload CSV
curl -X POST http://localhost:8001/upload/csv \
  -F "file=@sample_data.csv"
```

### PV Calculation Service

```bash
# Test health
curl http://localhost:8002/health

# Test PV profile generation
curl -X POST http://localhost:8002/generate-profile \
  -H "Content-Type: application/json" \
  -d '{
    "pv_type": "ground_s",
    "yield_target": 1050,
    "dc_ac_ratio": 1.2,
    "latitude": 52.0
  }'

# Test simulation
curl -X POST http://localhost:8002/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "capacity": 10000,
    "pv_profile": [0.0, 0.0, 0.1, 0.3, 0.5, 0.6],
    "consumption": [1000, 900, 800, 850, 900, 950],
    "dc_ac_ratio": 1.2
  }'
```

### Economics Service

```bash
# Test health
curl http://localhost:8003/health

# Get default parameters
curl http://localhost:8003/default-parameters

# Test economic analysis
curl -X POST http://localhost:8003/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "variant": {
      "capacity": 10000,
      "production": 10500000,
      "self_consumed": 9000000,
      "exported": 1500000,
      "auto_consumption_pct": 85.7,
      "coverage_pct": 45.2
    },
    "parameters": {
      "energy_price": 450,
      "feed_in_tariff": 0,
      "investment_cost": 3500,
      "export_mode": "zero"
    }
  }'
```

## Integration Testing

### Full Workflow Test

```bash
# 1. Upload data
curl -X POST http://localhost:8001/upload/csv \
  -F "file=@test_data.csv" \
  -o upload_response.json

# 2. Get statistics
curl http://localhost:8001/statistics \
  -o stats_response.json

# 3. Get consumption data
curl "http://localhost:8001/hourly-data?month=0" \
  -o hourly_data.json

# 4. Generate PV profile
curl -X POST http://localhost:8002/generate-profile \
  -H "Content-Type: application/json" \
  -d '{"pv_type": "ground_s", "yield_target": 1050, "dc_ac_ratio": 1.2}' \
  -o pv_profile.json

# 5. Run analysis
# (combine consumption from step 3 with PV config)
curl -X POST http://localhost:8002/analyze \
  -H "Content-Type: application/json" \
  -d @analysis_request.json \
  -o analysis_results.json

# 6. Economic analysis on variant B
# (use variant data from step 5)
curl -X POST http://localhost:8003/analyze \
  -H "Content-Type: application/json" \
  -d @economics_request.json \
  -o economics_results.json
```

## Load Testing

### Using Apache Bench

```bash
# Test data analysis endpoint
ab -n 100 -c 10 http://localhost:8001/health

# Test PV calculation
ab -n 100 -c 10 -p pv_profile.json \
  -T application/json \
  http://localhost:8002/generate-profile
```

### Using wrk

```bash
# Install wrk first
# Test frontend
wrk -t4 -c100 -d30s http://localhost/

# Test API endpoint
wrk -t2 -c50 -d30s http://localhost:8001/health
```

## Docker Container Testing

### Health Check Tests

```bash
# Check container health
docker inspect pv-data-analysis | grep -A5 Health

# Check all container statuses
docker-compose ps

# Expected: All should show "Up (healthy)"
```

### Resource Usage Tests

```bash
# Monitor resource usage
docker stats --no-stream

# Check specific container
docker stats pv-data-analysis --no-stream
```

### Network Tests

```bash
# Test inter-container communication
docker exec pv-frontend curl http://data-analysis:8001/health
docker exec pv-frontend curl http://pv-calculation:8002/health
docker exec pv-frontend curl http://economics:8003/health
```

## Kubernetes Testing

### Pod Health Tests

```bash
# Check pod status
kubectl get pods -n pv-optimizer

# Check pod health
kubectl get pods -n pv-optimizer \
  -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready

# Describe pod
kubectl describe pod <pod-name> -n pv-optimizer
```

### Service Tests

```bash
# List services
kubectl get svc -n pv-optimizer

# Test service from another pod
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -n pv-optimizer -- \
  curl http://data-analysis:8001/health

# Port forward and test locally
kubectl port-forward svc/data-analysis 8001:8001 -n pv-optimizer
curl http://localhost:8001/health
```

### Scaling Tests

```bash
# Scale up
kubectl scale deployment/data-analysis --replicas=5 -n pv-optimizer

# Watch scaling
kubectl get pods -n pv-optimizer -w

# Test load distribution
for i in {1..10}; do
  kubectl run test-$i -it --rm --image=curlimages/curl --restart=Never -n pv-optimizer -- \
    curl http://data-analysis:8001/health
done
```

## Frontend Testing

### Browser Tests

1. **Manual UI Test**:
   - Open http://localhost
   - Check all tabs load
   - Upload sample file
   - Run analysis
   - Check charts render
   - Export results

2. **Console Tests**:
```javascript
// Open browser console on http://localhost

// Test API client
await apiClient.checkHealth()

// Test file upload (need file input)
const file = document.getElementById('loadFile').files[0];
await apiClient.uploadCSV(file)

// Test statistics
await apiClient.getStatistics()
```

### Automated Browser Tests (Selenium example)

```python
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

driver = webdriver.Chrome()
driver.get("http://localhost")

# Wait for page load
wait = WebDriverWait(driver, 10)
element = wait.until(EC.presence_of_element_located((By.ID, "loadFile")))

# Test file upload
file_input = driver.find_element(By.ID, "loadFile")
file_input.send_keys("/path/to/test_data.csv")

# Wait for upload
wait.until(EC.presence_of_element_located((By.CLASS_NAME, "success")))

# Click run analysis
run_button = driver.find_element(By.XPATH, "//button[contains(text(), 'RUN ANALYSIS')]")
run_button.click()

# Wait for results
wait.until(EC.presence_of_element_located((By.ID, "variantResults")))

driver.quit()
```

## Performance Benchmarks

### Expected Response Times

| Endpoint | Expected Time | Max Acceptable |
|----------|--------------|----------------|
| /health | < 10ms | 50ms |
| /upload/csv (1MB) | < 2s | 5s |
| /statistics | < 100ms | 500ms |
| /generate-profile | < 500ms | 2s |
| /analyze (full) | < 10s | 30s |
| /economics/analyze | < 200ms | 1s |

### Memory Usage

| Service | Expected RAM | Max RAM |
|---------|--------------|---------|
| Frontend | 50MB | 128MB |
| Data Analysis | 200MB | 512MB |
| PV Calculation | 150MB | 512MB |
| Economics | 100MB | 512MB |

## Error Testing

### Test Error Handling

```bash
# Test with invalid file
curl -X POST http://localhost:8001/upload/csv \
  -F "file=@invalid_file.txt"

# Expected: 400 Bad Request with error message

# Test with missing data
curl -X POST http://localhost:8002/simulate \
  -H "Content-Type: application/json" \
  -d '{}'

# Expected: 422 Validation Error

# Test non-existent endpoint
curl http://localhost:8001/nonexistent

# Expected: 404 Not Found
```

## Continuous Integration Tests

### GitHub Actions Example

```yaml
name: Test PV Optimizer

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v2

    - name: Build images
      run: docker-compose build

    - name: Start services
      run: docker-compose up -d

    - name: Wait for services
      run: sleep 30

    - name: Test health endpoints
      run: |
        curl -f http://localhost:8001/health
        curl -f http://localhost:8002/health
        curl -f http://localhost:8003/health

    - name: Test frontend
      run: curl -f http://localhost/

    - name: Check container logs
      if: failure()
      run: docker-compose logs

    - name: Cleanup
      run: docker-compose down
```

## Test Data

### Sample CSV Data
```csv
Timestamp,kW
2024-01-01 00:00:00,1250.5
2024-01-01 00:15:00,1180.3
2024-01-01 00:30:00,1120.8
2024-01-01 00:45:00,1090.2
2024-01-01 01:00:00,1050.0
```

### Generate Test Data (Python)

```python
import pandas as pd
import numpy as np

# Generate 1 year of hourly data
dates = pd.date_range('2024-01-01', '2024-12-31 23:00:00', freq='H')
np.random.seed(42)

# Simulate load with daily and weekly patterns
hours = np.arange(len(dates))
daily_pattern = 1000 + 500 * np.sin(2 * np.pi * (hours % 24) / 24)
weekly_pattern = 100 * np.sin(2 * np.pi * (hours % (24*7)) / (24*7))
noise = np.random.normal(0, 50, len(dates))

power = daily_pattern + weekly_pattern + noise
power = np.maximum(power, 0)  # No negative values

df = pd.DataFrame({'Timestamp': dates, 'kW': power})
df.to_csv('test_consumption_data.csv', index=False)
```

## Troubleshooting Tests

### Common Test Failures

1. **Service not responding**:
```bash
# Check if container is running
docker ps | grep pv-

# Check logs
docker logs <container-name>

# Restart service
docker-compose restart <service-name>
```

2. **Timeout errors**:
```bash
# Increase timeout
curl --max-time 60 http://localhost:8001/health

# Check resource usage
docker stats
```

3. **Connection refused**:
```bash
# Check if port is bound
netstat -tulpn | grep 8001

# Check firewall
sudo ufw status
```

## Test Reports

### Generate Test Report

```bash
#!/bin/bash
echo "PV Optimizer Test Report"
echo "========================"
echo ""

echo "Service Health:"
curl -s http://localhost:8001/health | jq .
curl -s http://localhost:8002/health | jq .
curl -s http://localhost:8003/health | jq .

echo ""
echo "Container Status:"
docker-compose ps

echo ""
echo "Resource Usage:"
docker stats --no-stream

echo ""
echo "Test Date: $(date)"
```

## Monitoring Tests

### Prometheus Queries (if configured)

```promql
# Request rate
rate(http_requests_total[5m])

# Error rate
rate(http_requests_total{status=~"5.."}[5m])

# Response time
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))
```

---

**Testing is complete when all endpoints respond correctly and performance meets benchmarks.**
