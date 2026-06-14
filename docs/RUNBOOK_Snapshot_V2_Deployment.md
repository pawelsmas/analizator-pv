# RUNBOOK: Economics Snapshot V2 Deployment

**Version:** 4.6.0
**Date:** 2026-01-10
**Risk Level:** MEDIUM (database schema change)
**Estimated Downtime:** 5-10 minutes

---

## Prerequisites

- [ ] Database backup completed
- [ ] Access to PostgreSQL (pvanalyzer user)
- [ ] Docker Compose environment ready
- [ ] New application images built

---

## PHASE 1: PREFLIGHT CHECKS

### 1.1 Check Current model_type Values

```bash
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT DISTINCT model_type, COUNT(*) as count
FROM project_economics_cashflow_yearly
GROUP BY model_type
ORDER BY model_type;
\""
```

**Expected Result:**
```
  model_type   | count
---------------+-------
 CAPEX_CLIENT  |   XXX
 EAAS_CLIENT   |   XXX
 EAAS_INVESTOR |   XXX
```

**✅ PASS criteria:** Only 3 values: CAPEX_CLIENT, EAAS_CLIENT, EAAS_INVESTOR
**❌ STOP criteria:** Any other value present → requires manual cleanup before migration

### 1.2 Check Total Record Count

```bash
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT COUNT(*) as total_cashflow_records FROM project_economics_cashflow_yearly;
\""
```

**Record this number:** _____________ (for post-migration verification)

### 1.3 Check Current Column Type

```bash
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT data_type, udt_name
FROM information_schema.columns
WHERE table_name = 'project_economics_cashflow_yearly'
AND column_name = 'model_type';
\""
```

**Expected Result:**
```
     data_type     | udt_name
-------------------+----------
 character varying | varchar
```

**If already `USER-DEFINED` / `economics_model_type`:** Skip to Phase 3 (already migrated)

---

## PHASE 2: DATABASE MIGRATION

### 2.1 Create ENUM Type (if not exists)

```bash
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
DO \\\$\\\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'economics_model_type') THEN
        CREATE TYPE economics_model_type AS ENUM ('CAPEX_CLIENT', 'EAAS_CLIENT', 'EAAS_INVESTOR');
        RAISE NOTICE 'Created ENUM type economics_model_type';
    ELSE
        RAISE NOTICE 'ENUM type already exists';
    END IF;
END \\\$\\\$;
\""
```

**Expected:** `NOTICE: Created ENUM type economics_model_type` or `NOTICE: ENUM type already exists`

### 2.2 Normalize Values (safety step)

```bash
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
UPDATE project_economics_cashflow_yearly
SET model_type = UPPER(TRIM(model_type))
WHERE model_type != UPPER(TRIM(model_type));
\""
```

**Expected:** `UPDATE X` (usually 0 rows affected)

### 2.3 Convert Column to ENUM

```bash
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
-- Drop index
DROP INDEX IF EXISTS idx_econ_cashflow_model;

-- Convert column type
ALTER TABLE project_economics_cashflow_yearly
ALTER COLUMN model_type TYPE economics_model_type
USING model_type::economics_model_type;

-- Recreate index
CREATE INDEX idx_econ_cashflow_model ON project_economics_cashflow_yearly(model_type);
\""
```

**Expected:**
```
DROP INDEX
ALTER TABLE
CREATE INDEX
```

**❌ STOP criteria:** `ERROR: invalid input value for enum` → rollback and fix data

---

## PHASE 3: POST-MIGRATION VERIFICATION

### 3.1 Verify Column Type

```bash
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT
    data_type,
    udt_name,
    CASE
        WHEN data_type = 'USER-DEFINED' AND udt_name = 'economics_model_type'
        THEN 'PASS'
        ELSE 'FAIL'
    END as verification
FROM information_schema.columns
WHERE table_name = 'project_economics_cashflow_yearly'
AND column_name = 'model_type';
\""
```

**✅ PASS criteria:** `data_type=USER-DEFINED, udt_name=economics_model_type, verification=PASS`

### 3.2 Verify ENUM Values

```bash
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT unnest(enum_range(NULL::economics_model_type)) AS enum_values;
\""
```

**✅ PASS criteria:**
```
  enum_values
---------------
 CAPEX_CLIENT
 EAAS_CLIENT
 EAAS_INVESTOR
```

### 3.3 Verify Record Count (unchanged)

```bash
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT COUNT(*) as total_cashflow_records FROM project_economics_cashflow_yearly;
\""
```

**✅ PASS criteria:** Same count as recorded in 1.2

### 3.4 Verify Unique Constraint Works

```bash
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT constraint_name FROM information_schema.table_constraints
WHERE table_name = 'project_economics_cashflow_yearly'
AND constraint_type = 'UNIQUE';
\""
```

