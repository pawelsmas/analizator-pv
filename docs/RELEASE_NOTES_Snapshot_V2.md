# Release Notes: Economics Snapshot V2

**Version:** 4.6.0
**Date:** 2026-01-10
**Component:** Pagra Energy Studio - Economics Module

---

## What's New

### Economics Snapshot V2 - Auditable Yearly Cashflows

This release introduces a complete overhaul of how economic calculations are stored, providing full audit trail capability and preparing the foundation for Portfolio Management integration.

#### Business Value

- **Audit Trail**: Every economic calculation is now stored with complete yearly breakdown, enabling full traceability for investor due diligence
- **Portfolio Ready**: Standardized data contract enables future aggregation across multiple projects
- **Data Integrity**: Database-level ENUM constraints prevent invalid data from entering the system

#### Key Features

1. **Three Economic Models with Yearly Cashflows**
   - **CAPEX_CLIENT**: 30-year analysis (years 0-30, 31 records)
   - **EAAS_CLIENT**: 30-year client perspective (years 1-30, 30 records)
   - **EAAS_INVESTOR**: Contract period only (years 0-duration, up to 26 records)

2. **Full Investor Model Persistence**
   - Target/Project/Equity IRR
   - Capital structure (CAPEX, Debt, Equity, Leverage)
   - Contract financials (Revenue, OPEX, Tax, Interest)
   - Model parameters (CIT rate, Depreciation, Indexation, Project life)
   - Residual value

3. **Unique Project Names**
   - Duplicate project names are now rejected (HTTP 409)
   - Polish error message: "Projekt o nazwie 'X' już istnieje. Wybierz inną nazwę."

---

## Breaking Changes

### Migration Required: model_type VARCHAR → ENUM

**Impact:** Database schema change
**Migration file:** `migrations/003_convert_model_type_to_enum.sql`

Before deploying new application code, run the migration on your database:

```bash
# 1. Backup database
# 2. Run migration
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer" < migrations/003_convert_model_type_to_enum.sql

# 3. Verify
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"SELECT data_type, udt_name FROM information_schema.columns WHERE table_name='project_economics_cashflow_yearly' AND column_name='model_type';\""
# Expected: data_type=USER-DEFINED, udt_name=economics_model_type
```

---

## Known Issues

### Non-blocking Warnings

- **SQLAlchemy 2.0 deprecation**: `declarative_base()` should migrate to `sqlalchemy.orm.declarative_base()`
- **Pydantic V2 deprecation**: Class-based `config` should migrate to `ConfigDict`

These warnings do not affect functionality and will be addressed in a future maintenance release.

---

## Verification

After deployment, verify the system is working correctly:

```bash
# Run regression tests
docker exec pv-database-api pip install pytest
docker exec pv-database-api python -m pytest tests/test_economics_snapshot_validation.py -v
# Expected: 18/18 passed

# Verify ENUM
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer -c \"SELECT unnest(enum_range(NULL::economics_model_type));\""
# Expected: CAPEX_CLIENT, EAAS_CLIENT, EAAS_INVESTOR
```

---

## Rollback

If rollback is necessary:

```sql
-- Revert ENUM to VARCHAR
ALTER TABLE project_economics_cashflow_yearly
ALTER COLUMN model_type TYPE VARCHAR(20) USING model_type::text;

-- Optionally drop ENUM type
DROP TYPE IF EXISTS economics_model_type;
```

**Note:** Application code must also be rolled back as it expects ENUM type.

---

## Files Changed

- `services/database-api/app.py`
- `services/database-api/models.py`
- `services/database-api/init.sql`
- `services/database-api/migrations/003_convert_model_type_to_enum.sql`
- `services/database-api/tests/test_economics_snapshot_validation.py`
- `services/database-api/tests/sql_verification_checklist.sql`
- `services/frontend-economics/economics.js`

---

## Contributors

- Implementation: Claude Code AI Assistant
- Review: Pagra Energy Team
