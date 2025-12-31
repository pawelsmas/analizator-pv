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

## Validate-Pack Alerts (v1.7.0)

### Critical: Baseline Pack Failing

Fires when the baseline pack validation fails. This indicates that expected scenario
results are no longer matching, which could mean a regression in calculation logic.

```yaml
- alert: BESSBaselinePackFailing
  expr: bess_validation_last_pack_passed{pack="baseline"} == 0
  for: 0m
  labels:
    severity: critical
  annotations:
    summary: "Baseline pack validation is failing"
    description: "The baseline pack validation is failing. {{ $value }} scenarios are not matching expected results."
    runbook: "Run `make validate-pack PACK=baseline` locally to see diff details"
```

### Warning: Pack Validation Failures

Fires when any pack validation starts failing.

```yaml
- alert: BESSPackValidationFailing
  expr: increase(bess_validation_pack_failed_total[1h]) > 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Pack validation failures detected"
    description: "Pack {{ $labels.pack }} validation is failing"
```

### Warning: Scenario Errors

Fires when scenarios have errors (not mismatches, but actual errors like file not found).

```yaml
- alert: BESSScenarioErrors
  expr: increase(bess_validation_scenario_error_total[1h]) > 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Scenario validation errors"
    description: "Scenario {{ $labels.scenario }} in pack {{ $labels.pack }} has errors"
```

### Warning: High Pack Validation Duration

Fires when pack validation takes too long.

```yaml
- alert: BESSPackValidationSlow
  expr: histogram_quantile(0.99, rate(bess_validation_pack_duration_seconds_bucket[1h])) > 60
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: "Pack validation is slow"
    description: "99th percentile pack validation duration exceeds 60 seconds for pack {{ $labels.pack }}"
```

### Info: Nightly Baseline Health Summary

For Slack notifications, send a daily summary of baseline health.

```yaml
- alert: BESSNightlyBaselineHealthSummary
  expr: |
    bess_validation_last_scenarios_passed{pack="baseline"} /
    bess_validation_last_scenarios_total{pack="baseline"}
  labels:
    severity: info
  annotations:
    summary: "Nightly baseline health: {{ $value | humanizePercentage }} passing"
    description: |
      Baseline pack results:
      - Total: {{ with query "bess_validation_last_scenarios_total{pack='baseline'}" }}{{ . | first | value }}{{ end }}
      - Passed: {{ with query "bess_validation_last_scenarios_passed{pack='baseline'}" }}{{ . | first | value }}{{ end }}
      - Failed: {{ with query "bess_validation_last_scenarios_failed{pack='baseline'}" }}{{ . | first | value }}{{ end }}
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

## Debug Events Alerts (v1.8.0)

### Warning: Unserved Load Detected

Fires when any run has unserved load, indicating the BESS configuration is undersized.

```yaml
- alert: BESSUnservedLoadDetected
  expr: increase(bess_debug_events_unserved_load_total[15m]) > 0
  for: 1m
  labels:
    severity: warning
  annotations:
    summary: "Unserved load detected in sizing runs"
    description: "{{ $value }} runs had unserved load in the last 15 minutes. Consider reviewing BESS sizing constraints."
```

### Warning: High PV Curtailment

Fires when PV curtailment exceeds threshold.

```yaml
- alert: BESSHighPVCurtailment
  expr: histogram_quantile(0.99, rate(bess_debug_events_pv_curtail_mwh_bucket[1h])) > 1.0
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: "High PV curtailment detected"
    description: "99th percentile PV curtailment exceeds 1.0 MWh. Consider increasing BESS capacity or grid export limits."
```

### Info: Export/Import Limited Runs

Fires when grid constraints are frequently limiting energy flows.

```yaml
- alert: BESSGridLimited
  expr: |
    rate(bess_debug_events_export_limited_total[1h]) > 0.1
    or rate(bess_debug_events_import_limited_total[1h]) > 0.1
  for: 30m
  labels:
    severity: info
  annotations:
    summary: "Grid constraints limiting BESS operation"
    description: "Export or import limits are frequently activated. Review grid connection capacity."
```

## Repro Bundle Alerts (v1.8.0)

### Warning: High Repro Download Failure Rate

Fires when repro bundle downloads are frequently failing (run not found).

```yaml
- alert: BESSReproDownloadFailures
  expr: |
    sum(rate(bess_repro_run_downloads_total{status="not_found"}[15m])) /
    sum(rate(bess_repro_run_downloads_total[15m])) > 0.1
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "High repro bundle download failure rate"
    description: "More than 10% of repro.zip downloads are failing due to run not found. Check run retention policy."
```

## Runbook Links

When alerts fire, operators should:

1. **InvariantFailure**: Check logs for specific variant and failed check type
2. **ValidationFailure**: Run `python scripts/validate_scenarios.py --verbose` to see diff details
3. **StrictInvariantsViolation**: Consider disabling STRICT_INVARIANTS temporarily while investigating
4. **BaselinePackFailing**: Run `make validate-pack PACK=baseline` to see detailed diff output
5. **ScenarioErrors**: Check if scenario request files exist in `docs/scenarios/packs/` directory
6. **PackValidationSlow**: Consider reducing number of scenarios in pack or optimizing sizing engine
7. **UnservedLoadDetected**: Review BESS sizing constraints, possibly increase battery capacity
8. **HighPVCurtailment**: Consider increasing BESS capacity or grid export limits
9. **ReproDownloadFailures**: Check run store retention policy, may need to extend retention days