**✅ PASS criteria:** Constraint exists

### 3.5 Verify ENUM Rejects Invalid Values

```bash
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
INSERT INTO project_economics_cashflow_yearly (snapshot_id, model_type, year, net_cashflow_pln)
VALUES (999999, 'INVALID_TYPE', 0, 0);
\"" 2>&1 || echo "PASS: Invalid value rejected"
```

**✅ PASS criteria:** `ERROR: invalid input value for enum economics_model_type`

---

## PHASE 4: APPLICATION DEPLOYMENT

### 4.1 Rebuild and Deploy database-api

```bash
cd /path/to/ANALIZATOR-PV
docker-compose up -d --build database-api
```

Wait for container to be healthy:
```bash
docker ps | grep pv-database-api
curl -s http://localhost:8050/health
```

**✅ PASS criteria:** `{"status":"ok","service":"database-api","database":"connected"}`

### 4.2 Run Regression Tests

```bash
docker exec pv-database-api pip install pytest --quiet
docker exec pv-database-api python -m pytest tests/test_economics_snapshot_validation.py -v
```

**✅ PASS criteria:** `18 passed`

### 4.3 Rebuild Frontend (if applicable)

```bash
docker-compose up -d --build frontend-economics frontend-shell
```

### 4.4 End-to-End Test: Create New Snapshot

1. Open application in browser
2. Load or create a project
3. Go to Economics tab
4. Save the project

Verify in database:
```bash
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT id, project_id, snapshot_version, created_at
FROM project_economics_snapshot
ORDER BY id DESC LIMIT 1;
\""
```

**✅ PASS criteria:** New snapshot created with recent timestamp

---

## PHASE 5: SQL VERIFICATION CHECKLIST

Run full verification on latest snapshot:

```bash
# Get latest snapshot ID
SNAPSHOT_ID=$(docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -t -c \"SELECT MAX(id) FROM project_economics_snapshot;\"" | tr -d ' ')

echo "Verifying snapshot ID: $SNAPSHOT_ID"

# Run checklist
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
SELECT
  model_type,
  COUNT(*) AS row_count,
  MIN(year) AS min_year,
  MAX(year) AS max_year
FROM project_economics_cashflow_yearly
WHERE snapshot_id = $SNAPSHOT_ID
GROUP BY model_type
ORDER BY model_type;
\""
```

**✅ PASS criteria:**
```
  model_type   | row_count | min_year | max_year
---------------+-----------+----------+----------
 CAPEX_CLIENT  |        31 |        0 |       30
 EAAS_CLIENT   |        30 |        1 |       30
 EAAS_INVESTOR |   (d+1)   |        0 |    (d)
```

---

## ROLLBACK PROCEDURE

**When to rollback:**
- Migration fails with data errors
- Application cannot connect to database
- Critical functionality broken

### Rollback Steps

1. **Stop application:**
   ```bash
   docker-compose stop database-api
   ```

2. **Revert column type:**
   ```bash
   docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
   ALTER TABLE project_economics_cashflow_yearly
   ALTER COLUMN model_type TYPE VARCHAR(20) USING model_type::text;
   \""
   ```

3. **Optionally drop ENUM:**
   ```bash
   docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"
   DROP TYPE IF EXISTS economics_model_type;
   \""
   ```

4. **Deploy previous application version:**
   ```bash
   git checkout <previous-commit>
   docker-compose up -d --build database-api
   ```

---

## SUCCESS CRITERIA SUMMARY

| Check | Expected | Status |
|-------|----------|--------|
| model_type is ENUM | USER-DEFINED / economics_model_type | ☐ |
| ENUM has 3 values | CAPEX_CLIENT, EAAS_CLIENT, EAAS_INVESTOR | ☐ |
| Record count unchanged | Same as preflight | ☐ |
| Unique constraint works | Exists | ☐ |
| Invalid values rejected | ERROR on insert | ☐ |
| database-api healthy | Status: ok | ☐ |
| pytest passes | 18/18 passed | ☐ |
| New snapshot creates | E2E test passes | ☐ |
| SQL checklist passes | Correct counts/ranges | ☐ |

**Deployment Complete when all checks are ☑**

---

## STOP CRITERIA

**Immediately stop and escalate if:**

1. ❌ Preflight finds invalid model_type values
2. ❌ Migration fails with `invalid input value for enum`
3. ❌ Record count differs after migration
4. ❌ database-api cannot start
5. ❌ pytest has failures (not just warnings)
6. ❌ Cannot create new snapshot

---

## Contacts

- **Database Admin:** [contact]
- **Application Owner:** [contact]
- **On-call:** [contact]

---

**Document Version:** 1.0
**Last Updated:** 2026-01-10
