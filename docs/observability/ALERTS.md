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

## Ledger Reconciliation Alerts (v1.9.0)

### Critical: Ledger Reconciliation Failure

Fires when money ledger reconciliation fails (net_savings != ledger delta).
This indicates a calculation inconsistency that should be investigated immediately.

```yaml
- alert: BESSLedgerReconciliationFailure
  expr: increase(bess_ledger_reconciliation_total{status="failed"}[5m]) > 0
  for: 0m
  labels:
    severity: critical
  annotations:
    summary: "Ledger reconciliation failed"
    description: "{{ $value }} sizing runs had ledger reconciliation failures in the last 5 minutes. net_savings_pln does not match delta_annual_pln.total_cost_pln."
    runbook: "Check logs for affected run_id, compare savings_breakdown vs money_ledger values"
```

### Warning: High Reconciliation Error

Fires when ledger reconciliation error magnitude is unexpectedly high.

```yaml
- alert: BESSLedgerReconciliationErrorHigh
  expr: histogram_quantile(0.99, rate(bess_ledger_reconciliation_error_pln_bucket[15m])) > 0.1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High ledger reconciliation error"
    description: "99th percentile reconciliation error exceeds 0.1 PLN. May indicate rounding drift or calculation inconsistencies."
```

### Info: Money Ledger Adoption Rate

Tracks adoption of include_money_ledger feature.

```yaml
- alert: BESSMoneyLedgerAdoption
  expr: |
    sum(rate(bess_ledger_requests_total{include_money_ledger="true"}[1d])) /
    sum(rate(bess_ledger_requests_total[1d])) * 100
  labels:
    severity: info
  annotations:
    summary: "Money ledger adoption: {{ $value | humanize }}%"
    description: "{{ $value | humanize }}% of sizing requests include money_ledger"
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

## Pricing Engine Alerts (v2.0.0)

### Info: High Override Usage

Fires when price override is used frequently.

```yaml
- alert: BESSHighPriceOverrideUsage
  expr: rate(bess_price_override_requests_total[1h]) > 10
  for: 30m
  labels:
    severity: info
  annotations:
    summary: "High price override usage"
    description: "More than 10 requests/hour are using price_timeseries_override"
```

### Warning: Unusual Import Price

Fires when average import price is unusually high or low.

```yaml
- alert: BESSUnusualImportPrice
  expr: |
    histogram_quantile(0.95, rate(bess_price_import_pln_mwh_bucket[15m])) > 2000
    or histogram_quantile(0.05, rate(bess_price_import_pln_mwh_bucket[15m])) < 100
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Unusual import price detected"
    description: "Import prices are outside normal range (100-2000 PLN/MWh)"
```

### Info: High Ledger Net Costs

Fires when net costs in ledger are unusually high.

```yaml
- alert: BESSHighLedgerNetCosts
  expr: histogram_quantile(0.99, rate(bess_ledger_net_cost_pln_bucket[15m])) > 10000
  for: 15m
  labels:
    severity: info
  annotations:
    summary: "High ledger net costs"
    description: "99th percentile net cost exceeds 10,000 PLN"
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
10. **LedgerReconciliationFailure**: Compare net_savings_pln vs money_ledger.delta_annual_pln.total_cost_pln for affected run
11. **LedgerReconciliationErrorHigh**: Review rounding policies in money_ledger_helper.py and savings_breakdown calculation
12. **HighPriceOverrideUsage**: Review if price_timeseries_override is being used as intended (testing/replay)
13. **UnusualImportPrice**: Verify price configuration, check for typos in import_price_pln_mwh
14. **DispatchInvariantViolation**: Check battery trace for SOC/power limit violations, review dispatch algorithm
15. **CycleLimitExceeded**: Review max_cycles_per_day setting, may need to reduce or adjust dispatch strategy
16. **HighDailyEFC**: Battery cycling rate is high, may reduce battery lifetime

## Dispatch Trace Alerts (v2.2.0)

### Critical: Dispatch Invariant Violation

Fires when dispatch invariants (SOC bounds, power limits, no-simultaneous) are violated.

