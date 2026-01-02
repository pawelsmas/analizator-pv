# BESS Dispatch Service Level Objectives (SLO)

Version: v3.9.0

## Overview

This document defines the Service Level Objectives (SLOs) for the BESS Dispatch service.
SLOs provide measurable targets for service reliability and performance.

## SLO Definitions

### 1. Availability SLO

| Metric | Target | Window |
|--------|--------|--------|
| Service Availability | 99.5% | 30 days (rolling) |

**Definition**: Percentage of successful HTTP requests (non-5xx responses) out of total requests.

**SLI Formula**:
```promql
sum(rate(http_requests_total{status!~"5.."}[30d]))
/
sum(rate(http_requests_total[30d]))
```

**Error Budget**: 0.5% = ~3.6 hours downtime per 30 days

### 2. Latency SLO

| Metric | Target | Window |
|--------|--------|--------|
| Request Latency (p95) | < 2 seconds | 30 days (rolling) |

**Definition**: 95th percentile of request duration should be under 2 seconds.

**SLI Formula**:
```promql
histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[30d])) by (le))
```

**Target**: p95 latency < 2s for 99% of the time window

## Service Level Indicators (SLIs)

### HTTP Request Metrics

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `http_requests_total` | Counter | status, method, path | Total HTTP requests |
| `http_request_duration_seconds` | Histogram | method, path | Request duration |

### Availability SLI

```promql
# Availability ratio (1.0 = 100%)
bess:sli:availability:ratio =
  sum(rate(http_requests_total{status!~"5.."}[5m]))
  /
  sum(rate(http_requests_total[5m]))
```

### Latency SLI

```promql
# Latency p95 in seconds
bess:sli:latency:p95 =
  histogram_quantile(0.95,
    sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
  )

# Latency target compliance (1 = within target, 0 = exceeded)
bess:sli:latency:target_compliance =
  (bess:sli:latency:p95 < 2) or vector(0)
```

## Recording Rules

Recording rules pre-compute SLI metrics for efficient alerting and dashboards.

See: `monitoring/prometheus/slo_recording_rules.yml`

### Rule Groups

1. **bess_sli_availability** - 5m/1h/30d availability ratios
2. **bess_sli_latency** - p50/p95/p99 latency metrics
3. **bess_slo_compliance** - SLO target compliance flags
4. **bess_error_budget** - Error budget consumption metrics

## Error Budget Policy

### Budget Calculation

```
Error Budget = 1 - SLO Target
             = 1 - 0.995
             = 0.005 (0.5%)

Budget in minutes (30d) = 30 * 24 * 60 * 0.005
                        = 216 minutes
                        = 3.6 hours
```

### Budget Consumption Alerts

| Alert | Condition | Severity |
|-------|-----------|----------|
| ErrorBudgetBurn1h | >2% budget consumed in 1h | warning |
| ErrorBudgetBurn6h | >5% budget consumed in 6h | warning |
| ErrorBudgetBurn24h | >10% budget consumed in 24h | critical |
| ErrorBudgetExhausted | >100% budget consumed in 30d | critical |

### Multi-Window Burn Rate

We use multi-window, multi-burn-rate alerting as recommended by Google SRE:

| Window | Burn Rate | Budget Consumed | Alert After |
|--------|-----------|-----------------|-------------|
| 1h | 14.4x | 2% | 5 min |
| 6h | 6x | 5% | 30 min |
| 24h | 3x | 10% | 2h |
| 3d | 1x | 10% | 1d |

## Exclusions

The following are excluded from SLO calculations:

1. **Health checks**: `/health`, `/ready`, `/metrics` endpoints
2. **Scheduled maintenance**: Pre-announced maintenance windows
3. **External dependencies**: Failures caused by external services (when documented)
4. **Client errors**: 4xx responses (except 429 rate limiting)

## Incident Response

### SLO Breach Protocol

1. **Detection**: Alert fires when SLO is breached
2. **Acknowledgment**: On-call acknowledges within 15 minutes
3. **Investigation**: Root cause analysis begins
4. **Mitigation**: Temporary fix to restore service
5. **Resolution**: Permanent fix deployed
6. **Postmortem**: Document learnings within 48 hours

### Error Budget Actions

| Budget Remaining | Action |
|------------------|--------|
| >50% | Normal development velocity |
| 25-50% | Increased monitoring, cautious deployments |
| 10-25% | Freeze non-critical changes |
| <10% | All hands on reliability |
| Exhausted | Feature freeze until budget recovers |

## Dashboard

SLO metrics are visualized in the Grafana dashboard:
- **Dashboard ID**: `bess-slo-overview`
- **Panels**:
  - Current availability (30d rolling)
  - Latency percentiles (p50, p95, p99)
  - Error budget remaining
  - Error budget burn rate
  - SLO compliance history

## Validation

Recording rules are validated in CI using promtool:

```bash
make promtool-check
```

See: `scripts/monitoring/promtool_check.sh`

## Changelog

### v3.9.0
- Initial SLO definitions
- Availability SLO: 99.5% / 30d
- Latency SLO: p95 < 2s / 30d
- Recording rules for SLIs
- Error budget burn-rate alerting framework

## References

- [Google SRE Book - SLOs](https://sre.google/sre-book/service-level-objectives/)
- [Prometheus Recording Rules](https://prometheus.io/docs/prometheus/latest/configuration/recording_rules/)
- [Multi-Window Burn Rate Alerts](https://sre.google/workbook/alerting-on-slos/)
