# Helm Optional Dependencies (v3.5.0)

This document describes the optional dependencies that can be enabled in the PV Portal Helm chart.

## Overview

The Helm chart includes optional templates for common infrastructure components:

| Component | Purpose | Enabled Via |
|-----------|---------|-------------|
| Redis | Rate limiting backend (HA) | `redis.enabled=true` |
| MinIO | S3-compatible artifact storage | `minio.enabled=true` |
| PostgreSQL | Job store database (future) | `postgres.enabled=true` |

## Development Mode

For local development with all dependencies enabled:

```bash
# Using values-dev.yaml
helm install pv-portal deploy/helm/pv-portal -f deploy/helm/pv-portal/values-dev.yaml

# Or with Make
make helm-template-dev
```

## Production Mode

For production, use external managed services instead:

```bash
# External Redis, S3, PostgreSQL
helm install pv-portal deploy/helm/pv-portal \
  --set redis.enabled=false \
  --set redis.externalUrl="redis://my-redis.example.com:6379/0" \
  --set minio.enabled=false \
  --set s3.externalEndpoint="https://s3.amazonaws.com" \
  --set s3.bucket="my-prod-bucket" \
  --set s3.accessKey="${S3_ACCESS_KEY}" \
  --set s3.secretKey="${S3_SECRET_KEY}" \
  --set postgres.enabled=false \
  --set postgres.externalUrl="postgresql://user:pass@rds.example.com:5432/bess"
```

## Redis Configuration

Redis is used for distributed rate limiting when `RATE_LIMIT_BACKEND=redis`.

```yaml
redis:
  enabled: true
  image:
    repository: redis
    tag: "7-alpine"
  resources:
    limits:
      cpu: 100m
      memory: 128Mi
  persistence:
    enabled: true
    size: 1Gi
```

### External Redis

```yaml
redis:
  enabled: false
  externalUrl: "redis://my-redis-cluster.example.com:6379/0"
```

## MinIO Configuration

MinIO provides S3-compatible storage for job artifacts when `ARTIFACT_STORE_BACKEND=s3`.

```yaml
minio:
  enabled: true
  image:
    repository: minio/minio
    tag: "latest"
  accessKey: "minioadmin"  # Set via --set in production
  secretKey: "minioadmin"  # Set via --set in production
  bucket: "bess-artifacts"
  resources:
    limits:
      cpu: 500m
      memory: 512Mi
  persistence:
    enabled: true
    size: 10Gi
```

### External S3

```yaml
minio:
  enabled: false

s3:
  externalEndpoint: "https://s3.amazonaws.com"
  bucket: "my-prod-bucket"
  accessKey: ""  # Set via --set
  secretKey: ""  # Set via --set
  region: "us-east-1"
```

## PostgreSQL Configuration

PostgreSQL is available for future job store migration from SQLite.

```yaml
postgres:
  enabled: true
  image:
    repository: postgres
    tag: "16-alpine"
  database: "bess"
  username: "bess"
  password: ""  # Set via --set in production
  resources:
    limits:
      cpu: 500m
      memory: 512Mi
  persistence:
    enabled: true
    size: 10Gi
```

### External PostgreSQL

```yaml
postgres:
  enabled: false
  externalUrl: "postgresql://user:pass@rds.example.com:5432/bess"
```

## Environment Variables

The following environment variables are automatically configured when dependencies are enabled:

### API Pod

| Variable | Source |
|----------|--------|
| `REDIS_URL` | `redis.enabled` → internal, or `redis.externalUrl` |
| `REDIS_ENABLED` | `true` if Redis configured |
| `S3_ENDPOINT` | `minio.enabled` → internal, or `s3.externalEndpoint` |
| `S3_BUCKET` | From `minio.bucket` or `s3.bucket` |
| `S3_ACCESS_KEY` | From secret |
| `S3_SECRET_KEY` | From secret |
| `ARTIFACT_STORE_BACKEND` | `s3` if S3 configured |
| `RATE_LIMIT_BACKEND` | `redis` if Redis configured |

### Worker Pod

Same environment variables as API pod.

## Persistence

All components support optional persistent storage:

```yaml
# Example: Enable persistence for all components
redis:
  persistence:
    enabled: true
    size: 1Gi
    storageClass: "standard"

minio:
  persistence:
    enabled: true
    size: 10Gi
    storageClass: "standard"

postgres:
  persistence:
    enabled: true
    size: 10Gi
    storageClass: "standard"
```

**Warning**: Without persistence, data is lost when pods restart.

## Scaling Considerations

| Component | Scalable? | Notes |
|-----------|-----------|-------|
| Redis | No* | Use Redis Cluster or Sentinel for HA |
| MinIO | No* | Use distributed MinIO or external S3 for HA |
| PostgreSQL | No* | Use managed PostgreSQL for HA |

*These dev-mode deployments are single-replica. For production HA, use external managed services.

## Troubleshooting

### Check component health

```bash
# Redis
kubectl exec -it deploy/pv-portal-redis -- redis-cli ping

# MinIO
kubectl exec -it deploy/pv-portal-minio -- curl -s http://localhost:9000/minio/health/live

# PostgreSQL
kubectl exec -it deploy/pv-portal-postgres -- pg_isready -U bess
```

### View logs

```bash
kubectl logs deploy/pv-portal-redis
kubectl logs deploy/pv-portal-minio
kubectl logs deploy/pv-portal-postgres
```

### Check secrets

```bash
kubectl get secret pv-portal-minio -o yaml
kubectl get secret pv-portal-postgres -o yaml
```
