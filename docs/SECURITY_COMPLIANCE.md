# Compliance & Retention Security Guide

Security considerations for the BESS Dispatch compliance and retention features.

## Overview

The compliance module handles sensitive data operations including:
- Data retention and automated deletion
- Legal holds for litigation/regulatory preservation
- Compliance exports with audit trails
- Purge execution with safety controls

## Authorization Model

### Role Requirements

| Feature | Required Role | Notes |
|---------|--------------|-------|
| View retention policies | admin | Not visible to editors/viewers |
| Modify retention policies | admin | Tenant or project scope |
| Create legal holds | admin | Requires reason documentation |
| Release legal holds | admin | Audit logged |
| Execute purge (dry-run) | admin | Preview only |
| Execute purge (execute) | admin | Irreversible deletion |
| Create compliance export | admin | May contain PII |
| Download compliance export | admin | Redacted by default |
| Delete compliance export | admin | Bundle cleanup |

### Tenant Isolation

- Each tenant's compliance data is strictly isolated
- Cross-tenant access is prevented at database and API levels
- Multi-tenant queries are not supported
- All operations are scoped to authenticated tenant

### Project Scoping

- Project retention policies override tenant defaults
- Project owners can set project-specific policies
- Non-members cannot access project compliance data

## Data Classification

### Sensitive Data in Exports

Compliance exports may contain:

| Category | Sensitivity | Default Redaction |
|----------|------------|-------------------|
| User emails | PII | Redacted to `***@domain.com` |
| User IDs | PII | Preserved (required for audit) |
| IP addresses | PII | Redacted |
| API keys | Secret | Fully redacted |
| Calculation inputs | Business | Not redacted |
| Calculation results | Business | Not redacted |
| Audit logs | Audit | User details redacted |

### Redaction Modes

```json
{
  "redaction_mode": "standard"  // Default - redact PII
  // "redaction_mode": "none"   // No redaction - requires explicit approval
  // "redaction_mode": "full"   // Maximize redaction
}
```

## Legal Hold Security

### Creating Legal Holds

```json
{
  "resource_type": "run",
  "resource_id": "run-abc123",
  "reason": "Required documentation for reason",
  "expires_at": null  // Optional expiry
}
```

**Requirements:**
- Admin role required
- Reason field mandatory
- Audit logged with user ID
- Cannot be silently removed

### Hold Protection

Legal holds provide:
- Protection against automated purge
- Protection against manual deletion
- Audit trail of hold lifecycle
- No silent removal capability

### Releasing Holds

- Requires admin role
- Logged to audit trail
- Resource becomes eligible for purge
- Historical hold record preserved

## Purge Security

### Safety Controls

1. **Maximum Deletions Limit**
   - Default: 10,000 per run
   - Configurable via ConfigMap
   - Prevents accidental mass deletion

2. **Dry-Run Mode**
   - Preview before execution
   - No data modification
   - Full statistics available

3. **Legal Hold Enforcement**
   - Held resources skipped
   - Logged as "skipped_held"
   - Cannot be overridden

4. **Category Isolation**
   - Process specific categories only
   - Limit blast radius

5. **Audit Trail**
   - Every purge run logged
   - Deletion counts by category
   - Success/failure status

### Purge Authorization Flow

```
User Request
    ↓
Auth Check (admin role)
    ↓
Rate Limit Check
    ↓
Legal Hold Check (per resource)
    ↓
Retention Policy Check
    ↓
Deletion with Audit
```

## Export Security

### Bundle Contents

Standard compliance export ZIP structure:

```
export.zip
├── manifest.json         # SHA256 checksums, export metadata
├── metadata.json         # Export parameters, timestamps
├── data_retention_policies.json
├── data_legal_holds.json
├── data_audit_logs.json  # Redacted user details
├── data_runs.json        # Run summaries only
├── data_jobs.json        # Job summaries only
└── data_reports.json     # Report metadata only
```

### Verification

Each export includes:
- SHA256 checksums for all files
- Export timestamp
- Creator user ID
- Export version number
- Redaction mode used

### Access Control

- Exports stored temporarily (30 days default)
- Download requires admin role
- Download logged to audit
- Automatic expiry and cleanup

## Audit Trail

### Events Logged

| Event | Details Captured |
|-------|-----------------|
| `retention_policy_created` | Policy JSON, scope, user |
| `retention_policy_updated` | Old/new values, user |
| `retention_policy_deleted` | Policy ID, user |
| `legal_hold_created` | Resource type/ID, reason, user |
| `legal_hold_released` | Hold ID, user |
| `purge_dry_run` | Counts by category |
| `purge_executed` | Deletions by category, held skips |
| `compliance_export_created` | Options, user |
| `compliance_export_downloaded` | Export ID, user |
| `compliance_export_deleted` | Export ID, user |

### Retention of Audit Logs

- Default: 730 days (2 years)
- Legal holds protect audit logs
- Audit logs included in compliance exports

## Encryption

### At Rest

- SQLite database with WAL mode
- Relies on volume encryption (recommended)
- No application-level encryption

### In Transit

- All API endpoints require HTTPS
- Export downloads over HTTPS
- Inter-service communication via cluster network

## Incident Response

### Unauthorized Access Attempt

1. Alert triggers on denied access
2. Review audit logs for pattern
3. Block suspicious IPs if needed
4. Notify security team

### Accidental Mass Deletion

1. Legal holds prevent most scenarios
2. Check purge history for details
3. Restore from backup if needed
4. Post-incident: review limits

### Legal Hold Violation

1. Cannot happen through API
2. Database-level tampering requires:
   - Pod access
   - DB credentials
   - Audit trail bypass
3. Investigate infrastructure access

## Compliance Certifications

Features designed to support:
- **GDPR:** Data retention, deletion, export
- **SOX:** Audit trails, access controls
- **HIPAA:** Access logging, data protection
- **SOC 2:** Security controls, monitoring

## Security Checklist

- [ ] Admin role restricted to authorized users
- [ ] Retention policies set for all tenants
- [ ] Legal hold process documented
- [ ] Purge job alerts configured
- [ ] Export access reviewed regularly
- [ ] Audit log retention appropriate
- [ ] Volume encryption enabled
- [ ] Network policies configured
- [ ] RBAC permissions audited

## Contact

- Security team: security@company.com
- Compliance officer: compliance@company.com
- On-call engineering: #bess-oncall
