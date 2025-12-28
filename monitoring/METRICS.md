# Metrics Documentation

This document describes Prometheus metrics exposed by PV Optimizer services.

## bess-dispatch Service Metrics

### HTTP Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `http_requests_total` | Counter | service, endpoint, method, status | Total HTTP requests |
| `http_request_duration_seconds` | Histogram | service, endpoint, method | HTTP request duration |

### Domain Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `bess_sizing_requests_total` | Counter | mode, arbitrage_enabled | Total sizing requests |
| `bess_sizing_duration_seconds` | Histogram | mode | Sizing computation duration |
| `bess_dispatch_requests_total` | Counter | mode | Total dispatch requests |

### Process Metrics (default Python)

| Metric | Type | Description |
|--------|------|-------------|
| `process_resident_memory_bytes` | Gauge | RSS memory in bytes |
| `process_cpu_seconds_total` | Counter | Total CPU time |
| `python_gc_*` | Counter | Garbage collection stats |

## Label Cardinality Rules

**IMPORTANT**: To prevent Prometheus from exploding in memory, follow these rules:

### DO use as labels:
- `endpoint`: Route template path (e.g., `/sizing`, `/dispatch`, `/health`)
- `method`: HTTP method (`GET`, `POST`, etc.)
- `status`: HTTP status code as string (`200`, `404`, `500`)
- `service`: Service name (`bess-dispatch`)
- `mode`: Dispatch mode (limited enum: `pv_surplus`, `stacked`, `peak_shaving`, `load_only`)

### DO NOT use as labels:
- `assumptions_version` - changes with each assumptions.yaml update
- `schema_version` - can change frequently
- `recommended_variant` - too many possible values
- Full URL paths with query parameters
- Request/response body content
- User identifiers or session IDs

These high-cardinality values should go in **structured logs only**, not Prometheus labels.

## Alert Thresholds

| Alert | Condition | Severity | Duration |
|-------|-----------|----------|----------|
| BessDispatchTargetDown | `up == 0` | critical | 2m |
| BessSizingHighLatencyP95 | `p95 > 2s` | warning | 10m |
| BessSizingNoTraffic | `rate == 0` | info | 30m |
| BessHttp5xxErrorRateHigh | `5xx rate > 1%` | critical | 5m |

## Histogram Buckets

### `http_request_duration_seconds`
```
0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0
```

### `bess_sizing_duration_seconds`
```
0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0
```

## Querying Examples

### Error rate (5xx)
```promql
sum(rate(http_requests_total{service="bess-dispatch",status=~"5.."}[5m]))
/
sum(rate(http_requests_total{service="bess-dispatch"}[5m]))
```

### P95 latency
```promql
histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service="bess-dispatch"}[5m])) by (le))
```

### Requests per second by endpoint
```promql
sum(rate(http_requests_total{service="bess-dispatch"}[5m])) by (endpoint)
```
