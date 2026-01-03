# Jak to działa lokalnie (v4.4) — uruchomienie i testy end-to-end

## 1. Uruchomienie
### Start (minimum)
- `make dev-up`
- `docker compose ps`
- API: `http://localhost:8031/api/bess-dispatch`
- Metrics: `http://localhost:8031/metrics`

### Dodatkowe serwisy
- Webhook sink: `docker compose up -d webhook-sink` (port 8099)
- OIDC mock: `docker compose up -d oidc-mock`

## 2. Szybkie testy automatyczne
- `pytest -q`
- `make smoke`
- `make test-frontend`
- `make rc`
- `make rc-auth`

## 3. Najważniejsze moduły i gdzie je testować

### BESS sizing/dispatch (core)
- API: `POST /sizing`
- Sprawdź: `schema_version`, `assumptions_version`, `period_info`, `savings_breakdown.net_savings_pln`
- Flows: `energy_flows` (opcjonalnie timeseries)
- Trace: `battery_trace` + `cycle_summary`

### Finance
- `finance_config` w request
- Weryfikacje: NPV/IRR spójne z cashflow, sensitivity monotonic

### Grid constraints + Pareto
- `grid_constraints` + `constraints_config`
- `constraints_report`, `pareto_frontier`, `unserved_load_kwh` + penalty

### Reports (Run/Portfolio)
- Run: `/runs/{id}/report.zip|pdf|xlsx`
- Portfolio: export ZIP/CSV/XLSX

### Run Explorer
- PATCH metadata runów (label/tags/notes)
- Porównywanie runów

### Security (hardening)
- rate limiting 429
- lockout 423
- refresh token rotation
- audit verify (tamper-evident)

### Projects + RBAC
- `X-Project-Id` scoping
- membership management
- 404 dla obcych projektów

### Shares + Share Security
- share links (token)
- password protection, single-use, max access
- rotate token, revoke-all
- share stats + access log

### Quotas/Usage/Plans
- 429 QUOTA_EXCEEDED + Retry-After
- usage endpoints + CSV export
- UI: Billing/Usage + project quotas

### Webhooks
- outbox + retry/backoff + DLQ
- signing headers (HMAC)
- ops: deliveries, replay
- test: webhook-sink

### OIDC/MFA/Sessions
- OIDC PKCE flow + exchange_code
- MFA TOTP + recovery codes
- sessions list/revoke

### Compliance/Retention
- retention policy (tenant/project)
- purge dry-run/execute + legal hold
- compliance export job → ZIP z manifest SHA256 + redaction

### SCIM provisioning (v4.4)
- SCIM Users/Groups endpoints
- SCIM token create/rotate/revoke
- group→project mapping + sync-now
- membership source manual vs scim
- deprovision: disable user + revoke sessions/api keys

## 4. Najważniejsze packi rc-auth
Uruchamianie:
- `PACK=<name> make validate-pack`

Lista:
- baseline
- clean_contract
- projects_rbac_auth
- share_auth / share_security_auth
- quotas_billing
- webhooks_auth
- oidc_mfa_sessions_auth
- compliance_retention_auth
- scim_provisioning_auth

## 5. Observability
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000` (admin/pvoptimizer)
- Kluczowe metryki: bess_* (auth/shares/webhooks/quotas/retention/compliance/scim)

## 6. Zdobycie tokenu admina

```bash
API="http://localhost:8031/api/bess-dispatch"
ADMIN_EMAIL="admin@local"
ADMIN_PASS="admin"

TOKEN=$(curl -sS -X POST "$API/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASS\"}" | jq -r .access_token)

echo "$TOKEN" | head -c 20; echo
```

## 7. Przykładowe komendy API

### Sizing (stacked)
```bash
curl -sS -X POST "$API/sizing" \
  -H "Content-Type: application/json" \
  -d @scripts/smoke/sizing_stacked_no_arbitrage.json | head
```

### Projects
```bash
# Create project
curl -sS -X POST "$API/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Project A"}'

# List runs w projekcie
PROJECT_ID="<project_id>"
curl -sS -H "Authorization: Bearer $TOKEN" -H "X-Project-Id: $PROJECT_ID" "$API/runs" | head
```

### SCIM (v4.4)
```bash
# Create SCIM token
SCIM_TOKEN=$(curl -sS -X POST "$API/provisioning/tokens" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"local"}' | jq -r .plain_token)

# SCIM ServiceProviderConfig
curl -sS -H "Authorization: Bearer $SCIM_TOKEN" \
  "$API/scim/v2/ServiceProviderConfig" | head

# Create SCIM user
curl -sS -X POST "$API/scim/v2/Users" \
  -H "Authorization: Bearer $SCIM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"schemas":["urn:ietf:params:scim:schemas:core:2.0:User"],"userName":"userA@local","active":true}'
```

### Webhooks
```bash
# Start sink
docker compose up -d webhook-sink

# Create webhook
curl -sS -X POST "$API/webhooks" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"sink","url":"http://webhook-sink:8099/hook","events":["job.succeeded"],"enabled":true}'

# Check events
curl -sS http://localhost:8099/events | head
```

### Compliance/Retention
```bash
# Set retention policy
curl -sS -X PATCH "$API/retention/policy" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled":true,"runs_days":1,"jobs_days":1,"artifacts_days":1,"audit_days":30,"grace_days":0}'

# Dry-run purge
curl -sS -X POST "$API/retention/purge" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mode":"dry_run"}' | head
```

## 8. Full Demo (jedna sekwencja)

```bash
# 1) Start
make dev-up
docker compose ps

# 2) Health + metrics
API="http://localhost:8031/api/bess-dispatch"
curl -sS "$API/health/ready" | head
curl -sS "http://localhost:8031/metrics" | head

# 3) Testy bazowe
pytest -q
make smoke
make rc
make rc-auth

# 4) Wszystkie kluczowe packi
for p in baseline clean_contract projects_rbac_auth share_auth share_security_auth quotas_billing webhooks_auth oidc_mfa_sessions_auth compliance_retention_auth scim_provisioning_auth; do
  echo "== PACK: $p =="
  PACK=$p make validate-pack
done
```

## 9. Troubleshooting

### Docker nie startuje
```bash
docker compose down -v
docker compose up -d --build
docker compose logs -f
```

### Port zajęty
```bash
netstat -an | findstr 8031
# zabij proces lub zmień port w .env
```

### Brak tokenu
- Sprawdź czy admin user jest seeded w `.env`
- Sprawdź logi: `docker compose logs bess-api`

### SCIM nie działa
- Sprawdź czy token nie wygasł: `GET /api/provisioning/tokens`
- Sprawdź metryki: `scim_token_validation_total{result="expired"}`
