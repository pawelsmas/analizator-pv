# SCIM Migration Guide

Guide for migrating from manual user management to SCIM provisioning.

## Overview

This guide covers:
1. Pre-migration assessment
2. Pilot deployment
3. Full migration
4. Post-migration validation

## Pre-Migration Assessment

### Current State Analysis

Document your current setup:

| Question | Answer |
|----------|--------|
| Total users | ___ |
| Total projects | ___ |
| Users per project (avg) | ___ |
| IdP in use | ___ |
| IdP SCIM support? | Yes/No |

### User Mapping Strategy

Decide how IdP users map to portal users:

| Strategy | When to Use |
|----------|-------------|
| Email Match | Users already exist with same email |
| Create New | New users without existing accounts |
| Hybrid | Mix of existing and new users |

### Group Mapping Strategy

Plan your group → project mappings:

```
IdP Group              →    Portal Project    →    Role
─────────────────────────────────────────────────────────
Engineering            →    Core Platform     →    editor
Engineering Leads      →    Core Platform     →    admin
QA Team                →    Core Platform     →    viewer
```

## Phase 1: Pilot Deployment

### Scope

- 1 pilot group (5-10 users)
- 1 test project
- Non-production environment (if available)

### Steps

1. **Create SCIM Token**
   ```
   Portal → Settings → Provisioning → + Create Token
   Name: "Pilot - [IdP Name]"
   Expiry: 30 days
   ```

2. **Configure IdP**
   - Add SCIM application
   - Configure base URL and token
   - Test connection

3. **Push Pilot Group**
   - Assign pilot group to SCIM app
   - Enable "Push Groups" for pilot group
   - Verify group appears in portal

4. **Create Mapping**
   ```
   Portal → Settings → Provisioning → Mappings → + Add
   Group: [Pilot Group]
   Project: [Test Project]
   Role: editor
   ```

5. **Verify Sync**
   - Check project membership
   - Test user login
   - Test permission enforcement

6. **Test Deprovision**
   - Remove a user from pilot group
   - Verify access revoked
   - Verify sessions invalidated

### Pilot Success Criteria

- [ ] Users synced within 5 minutes
- [ ] Project access correct
- [ ] Deprovision works as expected
- [ ] No duplicate users created
- [ ] Manual memberships preserved

## Phase 2: Full Migration

### Timeline

| Week | Activity |
|------|----------|
| 1 | Configure all groups in IdP |
| 2 | Create all mappings in portal |
| 3 | Enable sync, monitor |
| 4 | Address issues, validate |

### Pre-Migration Checklist

- [ ] Backup database
- [ ] Document current memberships
- [ ] Notify users about migration
- [ ] Schedule during low-activity period
- [ ] Have rollback plan ready

### Migration Steps

1. **Export Current State**
   ```sql
   -- Save current memberships
   SELECT * FROM project_memberships
   INTO OUTFILE '/backup/memberships_backup.csv';
   ```

2. **Configure IdP**
   - Assign all groups to SCIM app
   - Verify attribute mappings
   - Test with single group first

3. **Create All Mappings**
   ```
   For each group → project pair:
   POST /api/provisioning/mappings
   {
     "scim_group_id": "...",
     "project_id": "...",
     "role": "editor"
   }
   ```

4. **Enable Full Sync**
   - Enable "Push Groups" for all groups
   - Monitor sync progress
   - Check for errors

5. **Validate**
   ```
   GET /api/provisioning/mappings/status
   ```
   Compare counts with expectations.

### Handling Existing Users

#### If Email Matches (Recommended)

When SCIM creates a user with matching email:
- User linked to existing account
- SCIM manages group memberships
- Manual memberships preserved

#### If No Email Match

Options:
1. **Pre-create users**: Create accounts before SCIM sync
2. **Let SCIM create**: SCIM creates new accounts
3. **Manual merge**: Link accounts after creation

### Handling Existing Memberships

#### SCIM Memberships (source='scim')

- Created by SCIM sync
- Managed entirely by SCIM
- Revoked on deprovision

#### Manual Memberships (source='manual')

- Created via UI/API
- **Never modified by SCIM**
- Must be managed separately

#### Conversion Strategy

To convert manual → SCIM managed:

1. Create group in IdP with same users
2. Create mapping in portal
3. After sync, manual membership becomes redundant
4. Optionally remove manual membership

```sql
-- Identify redundant memberships
SELECT pm.id, pm.user_id, pm.project_id
FROM project_memberships pm
WHERE pm.source = 'manual'
AND EXISTS (
  SELECT 1 FROM project_memberships scim
  WHERE scim.user_id = pm.user_id
  AND scim.project_id = pm.project_id
  AND scim.source = 'scim'
);
```

## Phase 3: Post-Migration

### Validation Checklist

- [ ] All expected users provisioned
- [ ] All group memberships correct
- [ ] All project access verified
- [ ] Login works for migrated users
- [ ] API access works (if applicable)

### Monitoring

Set up alerts:
- `SCIMSyncFailing` - Sync errors
- `SCIMSyncStale` - No sync in 24h
- `SCIMTokenExpiringSoon` - Token near expiry

### Documentation Update

Update runbooks with:
- SCIM token location
- IdP configuration details
- Escalation contacts

### User Communication

Notify users:
- How access is now managed
- Who to contact for access issues
- What changes (if any) they'll notice

## Rollback Plan

If migration fails:

1. **Disable SCIM Token**
   ```
   DELETE /api/provisioning/tokens/{token_id}
   ```

2. **Disable All Mappings**
   ```sql
   UPDATE scim_group_project_mappings SET enabled = 0;
   ```

3. **Restore Manual Memberships**
   ```sql
   -- If needed, restore from backup
   INSERT INTO project_memberships
   SELECT * FROM backup_memberships
   WHERE source = 'manual';
   ```

4. **Notify Users**
   - Explain temporary issue
   - Provide timeline for resolution

## Troubleshooting

### Users Not Syncing

1. Check IdP assignment
2. Verify SCIM token valid
3. Check IdP provisioning logs
4. Trigger manual sync

### Duplicate Users

If duplicates created:
1. Identify duplicate accounts
2. Merge or disable duplicates
3. Verify email matching configured correctly

### Permission Issues

1. Verify mapping exists and is enabled
2. Check correct role in mapping
3. Trigger group sync
4. Check for conflicting manual memberships

## Best Practices

### Do

- Start with pilot before full migration
- Keep manual memberships for exceptions
- Monitor sync status regularly
- Rotate tokens on schedule
- Document everything

### Don't

- Migrate during business hours (first time)
- Delete manual memberships immediately
- Ignore sync errors
- Share SCIM tokens
- Skip validation steps
