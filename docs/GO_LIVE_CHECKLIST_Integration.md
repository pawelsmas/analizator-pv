# Go-Live Checklist: Energy Studio Integration for 3 Portals

## Overview

This checklist covers deployment readiness for:
- Energy Studio (source of truth for economics)
- Customer Portal (customer-facing offers)
- Portfolio Management (credit/risk integration)
- HubSpot (CRM integration)

---

## Pre-Deployment Checks

### Database Migrations

| # | Check | Command | Expected | Status |
|---|-------|---------|----------|--------|
| 1 | Migration 004 ready | File exists | `004_add_integration_metadata.sql` | [ ] |
| 2 | Migration 005 ready | File exists | `005_add_publication_history_and_constraints.sql` | [ ] |
| 3 | No duplicate hubspot_deal_id | See runbook query | Empty result | [ ] |
| 4 | Backup created | `pg_dump` executed | Backup file exists | [ ] |

### Code Deployment

| # | Check | Expected | Status |
|---|-------|----------|--------|
| 1 | models.py updated | OfferPublicationHistory, Company credit fields | [ ] |
| 2 | schemas.py updated | CustomerSafe*, OfferPackage schemas | [ ] |
| 3 | app.py updated | New endpoints + access control | [ ] |
| 4 | Tests pass | `pytest tests/` all green | [ ] |

---

## Security Verification

### CUSTOMER_SAFE Data Isolation

| # | Check | Verification | Status |
|---|-------|--------------|--------|
| 1 | offer-package has no banned fields | Run `test_customer_safe_redaction.py` | [ ] |
| 2 | publication-history has no internal data | Manual review | [ ] |
| 3 | Redaction guard active | `verify_customer_safe_response()` in app.py | [ ] |

**Banned Fields (must NEVER appear in CUSTOMER_SAFE responses):**
```
capex_deal_direct_cost_pln
capex_deal_gross_margin_pct
capex_deal_gross_margin_pln
eaas_investor_* (all fields)
full_payload
hubspot_company_id
hubspot_deal_id
portfolio_company_id
```

### Access Control

| # | Endpoint | Required Token | Test | Status |
|---|----------|---------------|------|--------|
| 1 | GET /offer-package | Any (customer OK) | [ ] | [ ] |
| 2 | POST /publish-to-customer-portal | ADMIN | Run test | [ ] |
| 3 | PUT /integration | ADMIN | Run test | [ ] |
| 4 | GET /publication-history | INTERNAL or ADMIN | Run test | [ ] |
| 5 | GET /credit-decision | INTERNAL or ADMIN | Run test | [ ] |
| 6 | POST /attach-credit-decision | ADMIN | Run test | [ ] |

---

## Functional Verification

### Offer Package Flow

| # | Step | Expected | Status |
|---|------|----------|--------|
| 1 | Create project with snapshot | Snapshot saved | [ ] |
| 2 | GET /offer-package | Returns CUSTOMER_SAFE data | [ ] |
| 3 | Verify investment_pln = sell_price | NOT cost | [ ] |
| 4 | Verify no investor fields in response | Check JSON | [ ] |

### Publish Flow

| # | Step | Expected | Status |
|---|------|----------|--------|
| 1 | First publish | Creates v1, offer_id generated | [ ] |
| 2 | Check publication_history | 1 record with action=publish | [ ] |
| 3 | Republish same project | Creates v2 | [ ] |
| 4 | Check publication_history | 2 records (v1, v2) | [ ] |

### Credit Decision Flow

| # | Step | Expected | Status |
|---|------|----------|--------|
| 1 | Company has credit data from Portfolio | credit_risk_class set | [ ] |
| 2 | GET /credit-decision | Returns Portfolio data | [ ] |
| 3 | Attach to snapshot | Saves reference only | [ ] |
| 4 | Verify no policy logic in ES | No hardcoded mappings | [ ] |

---

## Integration Points

### HubSpot

| # | Check | Status |
|---|-------|--------|
| 1 | hubspot_deal_id unique constraint active | [ ] |
| 2 | hubspot_company_id stored on Project/Company | [ ] |
| 3 | Anti-duplicate rule enforced (1 deal = 1 project) | [ ] |

### Portfolio Management

| # | Check | Status |
|---|-------|--------|
| 1 | Company.credit_* fields exist | [ ] |
| 2 | Credit decision read-only in ES | [ ] |
| 3 | ES does NOT calculate credit policy | [ ] |
| 4 | credit_score_updated_at populated by Portfolio sync | [ ] |

### Customer Portal

| # | Check | Status |
|---|-------|--------|
| 1 | /offer-package returns complete OfferPackage | [ ] |
| 2 | No internal data in OfferPackage | [ ] |
| 3 | offer_id/offer_version tracked | [ ] |
| 4 | valid_until set on publish | [ ] |

---

## Test Execution

### Unit Tests
```bash
cd services/database-api
pytest tests/test_customer_safe_redaction.py -v
pytest tests/test_access_control.py -v
pytest tests/test_economics_snapshot_validation.py -v
```

### Smoke Tests E2E
```bash
pytest tests/test_smoke_e2e_integration.py -v
```

### Expected Results
- All tests PASS
- No security violations logged
- No banned fields detected

---

## PASS/STOP Criteria

### PASS - Ready for Production

- [ ] All database migrations applied successfully
- [ ] Unique constraint on hubspot_deal_id active
- [ ] offer_publication_history table created
- [ ] All unit tests pass (100%)
- [ ] All smoke tests pass
- [ ] No banned fields in CUSTOMER_SAFE responses (verified)
- [ ] Access control enforced on all protected endpoints
- [ ] Credit decision is reference-only (no policy in ES)
- [ ] API health check returns OK

### STOP - Do Not Deploy

- [ ] Any migration fails
- [ ] Duplicate hubspot_deal_id values exist
- [ ] Tests fail
- [ ] Banned fields detected in customer responses
- [ ] Access control not working
- [ ] Credit policy logic found in ES code

---

## Post-Deployment Verification

### Immediate (within 1 hour)

| # | Check | Status |
|---|-------|--------|
| 1 | API health check | [ ] |
| 2 | Create test project | [ ] |
| 3 | Generate offer-package | [ ] |
| 4 | Publish to customer portal | [ ] |
| 5 | Verify publication history | [ ] |

### Next Day

| # | Check | Status |
|---|-------|--------|
| 1 | No security errors in logs | [ ] |
| 2 | No DATA_LEAK_PREVENTED logs | [ ] |
| 3 | Customer Portal successfully consuming offer-package | [ ] |

---

## Rollback Plan

If critical issues found:

1. **Stop traffic** to affected endpoints
2. **Rollback** using SQL commands in RUNBOOK_Integration_Deploy.md
3. **Notify** team
4. **Investigate** and fix
5. **Re-deploy** after verification

---

## Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Backend Lead | | | |
| Security Review | | | |
| QA | | | |
| Product Owner | | | |

---

## Appendix: Quick Verification Queries

```sql
-- Check migration 004 applied
SELECT column_name FROM information_schema.columns
WHERE table_name = 'projects' AND column_name = 'hubspot_deal_id';

-- Check migration 005 applied
SELECT table_name FROM information_schema.tables
WHERE table_name = 'offer_publication_history';

-- Check unique constraint
SELECT constraint_name FROM information_schema.table_constraints
WHERE constraint_name = 'uq_projects_hubspot_deal_id';

-- Check recent publications
SELECT offer_id, offer_version, action, published_at
FROM offer_publication_history
ORDER BY published_at DESC LIMIT 10;
```
