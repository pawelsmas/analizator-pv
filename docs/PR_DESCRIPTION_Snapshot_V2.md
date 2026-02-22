# PR: Economics Snapshot V2 - Full Implementation

## Summary

This PR implements the complete Economics Snapshot V2 system with yearly cashflows per model type, backend validations, and ENUM-based model type enforcement.

### What's Implemented

1. **Snapshot V2 Data Contract**
   - Yearly cashflows stored per model type in `project_economics_cashflow_yearly`
   - Full investor model fields added to `project_economics_snapshot`
   - JSONB `full_payload` for audit trail

2. **Time Contract (Critical)**
   | Model | Year Range | Record Count |
   |-------|------------|--------------|
   | CAPEX_CLIENT | 0..30 | 31 records |
   | EAAS_CLIENT | 1..30 | 30 records (no year 0) |
   | EAAS_INVESTOR | 0..duration | duration+1 records (max duration: 25) |

3. **Backend Validations**
   - Year 0 required for CAPEX_CLIENT and EAAS_INVESTOR
   - No gaps in year sequence allowed
   - No duplicate years per model
   - EaaS duration max 25 years
   - model_type must be valid ENUM value

4. **Database Schema**
   - `model_type` column is PostgreSQL ENUM `economics_model_type`
   - Values: `CAPEX_CLIENT`, `EAAS_CLIENT`, `EAAS_INVESTOR`
   - Invalid values rejected at DB level

5. **Additional Features**
   - Unique project name validation (HTTP 409 on duplicate)
   - Margin formula: `margin% = gross_margin / sell_price` (not markup)

## Test Results

### pytest: 18/18 PASSED
```
tests/test_economics_snapshot_validation.py::TestHappyPath::test_valid_snapshot_with_all_models PASSED
tests/test_economics_snapshot_validation.py::TestHappyPath::test_capex_client_year_range PASSED
tests/test_economics_snapshot_validation.py::TestHappyPath::test_eaas_client_year_range PASSED
tests/test_economics_snapshot_validation.py::TestHappyPath::test_eaas_investor_year_range PASSED
tests/test_economics_snapshot_validation.py::TestHappyPath::test_year_0_has_negative_cashflow PASSED
tests/test_economics_snapshot_validation.py::TestValidationErrors::test_missing_year_0_for_capex_client PASSED
tests/test_economics_snapshot_validation.py::TestValidationErrors::test_missing_year_0_for_eaas_investor PASSED
tests/test_economics_snapshot_validation.py::TestValidationErrors::test_gap_in_years PASSED
tests/test_economics_snapshot_validation.py::TestValidationErrors::test_duplicate_year PASSED
tests/test_economics_snapshot_validation.py::TestValidationErrors::test_eaas_duration_exceeds_max PASSED
tests/test_economics_snapshot_validation.py::TestValidationErrors::test_year_out_of_range PASSED
tests/test_economics_snapshot_validation.py::TestMarginFormula::test_margin_formula_is_profit_over_sale_price PASSED
tests/test_economics_snapshot_validation.py::TestDataContractConstants::test_client_analysis_period_is_30 PASSED
tests/test_economics_snapshot_validation.py::TestDataContractConstants::test_max_eaas_duration_is_25 PASSED
tests/test_economics_snapshot_validation.py::TestDataContractConstants::test_discount_rate_stored_as_percentage PASSED
tests/test_economics_snapshot_validation.py::TestDatabaseSchema::test_model_type_is_enum PASSED
tests/test_economics_snapshot_validation.py::TestDatabaseSchema::test_valid_model_types PASSED
tests/test_economics_snapshot_validation.py::TestDatabaseSchema::test_invalid_model_type_should_fail PASSED

======================= 18 passed, 21 warnings in 1.22s =======================
```

### SQL Verification Checklist: ALL PASS

**1. model_type ENUM verification:**
```
 column_name |  data_type   |       udt_name       | verification
-------------+--------------+----------------------+--------------
 model_type  | USER-DEFINED | economics_model_type | PASS
```

**2. Cashflow counts (snapshot_id=7):**
```
  model_type   | row_count | min_year | max_year | verification
---------------+-----------+----------+----------+---------------
 CAPEX_CLIENT  |        31 |        0 |       30 | PASS
 EAAS_CLIENT   |        30 |        1 |       30 | PASS
 EAAS_INVESTOR |        16 |        0 |       15 | PASS (duration=15)
```

**3. Year 0 sign check:**
```
  model_type   | year | net_cashflow_pln |   sign_check
---------------+------+------------------+-----------------
 CAPEX_CLIENT  |    0 |      -1707300.00 | PASS (negative)
 EAAS_INVESTOR |    0 |      -1400000.00 | PASS (negative)
```

**4. Margin formula:**
```
 sell_price | margin_pln | stored_margin_pct | calculated_margin_pct | verification
------------+------------+-------------------+-----------------------+--------------
 1707300.00 |  307300.00 |             18.00 |                 18.00 | PASS
```

**5. ENUM constraint:**
```sql
INSERT INTO project_economics_cashflow_yearly VALUES (7, 'INVALID_TYPE', 99, 0);
-- ERROR: invalid input value for enum economics_model_type: "INVALID_TYPE"
-- PASS: Invalid value rejected
```

## How to Reproduce Verification

### 1. Run pytest
```bash
docker exec pv-database-api pip install pytest
docker exec pv-database-api python -m pytest tests/test_economics_snapshot_validation.py -v
```

### 2. Run SQL Checklist
```bash
# Connect to database
docker exec pv-postgres bash -c "PGPASSWORD=pvanalyzer123 psql -h localhost -U pvanalyzer -d pvanalyzer"

# Run checklist queries from:
# services/database-api/tests/sql_verification_checklist.sql
```

## Files Changed

| File | Change |
|------|--------|
| `services/database-api/app.py` | Unique project name validation |
| `services/database-api/models.py` | PG_ENUM for model_type |
| `services/database-api/init.sql` | ENUM type + table schema |
| `services/database-api/migrations/001_rename_npv_columns.sql` | NPV column rename |
| `services/database-api/migrations/002_add_full_investor_model.sql` | Full investor model fields |
| `services/database-api/migrations/003_convert_model_type_to_enum.sql` | VARCHAR→ENUM migration |
| `services/database-api/tests/test_economics_snapshot_validation.py` | Regression tests |
| `services/database-api/tests/sql_verification_checklist.sql` | SQL verification queries |
| `services/frontend-economics/economics.js` | fullInvestorModel in ECONOMICS_CALCULATED |

## Breaking Changes

- **Migration 003**: `model_type` column changed from VARCHAR to ENUM
  - Run migration before deploying new code
  - See `docs/RUNBOOK_Snapshot_V2_Deployment.md` for details

## Definition of Done

- [x] CAPEX_CLIENT: 31 records, years 0..30
- [x] EAAS_CLIENT: 30 records, years 1..30
- [x] EAAS_INVESTOR: duration+1 records, years 0..duration
- [x] model_type is ENUM economics_model_type
- [x] ENUM has exactly 3 values
- [x] Margin% = margin/sellPrice
- [x] Year 0 has negative cashflow
- [x] Backend rejects invalid model_type
- [x] pytest passes (18/18)
- [x] SQL checklist passes

**Audit Result: 100% PASS - Ready to Merge**
