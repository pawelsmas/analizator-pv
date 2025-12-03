# Testing Guide - PV Optimizer v1.8

## Testing Strategy

This document describes how to test the PV Optimizer micro-frontend application.

## Service Health Tests

### Backend Services

```bash
# Data Analysis
curl http://localhost:8001/health

# PV Calculation (includes pvlib version)
curl http://localhost:8002/health

# Economics
curl http://localhost:8003/health

# Advanced Analytics
curl http://localhost:8004/health

# Typical Days
curl http://localhost:8005/health

# Energy Prices
curl http://localhost:8010/health

# Reports
curl http://localhost:8011/health
```

### Frontend Modules

```bash
# Shell
curl http://localhost:9000

# All modules (9001-9010)
for port in 9001 9002 9003 9004 9005 9006 9007 9008 9009 9010; do
  echo "Testing port $port..."
  curl -s -o /dev/null -w "%{http_code}" http://localhost:$port
  echo ""
done
```

## Unit Testing (Individual Services)

### Data Analysis Service (8001)

```bash
# Test health endpoint
curl http://localhost:8001/health

# Test statistics (after data upload)
curl http://localhost:8001/statistics

# Test upload CSV
curl -X POST http://localhost:8001/upload/csv \
  -F "file=@sample_data.csv"
```

### PV Calculation Service (8002)

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

# Test with scenario
curl -X POST http://localhost:8002/generate-profile \
  -H "Content-Type: application/json" \
  -d '{
    "pv_type": "ground_s",
    "yield_target": 1050,
    "dc_ac_ratio": 1.2,
    "latitude": 52.0,
    "scenario": "P75"
  }'
```

### Economics Service (8003)

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
curl -X POST http://localhost:8002/analyze \
  -H "Content-Type: application/json" \
  -d @analysis_request.json \
  -o analysis_results.json

# 6. Economic analysis
curl -X POST http://localhost:8003/analyze \
  -H "Content-Type: application/json" \
  -d @economics_request.json \
  -o economics_results.json
```

## Frontend Testing

### P50/P75/P90 Scenario Testing

1. **Open Production Module**: http://localhost:9000 → Production tab

2. **Test Scenario Selector**:
   - Click P50 button → verify green active state
   - Click P75 button → verify blue active state
   - Click P90 button → verify red active state

3. **Verify Statistics Update**:
   - Check "Roczna Produkcja" changes with scenario
   - Check "Autokonsumpcja" percentage changes
   - Check "Samowystarczalnosc" percentage changes
   - Check "Pobor z Sieci" updates

4. **Console Verification**:
```javascript
// Open browser console (F12)
// Should see logs like:
// 📊 Scenario changed to: P75
// 📊 Final calculated values: {...}
```

### Inter-Module Communication Testing

1. **Scenario Sync Test**:
   - Change scenario in Production module
   - Switch to Economics module
   - Verify Economics uses same scenario

2. **Console Test**:
```javascript
// In shell's console
localStorage.getItem('pv_current_scenario')
// Should return current scenario: "P50", "P75", or "P90"
```

3. **postMessage Test**:
```javascript
// In any module's console
window.addEventListener('message', e => console.log('Received:', e.data));
// Change scenario and watch for SCENARIO_CHANGED messages
```

### European Number Formatting Test

1. **Production Table**:
   - Open Production module
   - Check monthly production table
   - Values should use comma as decimal (e.g., "142,27" not "142.27")
   - Thousands should use space (e.g., "1 234,56")

2. **Statistics Cards**:
   - All values should use EU formatting
   - Example: "6,75 GWh" not "6.75 GWh"

## Docker Container Testing

### Health Check Tests

```bash
# Check container health
docker inspect pv-frontend-production | grep -A5 Health

# Check all container statuses
docker-compose ps

# Expected: All should show "Up (healthy)"
```

### Resource Usage Tests

```bash
# Monitor resource usage
docker stats --no-stream

# Check specific container
docker stats pv-frontend-production --no-stream
```

### Network Tests

```bash
# Test inter-container communication
docker exec pv-frontend-shell curl http://data-analysis:8001/health
docker exec pv-frontend-shell curl http://pv-calculation:8002/health
docker exec pv-frontend-shell curl http://economics:8003/health
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
| Scenario change (frontend) | < 100ms | 500ms |

### Memory Usage

| Service | Expected RAM | Max RAM |
|---------|--------------|---------|
| Frontend modules | 50MB | 128MB |
| Data Analysis | 200MB | 512MB |
| PV Calculation | 150MB | 512MB |
| Economics | 100MB | 512MB |
| Energy Prices | 100MB | 256MB |
| Reports | 150MB | 512MB |

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

### Frontend Error Scenarios

1. **No Data Loaded**:
   - Open Production without uploading data
   - Should show "Brak Danych Produkcji PV" message

2. **Module Offline**:
   - Stop backend service
   - Verify error handling in console

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
power = np.maximum(power, 0)

df = pd.DataFrame({'Timestamp': dates, 'kW': power})
df.to_csv('test_consumption_data.csv', index=False)
```

## Troubleshooting Tests

### Common Test Failures

1. **Service not responding**:
```bash
docker ps | grep pv-
docker logs <container-name>
docker-compose restart <service-name>
```

2. **Scenario not syncing**:
```bash
# Check localStorage
# In browser console:
localStorage.getItem('pv_current_scenario')

# Check shell logs
docker logs pv-frontend-shell
```

3. **Cache issues**:
```bash
# Rebuild with no cache
docker-compose build frontend-production --no-cache
docker-compose up -d frontend-production

# Or update timestamp in index.html
```

4. **Connection refused**:
```bash
# Check if port is bound
netstat -an | findstr 8001

# Check container network
docker network inspect pv-optimizer-network
```

## Test Reports

### Generate Test Report

```bash
#!/bin/bash
echo "PV Optimizer v1.8 Test Report"
echo "============================="
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

## Checklist: v1.8 Features

### P50/P75/P90 Scenarios
- [ ] Floating selector visible in Production module
- [ ] P50 shows 100% factor
- [ ] P75 shows 97% factor
- [ ] P90 shows 94% factor
- [ ] Button colors correct (green/blue/red)
- [ ] Statistics recalculate on change
- [ ] Scenario persists in localStorage
- [ ] Economics module receives scenario changes

### European Number Formatting
- [ ] Monthly production table uses comma decimal
- [ ] Statistics cards use comma decimal
- [ ] Thousands separator is space
- [ ] All modules consistent

### ESG Module
- [ ] CO2 reduction displays
- [ ] Tree equivalent calculates
- [ ] Water savings shows
- [ ] Values update with scenario

### Inter-Module Communication
- [ ] Shell receives PRODUCTION_SCENARIO_CHANGED
- [ ] Shell broadcasts SCENARIO_CHANGED
- [ ] Economics handles scenario updates
- [ ] Settings sync works

---

**v1.8** - PV Optimizer Testing Guide
