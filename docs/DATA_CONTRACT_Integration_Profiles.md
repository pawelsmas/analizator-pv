# Data Contract: INTERNAL vs CUSTOMER_SAFE Profiles

**Version:** 2.0
**Last Updated:** 2026-01-11
**Status:** Production-Ready

## Overview

Energy Studio manages two distinct data profiles for economics snapshots:

| Profile | Purpose | Contains | Access |
|---------|---------|----------|--------|
| **INTERNAL** | Full economics data | All costs, margins, investor IRR | Energy Studio only |
| **CUSTOMER_SAFE** | Customer Portal data | Customer-facing metrics only | Customer Portal API |

## Profile Comparison

### INTERNAL Profile (Full Data)

Used in: Energy Studio frontend, Excel exports, Investor reports

```
capex_deal_sell_price_pln      ✓ Customer sees (as "Investment")
capex_deal_direct_cost_pln     ✗ INTERNAL ONLY
capex_deal_gross_margin_pct    ✗ INTERNAL ONLY
capex_deal_gross_margin_pln    ✗ INTERNAL ONLY
eaas_investor_target_irr       ✗ INTERNAL ONLY
eaas_investor_project_irr      ✗ INTERNAL ONLY
eaas_investor_equity_irr       ✗ INTERNAL ONLY
eaas_investor_capex_pln        ✗ INTERNAL ONLY
eaas_investor_debt_pln         ✗ INTERNAL ONLY
eaas_investor_equity_pln       ✗ INTERNAL ONLY
```

### CUSTOMER_SAFE Profile (Offer Package)

Used in: Customer Portal, customer-facing documents

```
CustomerSafeInstallation:
  - pv_capacity_kwp            ✓
  - pv_type                    ✓
  - has_bess                   ✓
  - bess_power_kw              ✓
  - bess_energy_kwh            ✓
  - location_name              ✓

CustomerSafeCapexEconomics:
  - investment_pln             ✓ (sell_price, NOT cost!)
  - npv_pln                    ✓
  - irr_pct                    ✓
  - simple_payback_years       ✓
  - annual_savings_year1_pln   ✓

CustomerSafeEaasEconomics:
  - duration_years             ✓
  - subscription_annual_pln    ✓
  - subscription_monthly_pln   ✓
  - price_per_mwh_pln          ✓
  - npv_pln                    ✓
  - total_savings_pln          ✓
  - savings_vs_grid_pct        ✓
```

## Security Rules

### Rule 1: Never Expose Margins
```
FORBIDDEN in Customer Portal:
- capex_deal_direct_cost_pln
- capex_deal_gross_margin_pct
- capex_deal_gross_margin_pln
```

### Rule 2: Never Expose Investor IRR
```
FORBIDDEN in Customer Portal:
- eaas_investor_target_irr
- eaas_investor_project_irr
- eaas_investor_equity_irr
- eaas_investor_capex_pln (our CAPEX, not customer's)
```

### Rule 3: Show Sell Price, Not Cost
```
Customer sees: "Inwestycja: 1,707,300 PLN" (capex_deal_sell_price_pln)
Customer does NOT see: "Koszt: 1,400,000 PLN" (capex_deal_direct_cost_pln)
```

## API Endpoints

### INTERNAL Access (Energy Studio)

```
GET /projects/{id}/economics-snapshot/latest
→ Returns: EconomicsSnapshotWithCashflows (FULL DATA)

GET /economics-snapshot/{snapshot_id}
→ Returns: EconomicsSnapshotWithCashflows (FULL DATA)
```

### CUSTOMER_SAFE Access (Customer Portal)

```
GET /projects/{id}/offer-package
→ Returns: OfferPackage (CUSTOMER_SAFE DATA ONLY)

POST /projects/{id}/publish-to-customer-portal
→ Marks snapshot as customer-visible
→ Sets offer_id, offer_version, published_at
```

## Integration Endpoints

### HubSpot / Portfolio Linking

```
PUT /projects/{id}/integration
Body: {
  hubspot_company_id: "string",
  hubspot_deal_id: "string",
  portfolio_company_id: int,
  selected_option_key: "A",
  selected_snapshot_id: int
}
```

### Credit Decision (Read-Only)

```
GET /companies/{id}/credit-decision
→ Returns credit risk class, max EaaS duration
→ READ-ONLY from Portfolio Management

POST /economics-snapshot/{id}/attach-credit-decision
→ Attaches current credit terms to snapshot
```

## Offer Package Structure

