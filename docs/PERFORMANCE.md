# Performance & Scale Hardening (v2.5.0)

This document describes the performance and scalability features introduced in v2.5.0.

## Overview

v2.5.0 focuses on infrastructure hardening without changing calculation results. All PRs are
additive and backward compatible.

## Request Limits

### Configuration

| Parameter | ENV Variable | Default | Description |
|-----------|--------------|---------|-------------|
| Max Request Size | `MAX_REQUEST_BYTES` | 2,500,000 (2.5MB) | Maximum request body size |
| Max Steps | `MAX_STEPS` | 35,040 | Maximum timeseries length (1 year @ 15min) |
| Max Trace Steps | `MAX_TRACE_STEPS` | 10,000 | Maximum full timeseries output |
| Max Variants | `MAX_VARIANTS` | 50 | Maximum variants to compute |
| Max Durations | `MAX_DURATIONS` | 10 | Maximum duration variants |

### Error Responses

When limits are exceeded, the API returns structured error responses:

```json
{
  "error_code": "STEPS_LIMIT_EXCEEDED",
  "detail": "Number of steps (50000) exceeds maximum allowed (35040)",
  "max_steps": 35040,
  "steps": 50000
}
```

Error codes:
- `REQUEST_TOO_LARGE` (413) - Request body exceeds MAX_REQUEST_BYTES
- `STEPS_LIMIT_EXCEEDED` (422) - Timeseries length exceeds MAX_STEPS
- `TIMESERIES_TOO_LARGE` (422) - Full mode output exceeds MAX_TRACE_STEPS

### Checking Limits

```bash
GET /api/bess-dispatch/limits
```

Returns current limit configuration.

## Timeseries Throttling

### Modes

Timeseries output can be controlled with mode parameters:

| Mode | Description |
|------|-------------|
| `none` | Do not include timeseries |
| `preview` | Include first N rows only |
| `full` | Include all rows (subject to MAX_TRACE_STEPS) |

### Request Parameters

```json
{
  "battery_trace_mode": "preview",
  "ledger_timeseries_mode": "none",
  "price_timeseries_mode": "full",
  "timeseries_preview_rows": 48
}
```

### Backward Compatibility

Existing boolean flags (`include_battery_trace`, etc.) continue to work:
- `include_X=true` with no mode → `mode=full` (original behavior)
- `include_X=false` with no mode → `mode=none`
- Mode parameter takes precedence when specified

### Preview Rows

| Parameter | Default | Min | Max |
|-----------|---------|-----|-----|
| `timeseries_preview_rows` | 48 | 12 | 240 |

### Response Metadata

When timeseries throttling is active, responses include metadata:

```json
{
  "timeseries_info": {
    "battery_trace": {
      "mode": "preview",
      "included_steps": 48,
      "total_steps": 8760,
      "truncated": true
    }
  }
}
```

## Report Caching

### Configuration

| Parameter | ENV Variable | Default | Description |
|-----------|--------------|---------|-------------|
| Max Entries | `REPORT_CACHE_MAX_ENTRIES` | 100 | Max entries per format |
| TTL | `REPORT_CACHE_TTL_SECONDS` | 3600 | Cache TTL (1 hour) |
| Enabled | `REPORT_CACHE_ENABLED` | true | Enable/disable cache |

### Cache Headers

Responses include `X-Cache` header:
- `HIT` - Served from cache
- `MISS` - Generated fresh and cached
- `DISABLED` - Caching disabled

### Cache Key

Cache key is computed from:
- run_id
- profile (client/engineering)
- branding options (client_name, site_name, etc.)
- notes
- max_table_rows

Different options = different cache entries.

## GZip Compression

### Configuration

Responses are automatically compressed when:
- Client sends `Accept-Encoding: gzip`
- Response exceeds 1KB threshold

### Headers

Compressed responses include:
- `Content-Encoding: gzip`
- `Vary: Accept-Encoding`

## Benchmarking

### Running Benchmarks

```bash
python scripts/bench_api.py --base-url http://localhost:8031 --iterations 10
```

Options:
- `--base-url URL` - API base URL
- `--iterations N` - Iterations per test
- `--output FILE` - Output JSON file
- `--quiet` - Suppress progress

### Output

```json
{
  "timestamp": "2025-01-01T00:00:00Z",
  "base_url": "http://localhost:8031",
  "results": [
    {
      "endpoint": "/api/bess-dispatch/sizing",
      "latency_ms": {"p50": 150, "p95": 250, "p99": 400},
      "throughput": {"requests_per_second": 6.5}
    }
  ]
}
```

### Metrics

- **p50/p95/p99 latency** - Response time percentiles
- **requests_per_second** - Throughput
- **response_size_bytes** - Response size

## Performance Observability

### Prometheus Metrics

Request/response metrics:
- `bess_request_size_bytes` - Request body size histogram
- `bess_response_size_bytes` - Response body size histogram
- `bess_slow_requests_total` - Requests exceeding threshold

Cache metrics:
- `bess_report_cache_hits_total` - Cache hits by format
- `bess_report_cache_misses_total` - Cache misses by format

### Alerts (docs/observability/ALERTS.md)

Recommended alerts:
- `BESSSlowRequests` - P95 latency > 2s
- `BESSHighRequestSize` - Requests approaching limits
- `BESSCacheHitRatelow` - Cache efficiency below threshold

## Best Practices

### Large Data Sets

For datasets with many steps:

1. Use `preview` mode for timeseries output
2. Request specific fields only
3. Use batch endpoints for multiple runs

### Report Downloads

1. Cache reports on client side using `X-Cache` header
2. Use same parameters to benefit from server cache
3. Consider ZIP format for all-in-one downloads

### Monitoring

1. Watch P95 latency trends
2. Monitor request size distribution
3. Track cache hit rates
