# Alerting Rules for BESS Dispatch Service

This document describes recommended alerting rules for monitoring the BESS Dispatch service correctness and reliability.

## Invariant Alerts (v1.6.0)

### Critical: Any Invariant Failure

Fires when any invariant check fails, indicating a potential calculation error.

```yaml
# Prometheus Alert Rule
- alert: BESSInvariantFailure
  expr: increase(bess_invariant_any_failed_total[5m]) > 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "BESS invariant check failed"
    description: "One or more invariant checks failed in the last 5 minutes. This indicates a potential calculation error."
```

### Warning: High Energy Balance Error

Fires when energy balance error exceeds acceptable threshold.

```yaml
- alert: BESSEnergyBalanceError
  expr: histogram_quantile(0.99, rate(bess_invariant_energy_balance_error_mwh_bucket[15m])) > 0.001
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High energy balance error detected"
    description: "99th percentile energy balance error exceeds 0.001 MWh"
```

### Critical: STRICT_INVARIANTS Violation

Fires when STRICT_INVARIANTS mode triggers an exception.

```yaml
- alert: BESSStrictInvariantsViolation
  expr: increase(bess_strict_invariants_violations_total[5m]) > 0
  for: 0m
  labels:
    severity: critical
  annotations:
    summary: "STRICT_INVARIANTS mode violation"
    description: "InvariantViolationError was raised, requests are being rejected"
```

## Validation Alerts

### Warning: Validation Failures

Fires when scenario validations start failing.

```yaml
- alert: BESSValidationFailures
  expr: increase(bess_validation_failed_total[15m]) > 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Scenario validation failures detected"
    description: "{{ $labels.scenario_id }} validation is failing"
```

### Critical: All Validations Failing

Fires when validation success rate drops significantly.

```yaml
- alert: BESSValidationSuccessRateLow
  expr: |
    sum(rate(bess_validation_passed_total[1h])) /
    sum(rate(bess_validation_requests_total[1h])) < 0.9
  for: 15m
  labels:
    severity: critical
  annotations:
    summary: "Validation success rate below 90%"
    description: "More than 10% of validations are failing"
```

## Service Health Alerts

### Critical: Service Down

```yaml
- alert: BESSServiceDown
  expr: up{job="bess-dispatch"} == 0
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "BESS Dispatch service is down"
    description: "The bess-dispatch service has been down for more than 2 minutes"
```

### Warning: High Error Rate

```yaml
- alert: BESSHighErrorRate
  expr: |
    sum(rate(bess_http_requests_total{status=~"5.."}[5m])) /
    sum(rate(bess_http_requests_total[5m])) > 0.01
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High HTTP 5xx error rate"
    description: "More than 1% of requests are returning 5xx errors"
```

### Warning: High Latency

```yaml
- alert: BESSHighLatency
  expr: histogram_quantile(0.99, rate(bess_http_request_duration_seconds_bucket{path="/sizing"}[5m])) > 10
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High sizing endpoint latency"
    description: "99th percentile latency for /sizing exceeds 10 seconds"
```

## Grafana Dashboard Panels

Recommended dashboard panels for correctness monitoring:

1. **Invariant Pass Rate** - Gauge showing percentage of invariant checks passing
2. **Invariant Failures by Type** - Bar chart showing failures by check type
3. **Energy Balance Error Distribution** - Histogram of error magnitudes
4. **Validation Success Rate** - Time series of validation pass/fail ratio
5. **Field Mismatch Heatmap** - Heatmap of which KPI fields are failing most

## Slack/PagerDuty Integration

For critical alerts, configure notification channels:

```yaml
receivers:
  - name: 'bess-critical'
    slack_configs:
      - channel: '#bess-alerts'
        send_resolved: true
    pagerduty_configs:
      - service_key: '<your-pagerduty-key>'

route:
  routes:
    - match:
        severity: critical
      receiver: 'bess-critical'
```

## Runbook Links

When alerts fire, operators should:

1. **InvariantFailure**: Check logs for specific variant and failed check type
2. **ValidationFailure**: Run `python scripts/validate_scenarios.py --verbose` to see diff details
3. **StrictInvariantsViolation**: Consider disabling STRICT_INVARIANTS temporarily while investigating
