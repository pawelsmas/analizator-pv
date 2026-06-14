# Runbook: Energy Studio Integration Deploy

## Overview

This runbook covers deployment of:
- Migration 004: Integration metadata (HubSpot, Portfolio, Offer fields)
- Migration 005: Publication history + anti-duplicate constraints

## Pre-Deployment Checklist

### 1. Environment Verification

```bash
# Verify database connection
docker exec pv-postgres pg_isready -h localhost -U pvanalyzer

# Check current migration state
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT table_name FROM information_schema.tables
WHERE table_name IN ('offer_publication_history', 'project_economics_snapshot')
ORDER BY table_name;
\""
```

**Expected:** `project_economics_snapshot` exists, `offer_publication_history` may not exist yet.

### 2. Data Conflict Check (CRITICAL)

Before running migrations, check for constraint conflicts:

```bash
# Check for duplicate hubspot_deal_id (would block migration 005)
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT hubspot_deal_id, COUNT(*) as cnt, array_agg(id) as project_ids
FROM projects
WHERE hubspot_deal_id IS NOT NULL
GROUP BY hubspot_deal_id
HAVING COUNT(*) > 1;
\""
```

**Expected:** Empty result (no duplicates)
**If duplicates exist:** STOP. Resolve duplicates before proceeding.

```bash
# Check existing integration columns
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT column_name FROM information_schema.columns
WHERE table_name = 'projects' AND column_name LIKE '%hubspot%';
\""
```

### 3. Backup (REQUIRED for production)

```bash
# Create backup before migration
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 pg_dump -h localhost -U pvanalyzer pvanalyzer > /tmp/backup_pre_integration_$(date +%Y%m%d_%H%M%S).sql"

# Verify backup
docker exec pv-postgres ls -la /tmp/backup_pre_integration_*.sql
```

---

## Deployment Steps

### Step 1: Run Migration 004 (Integration Metadata)

```bash
# Copy migration to container
docker cp services/database-api/migrations/004_add_integration_metadata.sql pv-postgres:/tmp/

# Run migration
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -f /tmp/004_add_integration_metadata.sql"
```

**Verify:**
```bash
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT column_name FROM information_schema.columns
WHERE table_name = 'projects' AND column_name IN ('hubspot_deal_id', 'offer_id', 'selected_snapshot_id')
ORDER BY column_name;
\""
```

**Expected:** 3 columns listed

### Step 2: Run Migration 005 (Publication History + Constraints)

```bash
# Copy migration to container
docker cp services/database-api/migrations/005_add_publication_history_and_constraints.sql pv-postgres:/tmp/

# Run migration
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -f /tmp/005_add_publication_history_and_constraints.sql"
```

**Verify:**
```bash
# Check publication_history table
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT table_name,
       CASE WHEN table_name = 'offer_publication_history' THEN 'PASS' ELSE 'FAIL' END as status
FROM information_schema.tables
WHERE table_name = 'offer_publication_history';
\""

# Check unique constraint
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT constraint_name, 'PASS' as status
FROM information_schema.table_constraints
WHERE table_name = 'projects' AND constraint_name = 'uq_projects_hubspot_deal_id';
\""
```

### Step 3: Restart Services

```bash
# Rebuild and restart database-api
docker-compose up -d --build pv-database-api

# Wait for service to be ready
sleep 10

# Health check
curl -s http://localhost:8050/health | jq .
```

**Expected:** `{"status": "healthy"}`

### Step 4: Smoke Tests

```bash
# Test offer-package endpoint (should return 404 if no snapshot)
curl -s http://localhost:8050/projects/1/offer-package | jq .

# Test publication-history endpoint
curl -s http://localhost:8050/projects/1/publication-history | jq .
```

---

## Post-Deployment Verification

### Verification Checklist

