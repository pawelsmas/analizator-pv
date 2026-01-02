# Authentication & Authorization (v3.8.0)

This document describes the authentication and authorization system in BESS PRO.

## Overview

BESS PRO supports two authentication modes:
- **Disabled mode** (default): No authentication required, all requests allowed
- **Enabled mode**: JWT/API key authentication required

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_MODE` | `disabled` | Set to `enabled` to require authentication |
| `AUTH_JWT_SECRET` | (random) | Secret key for JWT signing (32+ chars recommended) |
| `AUTH_JWT_EXPIRE_MINUTES` | `1440` | JWT token expiration (24 hours default) |
| `AUTH_DB_PATH` | `auth.sqlite` | Path to auth SQLite database |

### Enabling Authentication

```bash
# docker-compose.yml
services:
  bess-dispatch:
    environment:
      - AUTH_MODE=enabled
      - AUTH_JWT_SECRET=your-secret-key-min-32-chars-long
```

## Authentication Methods

### 1. JWT Token (Bearer)

Use for user sessions (web UI, interactive use).

```bash
# Login to get token
curl -X POST /api/bess-dispatch/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "secret"}'

# Response: {"access_token": "eyJ..."}

# Use token in requests
curl /api/bess-dispatch/sizing \
  -H "Authorization: Bearer eyJ..."
```

### 2. API Key (X-API-Key)

Use for service-to-service communication, CI/CD, scripts.

```bash
# Use API key in requests
curl /api/bess-dispatch/sizing \
  -H "X-API-Key: bess_abcd1234..."
```

## API Endpoints

### Auth Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/login` | POST | Login with email/password, returns JWT |
| `/auth/me` | GET | Get current user info |

### Admin Endpoints (admin role required)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/api-keys` | GET | List API keys for tenant |
| `/admin/api-keys` | POST | Create new API key |
| `/admin/api-keys/{key_id}` | DELETE | Revoke API key |
| `/audit` | GET | Query audit log |
| `/audit/export/csv` | GET | Export audit log as CSV |
| `/audit/export/json` | GET | Export audit log as JSON |
| `/audit/export/zip` | GET | Export audit log as ZIP |

## Role-Based Access Control (RBAC)

### Role Hierarchy

```
admin > editor = service > viewer
```

- **admin**: Full access, can manage users and API keys
- **editor**: Read/write access to sizing and runs
- **service**: Same as editor, for service accounts
- **viewer**: Read-only access

### Permission Mapping

| Endpoint | Required Role |
|----------|---------------|
| `/sizing` (POST) | editor |
| `/sizing` (GET) | viewer |
| `/runs` | viewer |
| `/jobs` | viewer |
| `/admin/*` | admin |
| `/audit` | admin |

## Multi-Tenancy

All data is isolated by tenant:
- Runs are only visible to the tenant that created them
- Jobs are scoped by tenant
- API keys are per-tenant
- Audit logs are per-tenant

Cross-tenant access returns 404 (not 403) to prevent information leakage.

## Audit Logging

All security-relevant events are logged:
- `login_success` / `login_failure`
- `api_key_created` / `api_key_revoked`
- `sizing_run` / `validation_run`

Query with filters:
```bash
curl "/api/bess-dispatch/audit?action=login_failure&limit=100"
```

Export for compliance:
```bash
curl /api/bess-dispatch/audit/export/zip -o audit.zip
```

## Frontend Integration

### Login Page

Navigate to `/login.html` for the login form.

### WhoAmI Badge

The header shows current user info:
- Email
- Role (colored badge)
- Tenant
- Logout button

### Settings Page (Admin)

Navigate to `/settings.html` to:
- Manage API keys (list, create, revoke)
- View audit log with filtering

## Security Best Practices

1. **Always set a strong JWT secret** in production
2. **Use API keys for automation**, JWT for users
3. **Set expiration on API keys** for temporary access
4. **Monitor audit logs** for suspicious activity
5. **Use HTTPS** in production

## Migration from v2.x

When upgrading from v2.x (no auth):

1. Deploy with `AUTH_MODE=disabled` (default)
2. Test that everything works
3. Seed admin user (optional, admin@local:admin created if empty)
4. Switch to `AUTH_MODE=enabled`
5. Update clients to use API keys

Existing runs and jobs get `tenant_id='default'` automatically.

## Projects & Per-Project RBAC (v3.7.0)

### Overview

Projects provide a way to organize resources (runs, jobs, reports) and control access at a granular level. Each project has:
- **Members** with roles (owner, editor, viewer)
- **Share policies** (allow_public_shares, share_max_expiry_hours)
- **Scoped resources** (runs, jobs, reports)

