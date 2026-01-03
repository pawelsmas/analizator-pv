# SCIM Provisioning Runbooks

Operational runbooks for SCIM provisioning incidents and maintenance.

## Table of Contents

1. [Token Expiry](#token-expiry)
2. [Sync Failures](#sync-failures)
3. [User Not Provisioned](#user-not-provisioned)
4. [Orphaned Memberships](#orphaned-memberships)
5. [Emergency Token Revocation](#emergency-token-revocation)
6. [Mass Deprovision](#mass-deprovision)
7. [Performance Issues](#performance-issues)

---

## Token Expiry

### Alert
`SCIMTokenExpiringSoon` or `SCIMTokenExpired`

### Symptoms
- SCIM requests returning 401 Unauthorized
- No new users being provisioned
- IdP showing connection errors

### Resolution

1. **Create a new token**:
   ```
   Portal → Settings → Provisioning → + Create Token
   ```

2. **Update IdP configuration**:
   - Okta: Applications → [App] → Provisioning → Integration → Edit
   - Azure AD: Enterprise Apps → [App] → Provisioning → Admin Credentials

3. **Test connection** from IdP

4. **Revoke old token** (optional but recommended):
   ```
   Portal → Settings → Provisioning → [Token] → Revoke
   ```

5. **Trigger a sync** to verify:
   ```
   Portal → Settings → Provisioning → Sync Now
   ```

### Prevention
- Set calendar reminder 30 days before expiry
- Configure `SCIMTokenExpiringSoon` alert
- Use tokens with 365-day expiry

---

## Sync Failures

### Alert
`SCIMSyncFailing` or `SCIMSyncStale`

### Symptoms
- Group memberships not updating
- Users missing from projects
- Sync status shows errors

### Diagnosis

1. **Check sync status**:
   ```
   GET /api/provisioning/mappings/status
   ```
   Response shows last sync time and error counts.

2. **Check SCIM metrics**:
   ```
   scim_sync_errors_total{tenant_id="..."}
   ```

3. **Review recent sync logs** in observability platform.

### Resolution

1. **Trigger manual sync**:
   ```
   POST /api/provisioning/mappings/sync
   ```

2. **For specific group**:
   ```
   POST /api/provisioning/mappings/sync
   Body: {"scim_group_id": "<group_id>"}
   ```

3. **If database issues**:
   - Check database connectivity
   - Verify WAL mode is enabled
   - Check disk space

4. **If IdP issues**:
   - Verify IdP is sending updates
   - Check IdP provisioning logs
   - Re-save app configuration in IdP to trigger full sync

---

## User Not Provisioned

### Symptoms
- User exists in IdP but not in portal
- User can't log in despite being assigned

### Diagnosis

1. **Check if user exists in SCIM**:
   ```
   GET /scim/v2/Users?filter=userName eq "user@example.com"
   ```

2. **Check group membership**:
   ```
   GET /scim/v2/Groups/{group_id}
   ```

3. **Check mapping status**:
   ```
   GET /api/provisioning/mappings?scim_group_id={group_id}
   ```

### Resolution

1. **If user not in SCIM store**:
   - Verify user is assigned to the app in IdP
   - Trigger "Push Users" from IdP
   - Check IdP provisioning logs for errors

2. **If user exists but not in project**:
   - Verify group mapping exists and is enabled
   - Trigger sync for the group
   - Check for sync errors

3. **Force user sync**:
   ```
   POST /scim/v2/Users
   Body: { user data from IdP }
   ```

---

## Orphaned Memberships

### Alert
`SCIMOrphanedMappings`

### Symptoms
- Users in projects who shouldn't be
- Mappings referencing deleted groups

### Diagnosis

1. **List all mappings**:
   ```
   GET /api/provisioning/mappings
   ```

2. **Cross-reference with groups**:
   ```
   GET /scim/v2/Groups
   ```

3. **Check for mismatches**.

### Resolution

1. **Delete orphaned mappings**:
   ```
   DELETE /api/provisioning/mappings/{mapping_id}
   ```
   This automatically revokes related memberships.

2. **Manual cleanup** (if needed):
   ```sql
   DELETE FROM project_memberships
   WHERE source = 'scim'
   AND scim_group_id NOT IN (SELECT id FROM scim_groups);
   ```

3. **Trigger full sync**:
   ```
   POST /api/provisioning/mappings/sync
   ```

---

## Emergency Token Revocation

### Scenario
Token potentially compromised.

### Immediate Actions

1. **Revoke the token**:
   ```
   DELETE /api/provisioning/tokens/{token_id}
   ```
   Or via UI: Portal → Settings → Provisioning → [Token] → Revoke

2. **Create new token** and update IdP.

3. **Review audit logs**:
   ```
   Filter: action="scim_request" AND token_id="{compromised_token}"
   ```

4. **Check for unauthorized changes**:
   - New users created
   - Users deleted
   - Group membership changes

5. **If malicious activity detected**:
   - Rollback unauthorized changes
   - Notify affected users
   - Follow security incident process

---

## Mass Deprovision

### Alert
`SCIMHighDeprovisionRate`

### Scenario
Large number of users being deprovisioned simultaneously.

### Verification

1. **Check if expected** (e.g., company layoff, offboarding):
   - Contact HR/IT to confirm
   - Document the expected scope

2. **If unexpected**:
   - **PAUSE** by disabling SCIM token
   - Investigate the cause

### If Unexpected - Recovery

1. **Disable SCIM token** immediately:
   ```
   DELETE /api/provisioning/tokens/{token_id}
   ```

2. **Check IdP for unauthorized changes**:
   - Deleted groups
   - Modified assignments
   - Compromised admin account

3. **Restore users** (if needed):
   ```python
   # Reactivate users
   for user_id in affected_users:
       PATCH /scim/v2/Users/{user_id}
       Body: {"active": true}
   ```

4. **Trigger full sync** after resolving the issue.

### If Expected - Monitoring

1. **Monitor the process**:
   ```
   scim_users_deprovisioned_total
   scim_deprovision_sessions_revoked_total
   ```

2. **Verify completion**:
   ```
   GET /api/provisioning/mappings/status
   ```

---

## Performance Issues

### Alert
`SCIMRequestLatencyHigh` or `SCIMSyncDurationHigh`

### Symptoms
- SCIM requests timing out
- Sync taking longer than expected
- IdP showing connection errors

### Diagnosis

1. **Check request latency**:
   ```
   histogram_quantile(0.95, scim_users_request_duration_seconds_bucket)
   ```

2. **Check sync duration**:
   ```
   histogram_quantile(0.95, scim_sync_duration_seconds_bucket)
   ```

3. **Check database performance**:
   - Query execution times
   - Lock contention
   - Index usage

### Resolution

1. **For high request latency**:
   - Check database connection pool
   - Verify indices exist on frequently queried columns
   - Consider rate limiting adjustments

2. **For slow syncs**:
   - Break large groups into smaller ones
   - Sync groups individually instead of all at once
   - Schedule syncs during off-peak hours

3. **Database optimization**:
   ```sql
   -- Verify index exists
   CREATE INDEX IF NOT EXISTS idx_project_memberships_scim
   ON project_memberships(scim_group_id, source);

   -- Analyze tables
   ANALYZE project_memberships;
   ANALYZE scim_groups;
   ```

4. **If persistent issues**:
   - Review database size and growth
   - Consider archiving old data
   - Scale database resources

---

## Maintenance Tasks

### Regular Token Rotation

Run every 90 days:

1. Create new token with 90-day expiry
2. Update IdP configuration
3. Test connection
4. Revoke old token

### Sync Health Check

Run weekly:

```
GET /api/provisioning/mappings/status
```

Verify:
- `scim_groups` matches IdP group count
- `enabled_mappings` matches expected mappings
- No stale sync timestamps

### Audit Review

Run monthly:

1. Review provisioning audit logs
2. Check for unusual patterns
3. Verify all tokens are still needed
4. Review and cleanup orphaned mappings