| Check | Command | Expected | Status |
|-------|---------|----------|--------|
| Migration 004 columns | See Step 1 verify | 3 columns | |
| Publication history table | See Step 2 verify | Table exists | |
| Unique constraint | See Step 2 verify | Constraint exists | |
| API health | `curl /health` | healthy | |
| Offer package endpoint | `curl /projects/1/offer-package` | 200 or 404 | |

### Full Verification Query

```sql
-- Run this to verify complete migration state
SELECT
  'projects.hubspot_deal_id' as check_item,
  CASE WHEN EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'projects' AND column_name = 'hubspot_deal_id'
  ) THEN 'PASS' ELSE 'FAIL' END as status
UNION ALL
SELECT
  'projects.offer_id',
  CASE WHEN EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'projects' AND column_name = 'offer_id'
  ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT
  'offer_publication_history table',
  CASE WHEN EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_name = 'offer_publication_history'
  ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT
  'uq_projects_hubspot_deal_id constraint',
  CASE WHEN EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'uq_projects_hubspot_deal_id'
  ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT
  'companies.max_eaas_duration_years',
  CASE WHEN EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'companies' AND column_name = 'max_eaas_duration_years'
  ) THEN 'PASS' ELSE 'FAIL' END;
```

---

## Rollback Procedure

### If Migration 005 Fails

```sql
-- Drop publication history table
DROP TABLE IF EXISTS offer_publication_history;

-- Drop unique constraint
ALTER TABLE projects DROP CONSTRAINT IF EXISTS uq_projects_hubspot_deal_id;

-- Drop new company columns
ALTER TABLE companies DROP COLUMN IF EXISTS max_eaas_duration_years;
ALTER TABLE companies DROP COLUMN IF EXISTS approval_required;
ALTER TABLE companies DROP COLUMN IF EXISTS required_deposit_pct;
ALTER TABLE companies DROP COLUMN IF EXISTS required_security;
```

### If Migration 004 Fails

```sql
-- Drop integration columns from projects
ALTER TABLE projects DROP COLUMN IF EXISTS hubspot_company_id;
ALTER TABLE projects DROP COLUMN IF EXISTS hubspot_deal_id;
ALTER TABLE projects DROP COLUMN IF EXISTS portfolio_company_id;
ALTER TABLE projects DROP COLUMN IF EXISTS selected_option_key;
ALTER TABLE projects DROP COLUMN IF EXISTS selected_snapshot_id;
ALTER TABLE projects DROP COLUMN IF EXISTS offer_id;
ALTER TABLE projects DROP COLUMN IF EXISTS offer_version;
ALTER TABLE projects DROP COLUMN IF EXISTS offer_published_at;

-- Drop snapshot integration columns
ALTER TABLE project_economics_snapshot DROP COLUMN IF EXISTS is_customer_visible;
ALTER TABLE project_economics_snapshot DROP COLUMN IF EXISTS customer_portal_published_at;
ALTER TABLE project_economics_snapshot DROP COLUMN IF EXISTS customer_portal_published_by;
ALTER TABLE project_economics_snapshot DROP COLUMN IF EXISTS credit_score_snapshot_id;
ALTER TABLE project_economics_snapshot DROP COLUMN IF EXISTS credit_risk_class;
ALTER TABLE project_economics_snapshot DROP COLUMN IF EXISTS max_eaas_duration_allowed;
```

---

## PASS/STOP Criteria

### PASS - Proceed to Production
- [ ] All verification queries return PASS
- [ ] API health check returns healthy
- [ ] Smoke tests complete without errors
- [ ] No duplicate hubspot_deal_id values

### STOP - Do Not Deploy
- [ ] Any verification query returns FAIL
- [ ] Duplicate hubspot_deal_id values exist
- [ ] API fails to start after migration
- [ ] Smoke tests return 500 errors

---

## Contacts

| Role | Contact |
|------|---------|
| Database Admin | [TBD] |
| Backend Lead | [TBD] |
| On-call | [TBD] |
