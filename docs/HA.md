# BESS Dispatch High Availability (HA) Guide

Version: v3.9.0

## Overview

BESS Dispatch supports two HA modes that control how the service behaves when external dependencies (Redis, S3, database) become unavailable.

## HA Modes

### Permissive Mode (Default)

```bash
HA_MODE=permissive  # or unset
```

In permissive mode, the service falls back to local/in-memory alternatives when external dependencies are unavailable:

| Dependency | Fallback Behavior |
|------------|-------------------|
| Redis | In-memory cache (per-instance) |
| S3 | Local filesystem storage |
| Database | SQLite local file |

**Use Cases**:
- Development environments
- Single-instance deployments
- Non-critical workloads where degraded operation is acceptable

### Strict Mode (Fail-Closed)

```bash
HA_MODE=strict
```

In strict mode, the service rejects requests when external dependencies are unavailable:

| Dependency | Behavior When Unavailable |
|------------|---------------------------|
| Redis | 503 Service Unavailable |
| S3 | 503 Service Unavailable |
| Database | 503 Service Unavailable |

**Use Cases**:
- Production HA deployments
- Multi-instance clusters
- Environments where data consistency is critical
- Compliance requirements for deterministic behavior

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `HA_MODE` | `permissive` or `strict` | `permissive` |
| `REDIS_URL` | Redis connection URL | `` |
| `S3_BUCKET` | S3 bucket for report storage | `` |
| `DATABASE_URL` | Primary database URL | `` |

### Strict Mode Requirements

When `HA_MODE=strict`, the following must be configured:

```bash
# Required in strict mode
HA_MODE=strict
REDIS_URL=redis://redis:6379/0
S3_BUCKET=bess-reports

# Service will fail to start if these are missing
```

## Health Endpoint

The `/health` endpoint includes HA status:

```json
{
  "status": "healthy",
  "ha": {
    "ha_mode": "strict",
    "dependencies": {
      "redis": true,
      "s3": true,
      "database": true,
      "all_available": true
    },
    "status": "healthy",
    "fail_closed": true
  }
}
```

### Status Values

| Status | Description |
|--------|-------------|
| `healthy` | All dependencies available |
| `degraded` | One or more dependencies unavailable |

## Prometheus Metrics

### Dependency Checks

```promql
# Total dependency health checks
bess_ha_dependency_checks_total{dependency="redis|s3|database", result="success|unavailable|fallback"}

# Fallback usage (permissive mode only)
bess_ha_fallback_used_total{dependency="redis|s3|database"}

# Requests rejected (strict mode only)
bess_ha_request_rejected_total{dependency="redis|s3|database"}
```

### Example Queries

```promql
# Rejection rate in strict mode
sum(rate(bess_ha_request_rejected_total[5m])) by (dependency)

# Fallback usage rate in permissive mode
sum(rate(bess_ha_fallback_used_total[5m])) by (dependency)

# Dependency availability ratio
sum(rate(bess_ha_dependency_checks_total{result="success"}[5m]))
/
sum(rate(bess_ha_dependency_checks_total[5m]))
```

## Alerting Rules

### Strict Mode Alerts

```yaml
# Redis unavailable in strict mode
- alert: BESSRedisUnavailableStrict
  expr: |
    sum(rate(bess_ha_request_rejected_total{dependency="redis"}[5m])) > 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Redis unavailable in strict HA mode"
    description: "Requests are being rejected due to Redis unavailability"

# S3 unavailable in strict mode
- alert: BESSS3UnavailableStrict
  expr: |
    sum(rate(bess_ha_request_rejected_total{dependency="s3"}[5m])) > 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "S3 unavailable in strict HA mode"
    description: "Report generation is being rejected due to S3 unavailability"
```

### Permissive Mode Alerts

```yaml
# High fallback usage (degraded operation)
- alert: BESSHighFallbackUsage
  expr: |
    sum(rate(bess_ha_fallback_used_total[5m])) > 0.1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High fallback usage detected"
    description: "Service is operating in degraded mode with fallbacks"
```

## Kubernetes Deployment

### Strict Mode with External Dependencies

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: bess-dispatch
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: bess-dispatch
          env:
            - name: HA_MODE
              value: "strict"
            - name: REDIS_URL
              valueFrom:
                secretKeyRef:
                  name: bess-secrets
                  key: redis-url
            - name: S3_BUCKET
              value: "bess-reports-prod"
          readinessProbe:
            httpGet:
              path: /health
              port: 8031
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /health
              port: 8031
            initialDelaySeconds: 15
            periodSeconds: 20
```

### Redis Sentinel Configuration

For HA Redis with Sentinel:

```yaml
env:
  - name: REDIS_URL
    value: "redis://redis-sentinel:26379/0?sentinel=mymaster"
```

## Failure Scenarios

### Scenario 1: Redis Failure (Strict Mode)

1. Redis becomes unavailable
2. Health check detects failure, updates `redis_available = false`
3. Next cache operation calls `check_redis_available()`
4. `HAUnavailableError` raised
5. API returns 503 Service Unavailable
6. Prometheus metric `bess_ha_request_rejected_total{dependency="redis"}` incremented

### Scenario 2: Redis Failure (Permissive Mode)

1. Redis becomes unavailable
2. Health check detects failure, updates `redis_available = false`
3. Next cache operation calls `check_redis_available()`
4. Returns `False`, service uses in-memory fallback
5. Prometheus metric `bess_ha_fallback_used_total{dependency="redis"}` incremented
6. Request completes (degraded but operational)

## Best Practices

1. **Production**: Always use `HA_MODE=strict` with properly configured external dependencies
2. **Monitoring**: Set up alerts for both rejection (strict) and fallback (permissive) metrics
3. **Health Checks**: Use `/health` endpoint for load balancer health checks
4. **Graceful Degradation**: In permissive mode, monitor fallback usage and investigate root causes
5. **Testing**: Test failover scenarios regularly using chaos engineering

## Related Documentation

- [SLO.md](SLO.md) - Service Level Objectives
- [observability/ALERTS.md](observability/ALERTS.md) - Alerting rules
