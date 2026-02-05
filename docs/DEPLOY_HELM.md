# Helm Deployment Guide

This guide covers deploying PV Portal using Helm charts.

## Prerequisites

- Kubernetes cluster (v1.24+)
- Helm 3.x (or Docker for local development)
- Access to container registry with PV Portal images

## Quick Start

### Using Docker (No Local Helm Required)

The Makefile provides Docker-based Helm commands that work on any platform:

```bash
# Lint the chart
make helm-lint

# Render templates to stdout
make helm-template

# Render with dev settings (Redis enabled)
make helm-template-dev

# Package chart
make helm-package
```

### Using Helm CLI

If you have Helm installed locally:

```bash
# Lint
helm lint deploy/helm/pv-portal

# Template
helm template pv-portal deploy/helm/pv-portal

# Install (dry-run)
helm install pv-portal deploy/helm/pv-portal --dry-run

# Install
helm install pv-portal deploy/helm/pv-portal \
  --namespace pv-portal \
  --create-namespace \
  --set database.url=postgresql://... \
  --set auth.jwtSecret=$(openssl rand -base64 32)
```

## Configuration

### Required Values

| Value | Description | Example |
|-------|-------------|---------|
| `database.url` | PostgreSQL connection string | `postgresql://user:pass@host:5432/db` |
| `auth.jwtSecret` | JWT signing secret (32+ chars) | `openssl rand -base64 32` |

### Optional Values

| Value | Default | Description |
|-------|---------|-------------|
| `api.replicaCount` | 1 | API pod replicas |
| `worker.enabled` | true | Enable worker deployment |
| `worker.replicaCount` | 1 | Worker pod replicas |
| `redis.enabled` | false | Enable Redis for HA rate limiting |
| `artifactStore.backend` | local | Artifact storage (local/s3) |
| `ingress.enabled` | false | Enable Ingress |

### Example: Production Values

```yaml
# values-prod.yaml
api:
  replicaCount: 3
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 2000m
      memory: 2Gi

worker:
  replicaCount: 2
  resources:
    requests:
      cpu: 250m
      memory: 256Mi

redis:
  enabled: true
  url: redis://redis-master:6379/0

artifactStore:
  backend: s3
  s3:
    bucket: pvportal-artifacts
    region: eu-central-1

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: pvportal.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: pvportal-tls
      hosts:
        - pvportal.example.com
```

Install with production values:

```bash
helm install pv-portal deploy/helm/pv-portal \
  -f values-prod.yaml \
  --namespace pv-portal \
  --create-namespace
```

## Health Probes

The chart configures Kubernetes probes using:

- **Liveness**: `GET /api/bess-dispatch/health/live`
  - Always returns 200 if process is alive

- **Readiness**: `GET /api/bess-dispatch/health/ready`
  - Returns 200 only when dependencies (DB, Redis, S3) are healthy

## Scaling

```bash
# Scale API
kubectl scale deployment pv-portal-api --replicas=5 -n pv-portal

# Scale workers
kubectl scale deployment pv-portal-worker --replicas=3 -n pv-portal
```

## Upgrading

```bash
helm upgrade pv-portal deploy/helm/pv-portal \
  -f values-prod.yaml \
  --namespace pv-portal
```

## Uninstalling

```bash
helm uninstall pv-portal --namespace pv-portal
```

## Troubleshooting

### Check pod status

```bash
kubectl get pods -n pv-portal
kubectl describe pod <pod-name> -n pv-portal
```

### Check logs

```bash
kubectl logs -f deployment/pv-portal-api -n pv-portal
kubectl logs -f deployment/pv-portal-worker -n pv-portal
```

### Check readiness

```bash
kubectl exec -it deployment/pv-portal-api -n pv-portal -- \
  curl -s localhost:8031/api/bess-dispatch/health/ready
```

## Chart Files

```
deploy/helm/pv-portal/
├── Chart.yaml              # Chart metadata
├── values.yaml             # Default configuration
└── templates/
    ├── _helpers.tpl        # Template helpers
    ├── configmap.yaml      # Non-sensitive configuration
    ├── secret.yaml         # Sensitive configuration
    ├── deployment-api.yaml # API deployment
    ├── deployment-worker.yaml # Worker deployment
    ├── service-api.yaml    # API service
    └── ingress.yaml        # Ingress (optional)
```
