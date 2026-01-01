# HA Alerting Rules (v3.5.0)

This document describes alerting rules for High Availability infrastructure components.

## Overview

These alerts monitor the health of optional HA dependencies:
- Redis (rate limiting backend)
- S3/MinIO (artifact storage)
- PostgreSQL (job store - future)

## Alert Rules

### Redis Alerts

```yaml
groups:
  - name: bess-redis
    rules:
      # Redis unavailable
      - alert: BESSRedisUnavailable
        expr: |
          sum(up{job="redis"}) == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Redis is unavailable"
          description: "Redis instance is down. Rate limiting will fall back to memory mode."
          runbook_url: "https://docs.example.com/runbooks/redis-unavailable"

      # Redis connection errors
      - alert: BESSRedisConnectionErrors
        expr: |
          rate(bess_redis_connection_errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High Redis connection error rate"
          description: "Redis connection errors detected at {{ $value }} errors/sec."

      # Redis high latency
      - alert: BESSRedisHighLatency
        expr: |
          histogram_quantile(0.99, rate(bess_redis_operation_duration_seconds_bucket[5m])) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Redis p99 latency above 100ms"
          description: "Redis operations p99 latency is {{ $value }}s."

      # Rate limit backend fallback
      - alert: BESSRateLimitFallback
        expr: |
          bess_rate_limit_backend{backend="memory"} == 1 AND bess_rate_limit_backend_configured{backend="redis"} == 1
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Rate limiting using memory fallback"
          description: "Redis was configured but unavailable. Using in-memory rate limiting (not HA)."
```

### S3/MinIO Alerts

```yaml
groups:
  - name: bess-s3
    rules:
      # S3 unavailable
      - alert: BESSS3Unavailable
        expr: |
          sum(bess_s3_health_check{status="ok"}) == 0 AND sum(bess_s3_health_check) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "S3/MinIO is unavailable"
          description: "S3 artifact storage is down. Artifact operations will fail."
          runbook_url: "https://docs.example.com/runbooks/s3-unavailable"

      # S3 high error rate
      - alert: BESSS3HighErrorRate
        expr: |
          rate(bess_s3_operation_errors_total[5m]) / rate(bess_s3_operations_total[5m]) > 0.01
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High S3 operation error rate"
          description: "S3 error rate is {{ $value | humanizePercentage }}."

      # S3 high latency
      - alert: BESSS3HighLatency
        expr: |
          histogram_quantile(0.99, rate(bess_s3_operation_duration_seconds_bucket[5m])) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "S3 p99 latency above 1s"
          description: "S3 operations p99 latency is {{ $value }}s."

      # Artifact store fallback
      - alert: BESSArtifactStoreFallback
        expr: |
          bess_artifact_store_backend{backend="local"} == 1 AND bess_artifact_store_backend_configured{backend="s3"} == 1
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Artifact store using local fallback"
          description: "S3 was configured but unavailable. Using local storage (not HA)."
```

### PostgreSQL Alerts (Future)

```yaml
groups:
  - name: bess-postgres
    rules:
      # PostgreSQL unavailable
      - alert: BESSPostgresUnavailable
        expr: |
          sum(pg_up{job="postgres"}) == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "PostgreSQL is unavailable"
          description: "PostgreSQL database is down."
          runbook_url: "https://docs.example.com/runbooks/postgres-unavailable"

      # PostgreSQL connection pool exhausted
      - alert: BESSPostgresConnectionPoolExhausted
        expr: |
          pg_stat_activity_count / pg_settings_max_connections > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "PostgreSQL connection pool nearly exhausted"
          description: "PostgreSQL using {{ $value | humanizePercentage }} of max connections."

      # PostgreSQL high query latency
      - alert: BESSPostgresHighLatency
        expr: |
          histogram_quantile(0.99, rate(bess_postgres_query_duration_seconds_bucket[5m])) > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "PostgreSQL p99 query latency above 500ms"
          description: "PostgreSQL query p99 latency is {{ $value }}s."
```

### Health Probe Alerts

```yaml
groups:
  - name: bess-health
    rules:
      # API not ready
      - alert: BESSAPINotReady
        expr: |
          sum(bess_health_ready{status="ok"}) == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "BESS API not ready"
          description: "API readiness probe failing. Dependencies may be unhealthy."
          runbook_url: "https://docs.example.com/runbooks/api-not-ready"

      # Worker not healthy
      - alert: BESSWorkerNotHealthy
        expr: |
          kube_deployment_status_replicas_ready{deployment=~".*-worker"} == 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "No healthy worker replicas"
          description: "All worker replicas are unhealthy. Background jobs will not be processed."

      # Pod restart rate high
      - alert: BESSHighPodRestartRate
        expr: |
          rate(kube_pod_container_status_restarts_total{namespace="default", pod=~"pv-portal-.*"}[1h]) > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High pod restart rate"
          description: "Pod {{ $labels.pod }} is restarting frequently."
```

## Grafana Dashboard

Import `docs/observability/dashboards/ha-health.json` for HA infrastructure monitoring.

### Panels

1. **Redis Health**
   - Connection status
   - Operation latency histogram
   - Error rate

2. **S3/MinIO Health**
   - Storage availability
   - Operation latency
   - Error rate

3. **PostgreSQL Health**
   - Connection pool usage
   - Query latency
   - Active connections

4. **Fallback Status**
   - Rate limit backend (redis/memory)
   - Artifact store backend (s3/local)

## Integration

### Prometheus Configuration

```yaml
# prometheus.yml
rule_files:
  - /etc/prometheus/rules/bess-ha-alerts.yml

scrape_configs:
  - job_name: 'redis'
    static_configs:
      - targets: ['redis:9121']  # Redis exporter

  - job_name: 'minio'
    static_configs:
      - targets: ['minio:9000']
    metrics_path: /minio/v2/metrics/cluster

  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres:9187']  # postgres_exporter
```

### AlertManager Configuration

```yaml
# alertmanager.yml
route:
  receiver: 'slack-notifications'
  group_by: ['alertname', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - match:
        severity: critical
      receiver: 'pagerduty-critical'

receivers:
  - name: 'slack-notifications'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/...'
        channel: '#bess-alerts'

  - name: 'pagerduty-critical'
    pagerduty_configs:
      - service_key: '...'
```

## Runbooks

### Redis Unavailable

1. Check Redis pod status: `kubectl get pods -l app.kubernetes.io/component=redis`
2. Check Redis logs: `kubectl logs deploy/pv-portal-redis`
3. Verify Redis connection: `kubectl exec deploy/pv-portal-redis -- redis-cli ping`
4. If using external Redis, check network connectivity
5. Rate limiting will automatically fall back to memory mode

### S3 Unavailable

1. Check MinIO pod status: `kubectl get pods -l app.kubernetes.io/component=minio`
2. Check MinIO health: `kubectl exec deploy/pv-portal-minio -- curl -s http://localhost:9000/minio/health/live`
3. Verify credentials in secret: `kubectl get secret pv-portal-minio -o yaml`
4. If using external S3, check IAM permissions and network
5. Artifact operations will fail until S3 is restored

### API Not Ready

1. Check API pod status: `kubectl get pods -l app.kubernetes.io/component=api`
2. Check readiness endpoint: `curl http://api:8031/api/bess-dispatch/health/ready`
3. Review dependency checks in response
4. Fix underlying dependency issue
5. Pod will automatically become ready when dependencies recover
