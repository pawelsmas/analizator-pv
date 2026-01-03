# SCIM Security Guide

Security considerations and best practices for SCIM provisioning.

## Overview

SCIM tokens provide powerful access to user and group management. This guide covers security controls and best practices.

## Token Security

### Token Generation

- Tokens are cryptographically random (256 bits of entropy)
- Token format: `scim_<base62_encoded_random_bytes>`
- Only the SHA-256 hash is stored in the database
- Plain token is shown only once at creation time

### Token Storage (IdP Side)

**DO:**
- Store tokens in IdP's secure credential store
- Use environment variables if storing in config
- Encrypt tokens at rest

**DON'T:**
- Store tokens in plain text files
- Commit tokens to version control
- Share tokens via email or chat

### Token Lifecycle

| Action | Impact |
|--------|--------|
| Create | New token, previous tokens unaffected |
| Revoke | Immediate rejection of all requests using that token |
| Expire | Automatic rejection after expiry date |

### Recommended Practices

1. **Use short-lived tokens**: 90-365 days maximum
2. **Rotate regularly**: Every 90 days for high-security environments
3. **Separate environments**: Use different tokens for prod/staging/dev
4. **Monitor usage**: Review `last_used_at` for inactive tokens

## Deprovision Semantics

### What Happens on Deprovision

When a SCIM user is disabled or deleted:

| Resource | Action | Reversible |
|----------|--------|------------|
| Active Sessions | Revoked immediately | No |
| API Keys | Revoked immediately | No |
| SCIM Memberships | Removed | Yes (re-sync) |
| Manual Memberships | Preserved | N/A |
| User Account | Marked inactive | Yes |

### Hard Delete vs Soft Delete

**Soft Delete** (`DELETE /scim/v2/Users/{id}`):
- User marked as `active=false`
- SCIM identity preserved
- Can be reactivated

**Hard Delete** (with `permanentDelete` param):
- SCIM identity removed
- User marked as `active=false`
- Cannot be reactivated via SCIM

### Session Revocation

On deprovision, all sessions are:
1. Marked as `revoked_at=now()`
2. Tagged with `revoked_reason='scim_deprovision'`
3. Immediately rejected on next auth check

## Access Controls

### SCIM Endpoint Authentication

All SCIM endpoints require:
- `Authorization: Bearer <scim_token>` header
- Valid, non-expired, non-revoked token
- Token must belong to the request tenant

### Rate Limiting

| Endpoint | Limit |
|----------|-------|
| `/scim/v2/Users` | 100 requests/minute |
| `/scim/v2/Groups` | 100 requests/minute |
| Token validation | 1000 requests/minute |

Exceeding limits returns `429 Too Many Requests`.

### IP Filtering (Optional)

For additional security, configure allowed IPs:

```yaml
scim:
  allowed_ips:
    - "52.x.x.x/24"  # Okta IPs
    - "40.x.x.x/24"  # Azure AD IPs
```

## Audit Logging

### Events Logged

| Event | Details Captured |
|-------|-----------------|
| Token Created | Token ID, name, expiry, creator |
| Token Revoked | Token ID, revoker, reason |
| User Provisioned | User ID, email, external ID |
| User Updated | User ID, changed fields |
| User Deprovisioned | User ID, type (soft/hard), resources revoked |
| Group Created | Group ID, display name |
| Group Updated | Group ID, membership changes |
| Mapping Created | Mapping ID, group, project, role |
| Sync Executed | Type, members added/removed |

### Log Retention

- Audit logs retained for 90 days
- Compressed and archived after 30 days
- Queryable via observability platform

### Sensitive Data Handling

**Not Logged:**
- Token values (only IDs)
- Passwords (never transmitted)
- Full request/response bodies

**Logged:**
- Token prefixes for identification
- Email addresses for user tracking
- IP addresses for security analysis

## Tenant Isolation

### Data Isolation

Each tenant has:
- Separate SCIM tokens
- Separate SCIM users and groups
- Separate group-project mappings

### Cross-Tenant Protection

- SCIM token validates tenant_id
- All queries include tenant_id filter
- Foreign key constraints prevent cross-tenant references

### Verification

Test isolation:
```bash
# Token A (tenant A) should NOT access tenant B's users
curl -H "Authorization: Bearer $TOKEN_A" \
  "https://portal/scim/v2/Users?filter=..."
# Should return only tenant A's users
```

## Network Security

### TLS Requirements

- TLS 1.2 or higher required
- TLS 1.3 preferred
- Strong cipher suites only

### Recommended Headers

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
```

## Incident Response

### Token Compromise

1. **Immediate**: Revoke compromised token
2. **Investigate**: Review audit logs for unauthorized actions
3. **Remediate**: Rollback any unauthorized changes
4. **Prevent**: Create new token with IP filtering

### Unauthorized Provisioning

1. **Identify**: Check audit logs for source
2. **Disable**: Revoke token if external
3. **Rollback**: Deprovision unauthorized users
4. **Review**: Check IdP for compromise

### Mass Deprovision Attack

1. **Detect**: Alert on `SCIMHighDeprovisionRate`
2. **Stop**: Revoke SCIM token
3. **Recover**: Reactivate users, restore memberships
4. **Investigate**: Identify attack vector

## Compliance

### GDPR Considerations

- SCIM syncs personal data (email, name)
- Deprovision removes SCIM-managed access
- Manual memberships require separate handling
- Audit logs may contain personal data

### SOC 2 Controls

| Control | Implementation |
|---------|---------------|
| Access Control | Token-based authentication |
| Encryption | TLS in transit, hashed at rest |
| Audit Logging | Comprehensive event logging |
| Separation | Tenant isolation |

## Checklist

### Initial Setup

- [ ] Create token with appropriate expiry
- [ ] Store token securely in IdP
- [ ] Test connection before enabling provisioning
- [ ] Configure alerting for token expiry

### Ongoing Operations

- [ ] Review token usage monthly
- [ ] Rotate tokens every 90 days
- [ ] Review audit logs for anomalies
- [ ] Test deprovision flow periodically

### Incident Preparation

- [ ] Document token revocation procedure
- [ ] Test recovery from mass deprovision
- [ ] Establish escalation path
- [ ] Keep IdP contact information current
