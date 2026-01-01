# Authentication & Authorization (v3.0.0)

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
