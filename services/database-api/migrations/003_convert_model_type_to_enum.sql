-- =============================================================================
-- MIGRATION 003: Convert model_type from VARCHAR to ENUM
-- =============================================================================
-- Date: 2026-01-10
-- Description: Converts model_type column in project_economics_cashflow_yearly
--              from VARCHAR to ENUM economics_model_type for data integrity.
--
-- IMPORTANT: Run this migration on existing databases where model_type is VARCHAR.
--            New installations (after init.sql update) already have ENUM.
--
-- Pre-requisites:
--   - Backup your database before running
--   - All model_type values must be one of: CAPEX_CLIENT, EAAS_CLIENT, EAAS_INVESTOR
-- =============================================================================

-- =============================================================================
-- STEP 1: PREFLIGHT CHECK - Verify current state
-- =============================================================================
-- Run this first to see if migration is needed

DO $$
DECLARE
    current_type TEXT;
    invalid_count INT;
BEGIN
    -- Check current column type
    SELECT data_type INTO current_type
    FROM information_schema.columns
    WHERE table_name = 'project_economics_cashflow_yearly'
    AND column_name = 'model_type';

    IF current_type = 'USER-DEFINED' THEN
        RAISE NOTICE 'Column model_type is already ENUM. Migration not needed.';
        RETURN;
    END IF;

    RAISE NOTICE 'Current model_type type: %. Proceeding with migration...', current_type;

    -- Check for invalid values
    SELECT COUNT(*) INTO invalid_count
    FROM project_economics_cashflow_yearly
    WHERE model_type NOT IN ('CAPEX_CLIENT', 'EAAS_CLIENT', 'EAAS_INVESTOR');

    IF invalid_count > 0 THEN
        RAISE EXCEPTION 'Found % rows with invalid model_type values. Fix these before migration:', invalid_count;
    END IF;

    RAISE NOTICE 'Preflight passed. All model_type values are valid.';
END $$;

-- =============================================================================
-- STEP 2: Show current data distribution (informational)
-- =============================================================================
SELECT
    model_type,
    COUNT(*) as row_count,
    MIN(year) as min_year,
    MAX(year) as max_year
FROM project_economics_cashflow_yearly
GROUP BY model_type
ORDER BY model_type;

-- =============================================================================
-- STEP 3: Create ENUM type if not exists
-- =============================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'economics_model_type') THEN
        CREATE TYPE economics_model_type AS ENUM ('CAPEX_CLIENT', 'EAAS_CLIENT', 'EAAS_INVESTOR');
        RAISE NOTICE 'Created ENUM type economics_model_type';
    ELSE
        RAISE NOTICE 'ENUM type economics_model_type already exists';
    END IF;
END $$;

-- =============================================================================
-- STEP 4: Normalize values (trim whitespace, ensure uppercase)
-- =============================================================================
UPDATE project_economics_cashflow_yearly
SET model_type = UPPER(TRIM(model_type))
WHERE model_type != UPPER(TRIM(model_type));

-- =============================================================================
-- STEP 5: Convert column from VARCHAR to ENUM
-- =============================================================================
-- This is done in a transaction for safety

DO $$
DECLARE
    current_type TEXT;
BEGIN
    -- Re-check current column type
    SELECT data_type INTO current_type
    FROM information_schema.columns
    WHERE table_name = 'project_economics_cashflow_yearly'
    AND column_name = 'model_type';

    IF current_type = 'USER-DEFINED' THEN
        RAISE NOTICE 'Column is already ENUM. Skipping conversion.';
        RETURN;
    END IF;

    -- Drop indexes that reference the column (will recreate after)
    DROP INDEX IF EXISTS idx_econ_cashflow_model;

    -- Alter column type using USING clause for safe cast
    ALTER TABLE project_economics_cashflow_yearly
    ALTER COLUMN model_type TYPE economics_model_type
    USING model_type::economics_model_type;

    RAISE NOTICE 'Successfully converted model_type to ENUM';

    -- Recreate index
    CREATE INDEX idx_econ_cashflow_model ON project_economics_cashflow_yearly(model_type);
    RAISE NOTICE 'Recreated index idx_econ_cashflow_model';
END $$;

-- =============================================================================
-- STEP 6: VERIFICATION - Confirm migration success
-- =============================================================================

-- Check column type is now ENUM
SELECT
    column_name,
    data_type,
    udt_name,
    CASE
        WHEN data_type = 'USER-DEFINED' AND udt_name = 'economics_model_type'
        THEN 'PASS - model_type is ENUM'
        ELSE 'FAIL - model_type is NOT ENUM'
    END as verification
FROM information_schema.columns
WHERE table_name = 'project_economics_cashflow_yearly'
AND column_name = 'model_type';

-- Verify ENUM values
SELECT unnest(enum_range(NULL::economics_model_type)) AS enum_values;

-- Verify data integrity (counts should match pre-migration)
SELECT
    model_type,
    COUNT(*) as row_count
FROM project_economics_cashflow_yearly
GROUP BY model_type
ORDER BY model_type;

-- Verify unique constraint still works
SELECT
    constraint_name,
    constraint_type
FROM information_schema.table_constraints
WHERE table_name = 'project_economics_cashflow_yearly'
AND constraint_name = 'uq_snapshot_model_year';

-- =============================================================================
-- ROLLBACK (if needed - run manually)
-- =============================================================================
-- To rollback, run:
-- ALTER TABLE project_economics_cashflow_yearly
-- ALTER COLUMN model_type TYPE VARCHAR(20)
-- USING model_type::text;
-- DROP TYPE IF EXISTS economics_model_type;