```yaml
- alert: BESSDispatchInvariantViolation
  expr: increase(bess_dispatch_invariant_violations_total[5m]) > 0
  for: 0m
  labels:
    severity: critical
  annotations:
    summary: "Dispatch invariant violation detected"
    description: "{{ $labels.invariant_type }} invariant violated. This indicates a dispatch algorithm error."
    runbook: "Check battery_trace for affected run, verify SOC/power calculations"
```

### Warning: SOC Bounds Violation

Fires when SOC goes outside valid range.

```yaml
- alert: BESSSOCBoundsViolation
  expr: increase(bess_dispatch_invariant_failed_total{check_type="soc_bounds"}[15m]) > 0
  for: 1m
  labels:
    severity: warning
  annotations:
    summary: "SOC bounds check failed"
    description: "SOC exceeded valid range (0 to capacity). Check dispatch algorithm."
```

### Warning: Power Limits Violation

Fires when charge/discharge power exceeds rated power.

```yaml
- alert: BESSPowerLimitsViolation
  expr: increase(bess_dispatch_invariant_failed_total{check_type="power_limits"}[15m]) > 0
  for: 1m
  labels:
    severity: warning
  annotations:
    summary: "Power limits check failed"
    description: "Charge or discharge power exceeded rated power. Check dispatch algorithm."
```

### Warning: Simultaneous Charge/Discharge

Fires when battery is simultaneously charging and discharging.

```yaml
- alert: BESSSimultaneousChargeDischarge
  expr: increase(bess_dispatch_invariant_failed_total{check_type="no_simultaneous"}[15m]) > 0
  for: 1m
  labels:
    severity: warning
  annotations:
    summary: "Simultaneous charge/discharge detected"
    description: "Battery is charging and discharging at the same time. This should never happen."
```

## Cycle Accounting Alerts (v2.2.0)

### Warning: Cycle Limit Exceeded

Fires when cycle limit enforcement is active and days are exceeding the limit.

```yaml
- alert: BESSCycleLimitExceeded
  expr: increase(bess_cycle_limit_days_exceeded_total[1d]) > 0
  for: 0m
  labels:
    severity: warning
  annotations:
    summary: "Daily cycle limit exceeded"
    description: "{{ $value }} days exceeded max_cycles_per_day limit"
```

### Warning: High Daily EFC

Fires when daily cycling rate is high, which may reduce battery lifetime.

```yaml
- alert: BESSHighDailyEFC
  expr: bess_cycle_daily_max_efc > 2.0
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: "High daily cycling rate"
    description: "Max daily EFC is {{ $value }}, which exceeds 2.0 cycles/day threshold"
```

### Info: Cycle Limit Clamping Active

Fires when cycle limit enforcement is actively clamping discharge.

```yaml
- alert: BESSCycleLimitClampingActive
  expr: rate(bess_cycle_limit_clamp_events_total[1h]) > 10
  for: 30m
  labels:
    severity: info
  annotations:
    summary: "Cycle limit clamping is active"
    description: "More than 10 clamp events per hour. Battery discharge is being limited to meet cycle budget."
```

### Info: Battery Trace Requests

Tracks adoption of battery trace feature.

```yaml
- alert: BESSBatteryTraceAdoption
  expr: |
    sum(rate(bess_battery_trace_requests_total[1d])) /
    sum(rate(bess_http_requests_total{path="/sizing"}[1d])) * 100
  labels:
    severity: info
  annotations:
    summary: "Battery trace adoption: {{ $value | humanize }}%"
    description: "{{ $value | humanize }}% of sizing requests include battery_trace"
```

## Portfolio Alerts (v2.3.0)

### Warning: Portfolio Summary Errors

Fires when portfolio summary requests are failing.

```yaml
- alert: BESSPortfolioSummaryErrors
  expr: increase(bess_portfolio_summary_errors_total[15m]) > 5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Portfolio summary errors increasing"
    description: "More than 5 portfolio summary errors in last 15 minutes"
```

### Warning: Mixed Assumptions Detected

Fires when portfolio requests aggregate runs with different assumptions versions.

```yaml
- alert: BESSPortfolioMixedAssumptions
  expr: rate(bess_portfolio_mixed_assumptions_total[1h]) > 1
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Portfolio requests with mixed assumptions"
    description: "Portfolio summary requests are aggregating runs with different assumption versions. Results may not be comparable."
```

### Info: Large Portfolio Requests

Tracks when users are aggregating large numbers of runs.