```json
{
  "offer_id": "OFFER-2026-0001",
  "offer_version": "v1",
  "project_name": "Farma Solarna ABC",
  "company_name": "ABC Sp. z o.o.",
  "created_at": "2026-01-11T10:00:00Z",
  "valid_until": "2026-02-10T10:00:00Z",

  "installation": {
    "pv_capacity_kwp": 500.0,
    "pv_type": "ground_s",
    "has_bess": false
  },

  "consumption": {
    "annual_consumption_kwh": 1200000,
    "peak_power_kw": 450,
    "profile_year": 2024
  },

  "production": {
    "scenario": "P50",
    "annual_production_kwh": 525000,
    "self_consumption_kwh": 367500,
    "self_consumption_rate_pct": 70.0
  },

  "capex_economics": {
    "investment_pln": 1707300,  // SELL PRICE!
    "npv_pln": 500000,
    "irr_pct": 12.5,
    "simple_payback_years": 8.5,
    "annual_savings_year1_pln": 180000
  },

  "eaas_economics": {
    "duration_years": 15,
    "subscription_annual_pln": 96000,
    "subscription_monthly_pln": 8000,
    "npv_pln": 300000,
    "total_savings_over_contract_pln": 450000,
    "savings_vs_grid_pct": 15.0
  },

  "options": [
    {"option_key": "A", "pv_capacity_kwp": 500, "is_selected": true},
    {"option_key": "B", "pv_capacity_kwp": 600, "is_selected": false}
  ],
  "selected_option": "A"
}
```

## Database Schema

### Projects Table (Integration Fields)

```sql
ALTER TABLE projects ADD COLUMN hubspot_company_id VARCHAR(50);
ALTER TABLE projects ADD COLUMN hubspot_deal_id VARCHAR(50);
ALTER TABLE projects ADD COLUMN portfolio_company_id INTEGER;
ALTER TABLE projects ADD COLUMN selected_option_key VARCHAR(10);
ALTER TABLE projects ADD COLUMN selected_snapshot_id INTEGER;
ALTER TABLE projects ADD COLUMN offer_id VARCHAR(50);
ALTER TABLE projects ADD COLUMN offer_version VARCHAR(20);
ALTER TABLE projects ADD COLUMN offer_published_at TIMESTAMP WITH TIME ZONE;
```

### Snapshot Table (Customer Portal Fields)

```sql
ALTER TABLE project_economics_snapshot
  ADD COLUMN credit_score_snapshot_id INTEGER;
ALTER TABLE project_economics_snapshot
  ADD COLUMN credit_risk_class VARCHAR(5);
ALTER TABLE project_economics_snapshot
  ADD COLUMN max_eaas_duration_allowed INTEGER;
ALTER TABLE project_economics_snapshot
  ADD COLUMN is_customer_visible BOOLEAN DEFAULT FALSE;
ALTER TABLE project_economics_snapshot
  ADD COLUMN customer_portal_published_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE project_economics_snapshot
  ADD COLUMN customer_portal_published_by VARCHAR(255);
```

### Companies Table (Credit Decision Cache)

```sql
ALTER TABLE companies ADD COLUMN hubspot_company_id VARCHAR(50);
ALTER TABLE companies ADD COLUMN portfolio_company_id INTEGER;
ALTER TABLE companies ADD COLUMN credit_risk_class VARCHAR(5);
ALTER TABLE companies ADD COLUMN credit_limit_pln NUMERIC(15,2);
ALTER TABLE companies ADD COLUMN credit_score_updated_at TIMESTAMP WITH TIME ZONE;
```

## Credit Risk Class Mapping

| Risk Class | Max EaaS Duration | Deposit Required | Notes |
|------------|-------------------|------------------|-------|
| A | 25 years | No | Best credit |
| B | 20 years | No | Good credit |
| C | 15 years | No | Standard credit |
| D | 10 years | 10% | Higher risk |
| E | 5 years | 20% | Highest risk |

## Migration Path

1. Run migration `004_add_integration_metadata.sql`
2. Rebuild `pv-database-api` container
3. API endpoints available immediately
4. Credit decisions populated via Portfolio sync (future)

## Access Control Requirements

### Endpoint Classification

| Endpoint | Profile | Access Level | Notes |
|----------|---------|--------------|-------|
| `GET /projects/{id}/offer-package` | CUSTOMER_SAFE | Customer Portal | Token/ACL required |
| `POST /projects/{id}/publish-to-customer-portal` | ADMIN | Energy Studio Admin | Creates audit record |
| `GET /projects/{id}/publication-history` | INTERNAL | Energy Studio | Audit trail |
| `PUT /projects/{id}/integration` | ADMIN | Energy Studio Admin | Links HubSpot/Portfolio |
| `GET /companies/{id}/credit-decision` | INTERNAL | Energy Studio | Read-only from Portfolio |
| `GET /economics-snapshot/{id}` | INTERNAL | Energy Studio | Full data access |

### Customer Portal Isolation

