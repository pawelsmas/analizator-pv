# Local Development Guide

Quick start guide for running the BESS Dispatch service locally.

## Prerequisites

- Docker and Docker Compose
- Python 3.11+
- curl (for smoke tests)

## Quick Start

### Start Everything

```bash
make dev-up
```

This command:
1. Builds and starts the bess-dispatch service
2. Waits for the backend to be ready
3. Optionally starts the frontend
4. Prints URLs when ready

### Run a Demo

```bash
make demo
```

Runs a sample sizing request and displays:
- Run ID
- Recommended variant details
- Links to reports and Run Explorer

### Stop Everything

```bash
make dev-down
```

## Endpoints

| Service | URL | Description |
|---------|-----|-------------|
| Backend | http://localhost:8031 | BESS Dispatch API |
| API Docs | http://localhost:8031/docs | OpenAPI/Swagger |
| Metrics | http://localhost:8031/metrics | Prometheus metrics |
| Frontend | http://localhost:3000 | UI (if available) |

## Testing

### Smoke Tests

```bash
make smoke
```

Runs basic API health checks.

### Contract Tests

```bash
make test-contract
```

Runs full pytest contract test suite.

### Validation

```bash
make validate
```

Runs scenario validation tests.

## Troubleshooting

### Service Not Starting

Check logs:
```bash
docker compose logs bess-dispatch
```

### Port Already in Use

Stop any existing services:
```bash
make dev-down
docker compose down
```

### Waiting for Services

Use the wait script directly:
```bash
python scripts/dev/wait_http.py http://localhost:8031/health --timeout 120
```
