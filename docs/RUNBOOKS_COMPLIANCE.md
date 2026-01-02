# Compliance & Retention Runbooks

Operational runbooks for managing compliance features in BESS Dispatch.

## Table of Contents

1. [Retention Purge Failure](#retention-purge-failure)
2. [Legal Hold Management](#legal-hold-management)
3. [Compliance Export Issues](#compliance-export-issues)
4. [Purge Backlog](#purge-backlog)
5. [Emergency Data Preservation](#emergency-data-preservation)

---

## Retention Purge Failure

**Alert:** `BESSRetentionPurgeFailure`

### Symptoms
- Retention purge CronJob failing
- Data not being cleaned up on schedule
- Database growing beyond expected size

### Diagnosis

1. Check CronJob status:
   ```bash
   kubectl get cronjob retention-purge -n pv-optimizer
   kubectl get jobs -l app=retention-purge -n pv-optimizer
   ```

2. View recent job logs:
   ```bash
   kubectl logs job/$(kubectl get jobs -l app=retention-purge -n pv-optimizer -o jsonpath='{.items[-1].metadata.name}') -n pv-optimizer
   ```

3. Check for database locks:
   ```bash
   kubectl exec -it deploy/bess-dispatch -n pv-optimizer -- sqlite3 /data/compliance.db "PRAGMA busy_timeout;"
   ```

4. Verify retention policies exist:
   ```bash
   curl -X GET https://api.example.com/compliance/retention -H "Authorization: Bearer $TOKEN"
   ```

### Resolution

**Database connection issues:**
```bash
# Restart the service
kubectl rollout restart deployment/bess-dispatch -n pv-optimizer

# Verify PVC is mounted
kubectl describe pod -l app=bess-dispatch -n pv-optimizer | grep -A5 Mounts
```

**Legal hold blocking all resources:**
```bash
# Check active holds
curl -X GET https://api.example.com/compliance/holds/summary -H "Authorization: Bearer $TOKEN"

# Release unnecessary holds if appropriate
curl -X DELETE https://api.example.com/compliance/holds/{hold_id} -H "Authorization: Bearer $TOKEN"
```

**Missing retention policy:**
```bash
# Create default policy
curl -X PUT https://api.example.com/compliance/retention \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"runs_days": 365, "jobs_days": 90, "reports_days": 365}'
```

---

## Legal Hold Management

### Creating Emergency Legal Hold

When legal/compliance requires immediate data preservation:

```bash
# Hold all tenant data
curl -X POST https://api.example.com/compliance/holds \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "resource_type": "all",
    "reason": "Legal investigation - Case #12345"
  }'

# Hold specific project
curl -X POST https://api.example.com/compliance/holds \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "resource_type": "project",
    "resource_id": "proj-abc123",
    "reason": "Regulatory audit"
  }'
```

### Listing Active Holds

```bash
# Get summary
curl -X GET https://api.example.com/compliance/holds/summary -H "Authorization: Bearer $TOKEN"

# List all holds with details
curl -X GET https://api.example.com/compliance/holds -H "Authorization: Bearer $TOKEN"
```

### Releasing Legal Hold

**Warning:** Only release holds after explicit legal/compliance approval.

```bash
# Release by hold ID
curl -X DELETE https://api.example.com/compliance/holds/{hold_id} \
  -H "Authorization: Bearer $TOKEN"
```

### Auditing Legal Hold Activity

All legal hold operations are logged in audit:

```bash
# Export audit logs for legal hold events
curl -X POST https://api.example.com/compliance/exports \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "include_audit_logs": true,
    "include_legal_holds": true
  }'
```

---

## Compliance Export Issues

### Export Job Stuck in "Running"

1. Check export job status:
   ```bash
   curl -X GET https://api.example.com/compliance/exports/{export_id} -H "Authorization: Bearer $TOKEN"
   ```

2. Check worker logs:
   ```bash
   kubectl logs -l app=bess-dispatch -n pv-optimizer | grep -i export
   ```

3. If stuck for >1 hour, delete and recreate:
   ```bash
   curl -X DELETE https://api.example.com/compliance/exports/{export_id} -H "Authorization: Bearer $TOKEN"

   # Recreate export
   curl -X POST https://api.example.com/compliance/exports \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"wait": false}'
   ```

### Large Export Timing Out

For large exports (>100MB), use async mode:

```bash
# Start async export
curl -X POST https://api.example.com/compliance/exports \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"wait": false}'

# Poll status
watch -n 30 "curl -s https://api.example.com/compliance/exports/{export_id} -H 'Authorization: Bearer $TOKEN' | jq '.status, .progress_pct'"
```

### Corrupted Export Bundle

1. Verify manifest checksums:
   ```bash
   unzip -p export.zip manifest.json | jq '.files[] | {name, sha256}'

   # Verify individual file
   sha256sum <(unzip -p export.zip data_runs.json)
   ```

2. Recreate export if checksums don't match

---

## Purge Backlog

**Alert:** `BESSPurgeHittingLimits`

### Symptoms
- Purge jobs consistently hitting MAX_DELETIONS_PER_RUN limit
- Database size not decreasing as expected
- Multiple consecutive limited purge runs

### Diagnosis

1. Check purge history:
   ```bash
   curl -X GET "https://api.example.com/compliance/purge/history?limit=10" -H "Authorization: Bearer $TOKEN"
   ```

2. Check if hitting limits:
   ```bash
   curl -X GET https://api.example.com/compliance/purge/history -H "Authorization: Bearer $TOKEN" | jq '.[] | select(.hit_limit == true)'
   ```

3. Estimate backlog with dry-run:
   ```bash
   curl -X POST https://api.example.com/compliance/purge/dry-run \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{}'
   ```

### Resolution

**Temporary increase deletion limit:**
```bash
# Update ConfigMap
kubectl patch configmap retention-config -n pv-optimizer \
  --patch '{"data":{"max_deletions_per_run":"50000"}}'

# Trigger immediate purge
kubectl create job --from=cronjob/retention-purge retention-backlog -n pv-optimizer
```

**Run multiple purges to clear backlog:**
```bash
# Run purge 5 times in sequence
for i in {1..5}; do
  echo "=== Purge run $i ==="
  curl -X POST https://api.example.com/compliance/purge/execute \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"max_deletions": 10000}'
  sleep 60
done
```

**Process specific category only:**
```bash
curl -X POST https://api.example.com/compliance/purge/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"categories": ["jobs"]}'
```

---

## Emergency Data Preservation

### Immediate Actions for Data Preservation

1. **Stop all purge jobs:**
   ```bash
   kubectl scale cronjob retention-purge --replicas=0 -n pv-optimizer
   # Or suspend
   kubectl patch cronjob retention-purge -n pv-optimizer -p '{"spec":{"suspend":true}}'
   ```

2. **Create blanket legal hold:**
   ```bash
   curl -X POST https://api.example.com/compliance/holds \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "resource_type": "all",
       "reason": "EMERGENCY PRESERVATION - Pending investigation"
     }'
   ```

3. **Verify no purge running:**
   ```bash
   kubectl get jobs -l app=retention-purge -n pv-optimizer --no-headers | wc -l
   ```

4. **Create immediate export:**
   ```bash
   curl -X POST https://api.example.com/compliance/exports \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "include_all": true,
       "redaction_mode": "none"
     }'
   ```

### Database Backup

```bash
# Create backup
kubectl exec deploy/bess-dispatch -n pv-optimizer -- sqlite3 /data/compliance.db ".backup /tmp/compliance_backup.db"

# Copy backup locally
kubectl cp pv-optimizer/$(kubectl get pod -l app=bess-dispatch -n pv-optimizer -o jsonpath='{.items[0].metadata.name}'):/tmp/compliance_backup.db ./compliance_backup_$(date +%Y%m%d).db
```

### Restoring Normal Operations

1. Remove legal hold (with approval):
   ```bash
   curl -X DELETE https://api.example.com/compliance/holds/{hold_id} -H "Authorization: Bearer $TOKEN"
   ```

2. Resume purge CronJob:
   ```bash
   kubectl patch cronjob retention-purge -n pv-optimizer -p '{"spec":{"suspend":false}}'
   ```

3. Verify next scheduled run:
   ```bash
   kubectl get cronjob retention-purge -n pv-optimizer
   ```

---

## Monitoring Dashboard Queries

### Prometheus Queries

**Purge success rate (last 24h):**
```promql
sum(increase(bess_purge_runs_total{result="success"}[24h])) /
sum(increase(bess_purge_runs_total[24h]))
```

**Resources deleted by category (last 7d):**
```promql
sum by (category) (increase(bess_purge_deleted_total[7d]))
```

**Active legal holds:**
```promql
sum(bess_legal_hold_active)
```

**Export job duration P95:**
```promql
histogram_quantile(0.95, rate(bess_compliance_export_duration_seconds_bucket[1h]))
```

---

## Escalation Path

1. **L1 Support:** Check logs, restart services, verify configuration
2. **L2 Support:** Database analysis, manual purge execution, legal hold management
3. **Engineering:** Schema issues, code bugs, performance problems
4. **Legal/Compliance:** Legal hold decisions, data retention policy changes

## Contact

- On-call engineering: #bess-oncall
- Legal/Compliance: legal@company.com
- Security incidents: security@company.com
