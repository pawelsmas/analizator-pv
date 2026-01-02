# Authentication & Authorization (v3.7.0)

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