### Project Endpoints

| Endpoint | Method | Description | Required Role |
|----------|--------|-------------|---------------|
| `/projects` | GET | List user's projects | viewer |
| `/projects` | POST | Create project | editor |
| `/projects/{id}` | GET | Get project details | project viewer |
| `/projects/{id}` | PATCH | Update project | project owner |
| `/projects/{id}` | DELETE | Archive project | project owner |
| `/projects/{id}/members` | GET | List members | project viewer |
| `/projects/{id}/members` | POST | Add member | project owner |
| `/projects/{id}/members/{user_id}` | PATCH | Update role | project owner |
| `/projects/{id}/members/{user_id}` | DELETE | Remove member | project owner |

### Project Roles

```
owner > editor > viewer
```

- **owner**: Full control - update settings, manage members, create/delete resources
- **editor**: Create runs/jobs, update resources, cannot manage members
- **viewer**: Read-only access to project resources

### Project-Scoped Resources

Resources are filtered by project when `project_id` query parameter is provided:

```bash
# Get runs for specific project
GET /runs?project_id=proj_abc123

# Create run in project
POST /sizing
{ "project_id": "proj_abc123", ... }
```

### Share Policies

Each project can configure share policies:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `allow_public_shares` | bool | true | Allow creating public share links |
| `share_max_expiry_hours` | int | null | Max expiration for shares (null = unlimited) |

Policy enforcement:
- If `allow_public_shares=false`: Share creation fails with error `PUBLIC_SHARES_DISABLED`
- If `share_max_expiry_hours` set: Expiration is clamped to max value

### Default Project

When authentication is enabled, a default project is created for each tenant:
- Name: "Default Project"
- ID: `proj_default_{tenant_id}`
- All existing runs migrate to this project

### Migration from v3.6.x

When upgrading from v3.6.x:

1. Database migration creates `projects` and `project_memberships` tables
2. Default project is created for each tenant
3. Existing runs get assigned to the default project
4. All tenant users become members of the default project
5. Admin users become project owners

### Frontend Integration

#### Project Selector (index.html)

A project dropdown in the main page allows filtering by project:
- Stored in `localStorage` as `bess_selected_project`
- Refreshes run lists when changed

#### Projects Admin (settings.html)

The Settings page has a "Projekty" tab for:
- Creating new projects
- Editing project settings
- Managing project members
- Archiving projects

### Audit Events

Project operations are logged:
- `project_created`
- `project_updated`
- `project_archived`
- `project_member_added`
- `project_member_updated`
- `project_member_removed`
- `share_created` (includes project_id)
- `share_revoked`
- `share_create_denied` (policy violation)

### Regression Testing

Use the `projects_rbac_auth` scenario pack for validation:

```bash
make validate-pack PACK=projects_rbac_auth
```

## Share Links v2 (v3.8.0)

### Overview

Share links allow secure external access to runs and reports without authentication. v3.8.0 introduces enhanced security features:

- **Password protection**: Optional bcrypt-hashed passwords
- **Single-use tokens**: Auto-revoke after first access
- **Max access count**: Limit total number of accesses
- **Token rotation**: Rotate tokens without recreating shares
- **Access logging**: Track all share access attempts

### Creating Shares

```bash
# Basic share (no password, no limits)
POST /api/bess-dispatch/admin/shares
{
  "resource_type": "run",
  "resource_id": "run_abc123",
  "label": "For client review"
}

# Password-protected share
POST /api/bess-dispatch/admin/shares
{
  "resource_type": "run",
  "resource_id": "run_abc123",
  "password": "secure-password-10-chars",
  "expires_hours": 24
}

# Single-use share
POST /api/bess-dispatch/admin/shares
{
  "resource_type": "run",
  "resource_id": "run_abc123",
  "single_use": true
}

# Limited access count
POST /api/bess-dispatch/admin/shares
{
  "resource_type": "run",
  "resource_id": "run_abc123",
  "max_access_count": 5
}
```

### Share Fields (v3.8.0)

| Field | Type | Description |
|-------|------|-------------|
| `requires_password` | bool | Whether password is required |
| `password_hash` | string | Bcrypt hash (internal) |
| `single_use` | bool | Auto-revoke after first access |
| `max_access_count` | int | Max allowed accesses (null = unlimited) |
| `access_count` | int | Current access count |
| `last_access_at` | datetime | Last successful access timestamp |
| `token_version` | int | Token version for rotation |

### Accessing Shares

```bash
# Access without password
GET /api/bess-dispatch/shared/runs/{run_id}/summary
X-Share-Token: share_token_here

# Access with password
GET /api/bess-dispatch/shared/runs/{run_id}/summary
X-Share-Token: share_token_here
X-Share-Password: secure-password
```