```yaml
- alert: BESSLargePortfolioRequests
  expr: histogram_quantile(0.95, rate(bess_portfolio_items_per_request_bucket[1h])) > 20
  for: 30m
  labels:
    severity: info
  annotations:
    summary: "Large portfolio requests detected"
    description: "95th percentile portfolio request size is {{ $value | humanize }} items"
```

### Info: Portfolio Usage

Tracks adoption of portfolio feature.

```yaml
- alert: BESSPortfolioAdoption
  expr: sum(increase(bess_portfolio_summary_requests_total[1d])) > 10
  labels:
    severity: info
  annotations:
    summary: "Portfolio feature adoption"
    description: "{{ $value | humanize }} portfolio summary requests in last 24 hours"
```

---

## Report Generation Alerts (v2.4.0)

Alerting rules for report generation (PDF, XLSX, ZIP).

### Warning: Report Generation Failures

Alerts when report generation is failing frequently.

```yaml
- alert: BESSReportGenerationFailing
  expr: rate(bess_report_errors_total[5m]) > 0.1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Report generation failures detected"
    description: "Report generation errors rate {{ $value | humanize }}/s for format={{ $labels.format }}, error_type={{ $labels.error_type }}"
```

### Warning: Slow Report Generation

Alerts when report generation is taking too long.

```yaml
- alert: BESSSlowReportGeneration
  expr: histogram_quantile(0.95, rate(bess_report_generation_duration_seconds_bucket[10m])) > 10
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Slow report generation detected"
    description: "95th percentile report generation time is {{ $value | humanize }}s for format={{ $labels.format }}"
```

### Warning: Large Report Files

Alerts when generated reports are unusually large.

```yaml
- alert: BESSLargeReportFiles
  expr: histogram_quantile(0.95, rate(bess_report_size_bytes_bucket[1h])) > 5000000
  for: 30m
  labels:
    severity: warning
  annotations:
    summary: "Large report files detected"
    description: "95th percentile report size is {{ $value | humanize }}B for format={{ $labels.format }}"
```

### Warning: Portfolio Report Failures

Alerts when portfolio report generation is failing.

```yaml
- alert: BESSPortfolioReportFailing
  expr: rate(bess_portfolio_report_errors_total[5m]) > 0.05
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Portfolio report generation failures"
    description: "Portfolio report errors rate {{ $value | humanize }}/s for error_type={{ $labels.error_type }}"
```

### Info: Report Usage by Format

Tracks report generation by format for adoption monitoring.

```yaml
- alert: BESSReportUsage
  expr: sum by (format) (increase(bess_report_requests_total[1d])) > 10
  labels:
    severity: info
  annotations:
    summary: "Report usage by format"
    description: "{{ $value | humanize }} {{ $labels.format }} reports generated in last 24 hours"
```

### Info: Engineering Profile Adoption

Tracks adoption of engineering profile for reports.

```yaml
- alert: BESSEngineeringReportAdoption
  expr: sum(increase(bess_report_profile_requests_total{profile="engineering"}[1d])) > 5
  labels:
    severity: info
  annotations:
    summary: "Engineering profile adoption"
    description: "{{ $value | humanize }} engineering profile reports in last 24 hours"
```

### Info: Custom Branding Usage

Tracks adoption of custom branding fields.

```yaml
- alert: BESSReportBrandingAdoption
  expr: sum by (field) (increase(bess_report_branding_usage_total[1d])) > 5
  labels:
    severity: info
  annotations:
    summary: "Report branding field usage"
    description: "{{ $value | humanize }} reports with {{ $labels.field }} in last 24 hours"
```

## Performance Alerts (v2.5.0)

### Warning: Slow Requests

Fires when requests exceed the slow request threshold (default 2s).

```yaml
- alert: BESSSlowRequests
  expr: increase(bess_slow_requests_total[5m]) > 5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Slow requests detected"
    description: "{{ $value | humanize }} requests exceeded {{ $labels.endpoint }} threshold in last 5 minutes"
```

### Warning: High P95 Latency

Fires when P95 request latency exceeds threshold.

```yaml
- alert: BESSHighP95Latency
  expr: histogram_quantile(0.95, rate(bess_request_duration_seconds_bucket[5m])) > 5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High P95 latency detected"
    description: "P95 latency is {{ $value | humanizeDuration }}"
```