```
RULE: Customer Portal must NEVER access internal endpoints

Customer Portal CAN access:
  - GET /projects/{id}/offer-package (with valid offer token)

Customer Portal CANNOT access:
  - GET /economics-snapshot/{id}
  - PUT /projects/{id}/integration
  - Any endpoint returning margins, costs, or investor data
```

### Token-Based Access (Future)

For Customer Portal, implement offer-specific tokens:

```
1. When publishing: generate offer_access_token
2. Customer Portal calls: GET /portal/offer/{offer_id}?token={token}
3. Token validates: offer_id matches, not expired, customer IP allowed
4. Returns: OfferPackage (CUSTOMER_SAFE only)
```

### Admin Endpoints

These endpoints should require admin authentication:

```
PUT /projects/{id}/integration
  - Links project to HubSpot deal
  - Links company to Portfolio
  - Can break anti-duplicate if misused

POST /projects/{id}/publish-to-customer-portal
  - Creates legally binding offer
  - Must be auditable (who published what, when)
```

### Portfolio Integration (Future)

```
Portfolio → Energy Studio (sync):
  - POST /internal/sync/company-credit-decision
  - Requires: portfolio_service_token
  - Updates: Company.credit_* fields

Energy Studio → Portfolio (read):
  - GET /api/v1/companies/{id}/credit-decision (via Portfolio API)
  - Requires: energy_studio_service_token
```

## Verification Queries

### Check project has integration metadata
```sql
SELECT
  id, name,
  hubspot_deal_id, portfolio_company_id,
  offer_id, offer_version, offer_published_at
FROM projects
WHERE id = 123;
```

### Check snapshot is customer-visible
```sql
SELECT
  id, variant_key,
  is_customer_visible, customer_portal_published_at
FROM project_economics_snapshot
WHERE project_id = 123;
```

### Check credit decision attached
```sql
SELECT
  id, credit_risk_class, max_eaas_duration_allowed
FROM project_economics_snapshot
WHERE id = 456;
```

### Check publication history
```sql
SELECT
  offer_id, offer_version, action, published_at,
  pv_capacity_kwp, capex_sell_price_pln
FROM offer_publication_history
WHERE project_id = 123
ORDER BY published_at DESC;
```

## Versioning Semantics

### Scope
- Version scope: `(project_id, offer_id)`
- Each project has one stable `offer_id` (e.g., `OFFER-2026-0001`)
- Versions increment on each publish: v1 → v2 → v3

### Rules
1. First publish → v1
2. Republish (any snapshot) → v(n+1)
3. Republishing same snapshot = new version (audit requirement)
4. Version never decreases
5. Each version creates immutable audit record

### Example
```
Project 123:
  - Publish snapshot 1 → OFFER-2026-0123 v1
  - Publish snapshot 2 → OFFER-2026-0123 v2
  - Republish snapshot 1 → OFFER-2026-0123 v3
```

## Banned Fields List (CUSTOMER_SAFE)

These fields must NEVER appear in CUSTOMER_SAFE responses:

```python
BANNED_FIELDS = {
    # Cost/Margin (reveals our profit)
    "capex_deal_direct_cost_pln",
    "capex_deal_gross_margin_pct",
    "capex_deal_gross_margin_pln",
    "direct_cost",
    "gross_margin",

    # Investor Economics (internal business model)
    "eaas_investor_target_irr",
    "eaas_investor_project_irr",
    "eaas_investor_equity_irr",
    "eaas_investor_capex_pln",
    "eaas_investor_debt_pln",
    "eaas_investor_equity_pln",
    "eaas_investor_leverage_pct",
    "eaas_investor_npv",
    "eaas_investor_*",  # All investor fields

    # Internal Data
    "full_payload",
    "calc_metadata",
    "request_payload",
    "result_payload",

    # Integration IDs (internal references)
    "hubspot_company_id",
    "hubspot_deal_id",
    "portfolio_company_id",
}
```

## Credit Decision Architecture

### Ownership
- **Portfolio Management**: OWNS credit policy and risk assessment
- **Energy Studio**: CONSUMES credit decision (read-only)

### Data Flow
```
D&B/Credit Bureau → Portfolio → Energy Studio → Snapshot
                       ↓
                  credit_risk_class
                  max_eaas_duration_years
                  approval_required
                  required_deposit_pct
```

### Rules
1. Energy Studio does NOT calculate credit policy
2. All credit fields populated BY Portfolio sync
3. Snapshot stores point-in-time reference (frozen at publish)
4. If Portfolio updates decision, existing snapshots unchanged

## Related Documents

- [RUNBOOK_Integration_Deploy.md](RUNBOOK_Integration_Deploy.md) - Deployment procedures
- [GO_LIVE_CHECKLIST_Integration.md](GO_LIVE_CHECKLIST_Integration.md) - Production readiness
