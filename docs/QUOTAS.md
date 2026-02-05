# Quotas & Usage System (v4.0.0)

This document describes the quota and usage tracking system for the BESS Dispatch service.

## Overview

The quota system provides:
- **Plan-based limits**: Different subscription plans (free, pro, enterprise) with different resource limits
- **Per-project overrides**: Admins can override plan limits for specific projects
- **Usage tracking**: Real-time metering of resource consumption
- **Enforcement**: Requests exceeding quotas are rejected with 429 status

## Plans

### Available Plans

| Plan | jobs_per_day | reports_per_day | shares_total | storage_mb | projects_total |
|------|-------------|-----------------|--------------|------------|----------------|
| free | 10 | 5 | 3 | 100 | 1 |
| pro | 100 | 50 | 20 | 1000 | 10 |
| enterprise | 0 (unlimited) | 0 (unlimited) | 0 (unlimited) | 0 (unlimited) | 0 (unlimited) |

### Limit = 0 Means Unlimited

When a limit is set to 0, the quota is unlimited. This applies both to plan limits and project overrides.

## API Endpoints

### Plans

```
GET /api/bess-dispatch/plans
```
List all available plans.

```
GET /api/bess-dispatch/plans/{plan_id}
```
Get details of a specific plan.

### Tenant Settings

```
GET /api/bess-dispatch/tenants/{tenant_id}/settings
```
Get tenant billing settings including plan assignment.

```
PATCH /api/bess-dispatch/tenants/{tenant_id}/settings
```
Update tenant plan assignment. Requires admin role.

### Project Quotas

```
GET /api/bess-dispatch/projects/{project_id}/quotas
```
Get project quotas including overrides and effective limits.

```
PATCH /api/bess-dispatch/projects/{project_id}/quotas
```
Set project quota overrides. Requires admin role.

### Usage

```
GET /api/bess-dispatch/usage
```
Get tenant usage summary.

```
GET /api/bess-dispatch/usage/daily?days=30
```
Get daily usage records.

```
GET /api/bess-dispatch/projects/{project_id}/usage
```
Get project-specific usage.

```
GET /api/bess-dispatch/usage/export/csv
```
Export usage data as CSV.

## Quota Enforcement

### 429 Response

When a quota is exceeded, the API returns HTTP 429 with this structure:

```json
{
  "detail": {
    "code": "QUOTA_EXCEEDED",
    "message": "Quota exceeded for jobs_per_day",
    "quota_name": "jobs_per_day",
    "limit": 10,
    "used": 10,
    "retry_after_seconds": 43200
  }
}
```

The response includes a `Retry-After` header with seconds until quota reset.

### Quota Reset

All daily quotas reset at midnight UTC. The response includes `reset_at` timestamp.

## Project Overrides

Overrides take precedence over plan limits:

```json
{
  "overrides": {
    "jobs_per_day": 200  // Override the 10 from free plan
  }
}
```

Setting an override to `null` or omitting it uses the plan default.

## Usage Tracking

Usage is tracked per-tenant and per-project:

- `jobs_per_day`: Sizing requests
- `reports_per_day`: Report generations
- `shares_total`: Share link creations
- `storage_mb`: Storage consumption (runs + reports)
- `projects_total`: Project count

## UI Components

### Billing Dashboard (`billing.html`)

- Quota cards showing usage vs limits
- Progress bars with warning colors (>70%: yellow, >90%: red)
- Usage history table
- CSV export button

### Project Quotas Editor (`project-quotas.html`)

- Project selector dropdown
- Override inputs for each quota
- Plan limit comparison display
- Current usage grid

## Prometheus Metrics

```
bess_quota_check_total{quota_name, result}
bess_quota_exceeded_total{quota_name, plan_id}
bess_quota_usage_current{tenant_id, project_id, quota_name}
bess_quota_usage_pct{tenant_id, project_id, quota_name}
bess_usage_api_requests_total{endpoint, result}
```

## Migration

### Database Tables

The following tables are added by the migration:

- `plans`: Plan definitions with limits
- `tenant_settings`: Tenant-to-plan assignments
- `project_quotas`: Project override storage
- `usage_daily`: Daily usage records

### Migration Steps

1. Run database migration:
   ```bash
   python -m services.bess-dispatch.migrations.v4_0_0_quotas
   ```

2. Seed default plans:
   ```bash
   python -m services.bess-dispatch.scripts.seed_plans
   ```

3. Set tenant plans:
   ```bash
   curl -X PATCH /api/bess-dispatch/tenants/{tenant_id}/settings \
     -d '{"plan_id": "pro"}'
   ```

## Runbook

### Quota Exceeded Alert

When `BESSQuotaExceededSpike` fires:

1. Check which tenant/project is hitting limits:
   ```
   bess_quota_exceeded_total{quota_name="jobs_per_day"}
   ```

2. Review if limit increase is needed:
   - Temporary spike: Wait for reset
   - Consistent overage: Upgrade plan or add override

3. Add project override if appropriate:
   ```bash
   curl -X PATCH /api/bess-dispatch/projects/{project_id}/quotas \
     -d '{"overrides": {"jobs_per_day": 200}}'
   ```

### High Denial Rate

When `BESSHighQuotaDenialRate` fires:

1. Identify affected quota type from metric labels
2. Check plan distribution: `bess_plan_usage_by_tier`
3. Consider:
   - Plan limits too restrictive
   - Need to encourage upgrades
   - Specific projects need overrides

### Tenant Near Limit

When `BESSTenantNearQuotaLimit` fires:

1. Contact tenant proactively
2. Offer plan upgrade or temporary override
3. Review usage patterns