### Warning: High Request Size

Fires when requests approach the size limit.

```yaml
- alert: BESSHighRequestSize
  expr: histogram_quantile(0.99, rate(bess_request_size_bytes_bucket[15m])) > 2000000
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Large requests approaching limit"
    description: "P99 request size is {{ $value | humanize1024 }}B, limit is 2.5MB"
```

### Warning: Low Cache Hit Rate

Fires when report cache hit rate is low, indicating inefficient caching.

```yaml
- alert: BESSCacheHitRateLow
  expr: |
    sum(rate(bess_report_cache_hits_total[1h])) /
    (sum(rate(bess_report_cache_hits_total[1h])) + sum(rate(bess_report_cache_misses_total[1h]))) < 0.5
  for: 30m
  labels:
    severity: warning
  annotations:
    summary: "Report cache hit rate below 50%"
    description: "Cache hit rate is {{ $value | humanizePercentage }}. Consider increasing cache size or TTL."
```

### Warning: Limit Rejections

Fires when requests are being rejected due to limits.

```yaml
- alert: BESSLimitRejections
  expr: increase(bess_limit_rejections_total[15m]) > 5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Requests being rejected due to limits"
    description: "{{ $value | humanize }} requests rejected for {{ $labels.limit_type }} in last 15 minutes"
```

### Info: Compression Efficiency

Tracks compression savings.

```yaml
- alert: BESSCompressionSavings
  expr: increase(bess_compression_savings_bytes_total[1d]) > 100000000
  labels:
    severity: info
  annotations:
    summary: "Compression savings"
    description: "{{ $value | humanize1024 }}B saved by compression in last 24 hours"
```

### Info: Cache Size

Tracks cache utilization.

```yaml
- alert: BESSCacheNearCapacity
  expr: sum(bess_report_cache_size_entries) > 80
  for: 15m
  labels:
    severity: info
  annotations:
    summary: "Report cache near capacity"
    description: "{{ $value | humanize }} entries in cache (max 100)"
```

## Auth Alerts (v3.0.0)

### Warning: High Login Failure Rate

Fires when login failures exceed a threshold, indicating possible brute-force attack.

```yaml
- alert: BESSHighLoginFailureRate
  expr: |
    sum(rate(bess_auth_login_total{result="failure"}[15m])) /
    sum(rate(bess_auth_login_total[15m])) > 0.5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High login failure rate"
    description: "More than 50% of login attempts are failing in the last 15 minutes"
```

### Warning: Login Failures Spike

Fires when absolute number of login failures spikes.

```yaml
- alert: BESSLoginFailuresSpike
  expr: increase(bess_auth_login_total{result="failure"}[5m]) > 10
  for: 0m
  labels:
    severity: warning
  annotations:
    summary: "Login failures spike detected"
    description: "{{ $value | humanize }} failed login attempts in the last 5 minutes"
```

### Warning: API Key Validation Failures

Fires when API key validations fail repeatedly.

```yaml
- alert: BESSApiKeyValidationFailures
  expr: increase(bess_auth_api_key_validations_total{result="failure"}[15m]) > 20
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "API key validation failures"
    description: "{{ $value | humanize }} API key validation failures in the last 15 minutes"
```

### Info: Expired API Keys Used

Tracks usage of expired API keys (may indicate forgotten rotations).

```yaml
- alert: BESSExpiredApiKeysUsed
  expr: increase(bess_auth_api_key_validations_total{result="expired"}[1h]) > 0
  labels:
    severity: info
  annotations:
    summary: "Expired API keys being used"
    description: "{{ $value | humanize }} requests with expired API keys in the last hour"
```

### Critical: RBAC Denials

Fires when permission denials increase (may indicate misconfigured clients).

```yaml
- alert: BESSRbacDenials
  expr: increase(bess_rbac_checks_total{result="denied"}[15m]) > 10
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "RBAC permission denials"
    description: "{{ $value | humanize }} permission denials in the last 15 minutes"
```

### Info: Audit Log Volume

Tracks audit log write volume.

```yaml
- alert: BESSAuditLogHighVolume
  expr: increase(bess_audit_log_writes_total[1h]) > 1000
  labels:
    severity: info
  annotations:
    summary: "High audit log volume"
    description: "{{ $value | humanize }} audit entries in the last hour"
```
