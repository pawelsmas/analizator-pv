# Migration Guide: v4.2.x → v4.3.0

This guide covers the migration to v4.3.0 which introduces Compliance, Retention, and Legal Hold features.

## Breaking Changes

**None.** All changes in v4.3.0 are additive. Existing APIs and functionality remain unchanged.

## New Features

### 1. Retention Policies

Retention policies define how long data is kept before being eligible for purge.

**Default Categories:**
- `runs`: Sizing calculation runs (default: 365 days)
- `jobs`: Background job records (default: 90 days)
- `reports`: Generated reports (default: 365 days)
- `audit_logs`: Audit log entries (default: 730 days / 2 years)
- `exports`: Compliance export bundles (default: 30 days)

**Configuration:**
```json
{
  "runs_days": 365,
  "jobs_days": 90,
  "reports_days": 365,
  "audit_logs_days": 730,
  "exports_days": 30,
  "enabled": true
}
```

**Special Values:**
- `0`: Keep data indefinitely
- `-1`: Inherit from parent (project inherits from tenant)

### 2. Legal Holds

Legal holds prevent data from being purged, even if past retention period.

**Use Cases:**
- Litigation hold requirements
- Regulatory audits
- Investigation preservation

**Resource Types:**
- `project`: Hold all data in a project
- `run`: Hold specific calculation run
- `job`: Hold specific background job
- `all`: Hold all tenant data

### 3. Compliance Exports

Generate downloadable ZIP bundles containing compliance data with:
- Manifest with SHA256 checksums
- Metadata with export parameters
- Retention policies and legal holds
- Audit logs (redacted by default)
- Run/job/report summaries

### 4. Purge Engine

Automated data cleanup based on retention policies:
- Dry-run mode for preview
- Execute mode with safety limits
- Legal hold enforcement
- Per-category processing
- Audit trail

## Database Migration

v4.3.0 adds 4 new tables to the SQLite database:

```sql
-- Automatically created on first startup
CREATE TABLE retention_policies (...)
CREATE TABLE legal_holds (...)
CREATE TABLE purge_runs (...)
CREATE TABLE compliance_exports (...)
```

**Migration is automatic.** Tables are created if they don't exist when the service starts.

## Kubernetes Deployment

### New Resources

1. **CronJob: retention-purge**
   - Runs daily at 2:00 AM UTC
   - Configurable via ConfigMap

2. **PVC: compliance-data-pvc**
   - 10Gi storage for compliance database
   - Adjust size based on data volume

3. **RBAC: retention-purge ServiceAccount**
   - Minimal permissions for job execution

### Configuration

```yaml
# retention-config ConfigMap
data:
  log_level: "INFO"
  max_deletions_per_run: "10000"
  dry_run_mode: "false"  # Set to "true" for initial testing
  notify_on_completion: "true"
  enabled_categories: "runs,jobs,reports,audit_logs,exports"
```

### Deployment Steps

1. Apply new Kubernetes resources:
   ```bash
   kubectl apply -f k8s/compliance-pvc.yaml
   kubectl apply -f k8s/retention-cronjob.yaml
   ```

2. Verify resources:
   ```bash
   kubectl get cronjob retention-purge -n pv-optimizer
   kubectl get pvc compliance-data-pvc -n pv-optimizer
   ```

3. Test with dry-run:
   ```bash
   kubectl create job --from=cronjob/retention-purge retention-test -n pv-optimizer
   kubectl logs -f job/retention-test -n pv-optimizer
   ```

## API Endpoints

### Retention Policies

| Method | Path | Description |
|--------|------|-------------|
| GET | `/compliance/retention` | Get tenant default policy |
| PUT | `/compliance/retention` | Update tenant default policy |
| GET | `/compliance/retention/projects/{id}` | Get project policy |
| PUT | `/compliance/retention/projects/{id}` | Update project policy |
| DELETE | `/compliance/retention/projects/{id}` | Remove project override |

### Legal Holds

| Method | Path | Description |
|--------|------|-------------|
| GET | `/compliance/holds` | List legal holds |
| POST | `/compliance/holds` | Create legal hold |
| DELETE | `/compliance/holds/{id}` | Release legal hold |
| GET | `/compliance/holds/summary` | Get hold statistics |

### Purge

| Method | Path | Description |
|--------|------|-------------|
| POST | `/compliance/purge/dry-run` | Preview what would be deleted |
| POST | `/compliance/purge/execute` | Execute purge |
| GET | `/compliance/purge/history` | List past purge runs |
| GET | `/compliance/purge/{id}` | Get purge run details |

### Exports

| Method | Path | Description |
|--------|------|-------------|
| GET | `/compliance/exports` | List exports |
| POST | `/compliance/exports` | Start export job |
| GET | `/compliance/exports/{id}` | Get export status |
| GET | `/compliance/exports/{id}/download` | Download bundle |
| DELETE | `/compliance/exports/{id}` | Delete bundle |

## Authorization

All compliance endpoints require **admin** role:

| Role | Access |
|------|--------|
| admin | Full access to all compliance features |
| editor | No access (403 Forbidden) |
| viewer | No access (403 Forbidden) |

## Monitoring

### Prometheus Metrics

New metrics available:
- `bess_retention_policy_operations_total`
- `bess_legal_hold_operations_total`
- `bess_legal_hold_active`
- `bess_purge_runs_total`
- `bess_purge_deleted_total`
- `bess_purge_skipped_total`
- `bess_compliance_export_operations_total`

### Alerting Rules

Configure recommended alerts from `docs/observability/ALERTS.md`:
- `BESSRetentionPurgeFailure` (critical)
- `BESSPurgeHittingLimits` (warning)
- `BESSComplianceExportFailure` (warning)
- `BESSNoRetentionPolicy` (critical)

## Rollback

To rollback from v4.3.0 to v4.2.x:

1. The new tables will be ignored by older versions
2. No schema changes to existing tables
3. Simply deploy the previous version

**Note:** Any data in new tables (policies, holds, exports) will remain but be inaccessible until upgrading again.

## Recommended First Steps

1. **Review existing data volumes** to estimate retention needs
2. **Set up tenant retention policies** via UI or API
3. **Run dry-run purge** to preview what would be deleted
4. **Configure alerting** for purge failures
5. **Test compliance export** to verify bundle format

## Support

For issues with migration:
1. Check logs: `kubectl logs -l app=bess-dispatch`
2. Review purge history: `GET /compliance/purge/history`
3. Check legal holds: `GET /compliance/holds/summary`
