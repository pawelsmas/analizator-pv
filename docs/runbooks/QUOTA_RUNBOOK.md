# Quota System Runbook

Operational procedures for the BESS quota and billing system.

## Quick Reference

| Metric | Alert | Severity | Action |
|--------|-------|----------|--------|
| `bess_quota_exceeded_total` | BESSQuotaExceededSpike | critical | Review tenant usage |
| `bess_quota_check_total{result="denied"}` | BESSHighQuotaDenialRate | warning | Check plan limits |
| `bess_quota_usage_pct` | BESSTenantNearQuotaLimit | warning | Contact tenant |
| `bess_usage_query_duration_seconds` | BESSSlowUsageQueries | warning | Check DB indexes |

## Procedures

### 1. Investigate Quota Exceeded Events

**Symptoms**: BESSQuotaExceededSpike alert firing

**Investigation**:

```promql
# Find affected tenants
topk(10, increase(bess_quota_exceeded_total[1h]))

# Check specific quota type
bess_quota_exceeded_total{quota_name="jobs_per_day"}

# Find current usage
bess_quota_usage_current{quota_name="jobs_per_day"}
```

**API Commands**:

```bash
# Get tenant usage
curl -H "Authorization: Bearer $TOKEN" \
  "$API_BASE/usage?tenant_id=$TENANT_ID"

# Get project quotas
curl -H "Authorization: Bearer $TOKEN" \
  "$API_BASE/projects/$PROJECT_ID/quotas"
```

**Resolution**:

1. **Temporary spike**: Wait for midnight UTC reset
2. **Legitimate growth**: Upgrade plan or add override
3. **Abuse**: Contact customer, consider rate limiting

### 2. Add Project Override

**When**: Customer needs higher limit than their plan

**Procedure**:

```bash
# Check current settings
curl -H "Authorization: Bearer $TOKEN" \
  "$API_BASE/projects/$PROJECT_ID/quotas"

# Add override
curl -X PATCH \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"overrides": {"jobs_per_day": 200}}' \
  "$API_BASE/projects/$PROJECT_ID/quotas"

# Verify
curl -H "Authorization: Bearer $TOKEN" \
  "$API_BASE/projects/$PROJECT_ID/quotas"
```

**Validation**:
- Check `effective_limits` in response matches expected
- Monitor `bess_project_override_total` metric

### 3. Change Tenant Plan

**When**: Customer upgrades/downgrades subscription

**Procedure**:

```bash
# Check current plan
curl -H "Authorization: Bearer $TOKEN" \
  "$API_BASE/tenants/$TENANT_ID/settings"

# Update plan
curl -X PATCH \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan_id": "pro"}' \
  "$API_BASE/tenants/$TENANT_ID/settings"
```

**Post-change checks**:
1. Verify plan assignment in response
2. Clear any project overrides that are now unnecessary
3. Monitor `bess_plan_assignments_total` metric

### 4. Debug Slow Usage Queries

**Symptoms**: BESSSlowUsageQueries alert firing

**Investigation**:

```promql
# Check query durations by type
histogram_quantile(0.99, rate(bess_usage_query_duration_seconds_bucket[15m]))
```

**Database checks**:

```sql
-- Check table sizes
SELECT name, COUNT(*) FROM usage_daily GROUP BY name;

-- Check for missing indexes
EXPLAIN QUERY PLAN
SELECT * FROM usage_daily
WHERE tenant_id = 'x' AND date >= '2024-01-01';
```

**Resolution**:
1. Add indexes if missing
2. Archive old usage records
3. Optimize query patterns

### 5. Emergency: Disable Quota Enforcement

**When**: Critical system issue requiring bypass

**Procedure**:

```bash
# Set environment variable
export QUOTA_ENFORCEMENT_DISABLED=true

# Restart service
docker-compose restart bess-dispatch
```

**Post-resolution**:
1. Remove environment variable
2. Restart service
3. Monitor `bess_quota_enforcement_total` to confirm re-enabled
4. File post-incident review

### 6. Quota Reset Issues

**Symptoms**: Usage not resetting at midnight UTC

**Investigation**:

```promql
# Check reset timing
bess_quota_reset_seconds_remaining
```

**Database check**:

```sql
-- Check today's records
SELECT * FROM usage_daily WHERE date = date('now');

-- Check yesterday's records (should not be counted)
SELECT * FROM usage_daily WHERE date = date('now', '-1 day');
```

**Resolution**:
1. Verify server timezone is UTC
2. Check `get_today_date()` function
3. Manual reset if needed:
   ```bash
   python -c "from quota_store import QuotaStore; s=QuotaStore(); s.reset_daily_usage()"
   ```

## Monitoring Dashboard

Recommended Grafana panels:

1. **Quota Check Rate**: `rate(bess_quota_check_total[5m])`
2. **Denial Rate**: `rate(bess_quota_check_total{result="denied"}[5m])`
3. **Exceeded by Plan**: `sum by(plan_id)(increase(bess_quota_exceeded_total[1h]))`
4. **Usage % Heatmap**: `bess_quota_usage_pct`
5. **Seconds to Reset**: `bess_quota_reset_seconds_remaining`
6. **Plan Distribution**: `bess_plan_usage_by_tier`

## Escalation

| Level | Contact | When |
|-------|---------|------|
| L1 | On-call engineer | Any quota alert |
| L2 | Backend team | Persistent issues, DB problems |
| L3 | Product owner | Plan limit policy decisions |
| L4 | CTO | Emergency bypass approval |

## Related Documentation

- [QUOTAS.md](../QUOTAS.md) - System overview
- [ALERTS.md](../observability/ALERTS.md) - Alert definitions
- [quota_metrics.py](../../services/bess-dispatch/observability/quota_metrics.py) - Metric definitions