### Access Denied Responses

| Error Code | Description |
|------------|-------------|
| `INVALID_TOKEN` | Token not found or revoked |
| `EXPIRED` | Share has expired |
| `PASSWORD_REQUIRED` | Password needed but not provided |
| `INVALID_PASSWORD` | Wrong password |
| `ACCESS_LIMIT_EXCEEDED` | Max access count reached |

### Token Rotation

Rotate a share token without changing other settings:

```bash
POST /api/bess-dispatch/admin/shares/{share_id}/rotate
```

Response includes new plaintext token (shown once).

### Bulk Revocation

Revoke all shares for a project or resource:

```bash
# Revoke all shares in a project
POST /api/bess-dispatch/admin/shares/revoke-all
{
  "project_id": "proj_abc123"
}

# Revoke all shares for a specific resource
POST /api/bess-dispatch/admin/shares/revoke-all
{
  "resource_type": "run",
  "resource_id": "run_abc123"
}
```

### Access Logs

View access logs for a share:

```bash
GET /api/bess-dispatch/admin/shares/{share_id}/access-logs?limit=50
```

Response:
```json
{
  "items": [
    {
      "id": "log_123",
      "share_id": "share_abc",
      "accessed_at": "2025-01-15T10:30:00Z",
      "ip_address": "192.168.1.100",
      "user_agent": "Mozilla/5.0...",
      "access_result": "success"
    }
  ],
  "total": 42
}
```

### Share Statistics

Get aggregated statistics for a share:

```bash
GET /api/bess-dispatch/admin/shares/{share_id}/stats
```

Response:
```json
{
  "share_id": "share_abc",
  "total_accesses": 42,
  "successful_accesses": 40,
  "denied_accesses": 2,
  "first_access_at": "2025-01-01T00:00:00Z",
  "last_access_at": "2025-01-15T10:30:00Z",
  "unique_ips": 5
}
```

### Data Retention (v3.8.0 PR5)

#### Retention Statistics

View what can be purged:

```bash
GET /api/bess-dispatch/admin/retention/stats
```

Response:
```json
{
  "active_shares": 15,
  "expired_shares": 8,
  "expired_shares_purgeable": 5,
  "revoked_shares": 12,
  "revoked_shares_purgeable": 10,
  "total_access_logs": 1234,
  "access_logs_purgeable": 456
}
```

#### Purge Expired Shares

Delete shares expired more than N days ago:

```bash
POST /api/bess-dispatch/admin/retention/purge-expired-shares
{
  "older_than_days": 30
}
```

#### Purge Revoked Shares

Delete shares revoked more than N days ago:

```bash
POST /api/bess-dispatch/admin/retention/purge-revoked-shares
{
  "older_than_days": 30
}
```

#### Prune Access Logs

Delete access logs older than N days:

```bash
POST /api/bess-dispatch/admin/retention/prune-access-logs
{
  "older_than_days": 90
}
```

### Retention Defaults

| Policy | Default | Description |
|--------|---------|-------------|
| Expired shares | 30 days | Delete shares expired 30+ days ago |
| Revoked shares | 30 days | Delete shares revoked 30+ days ago |
| Access logs | 90 days | Delete logs older than 90 days |

### Audit Events

Share operations are logged:
- `share_created` (with security options)
- `share_revoked`
- `share_access_success`
- `share_access_denied` (with reason)
- `share_token_rotated`
- `share_revoke_all`
- `retention.purge_expired_shares`
- `retention.purge_revoked_shares`
- `retention.prune_access_logs`

### Frontend Integration

#### Share Modal (index.html)

Click "Udostępnij" button on a run to open the share modal:
- Password toggle with optional input
- Single-use checkbox
- Max access count input
- Expiry hours input

#### Shares Tab (settings.html)

The Settings page has a "Linki" tab for:
- Viewing all shares with status badges
- Rotating share tokens
- Viewing share statistics
- Revoking individual shares
- Bulk revoking all shares

### Security Best Practices

1. **Use passwords for sensitive data** - Always set a password for confidential reports
2. **Set reasonable expiry times** - Default to 24-72 hours for temporary shares
3. **Use single-use for one-time access** - Downloads, previews that shouldn't be revisited
4. **Monitor access logs** - Watch for suspicious patterns (many IPs, denied accesses)
5. **Enforce project policies** - Set `share_max_expiry_hours` on projects for compliance
6. **Regular retention cleanup** - Purge expired/revoked shares monthly
7. **Rotate tokens after suspected leak** - Use token rotation without losing settings
