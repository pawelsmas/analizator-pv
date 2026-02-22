-- =============================================================================
-- MIGRATION 001: Rename NPV columns (remove misleading "25" suffix)
-- =============================================================================
-- Date: 2026-01-10
-- Description: NPV columns were named with "25" suffix suggesting 25-year analysis,
--              but actual analysis periods vary:
--              - CAPEX_CLIENT: analysis_period_years (configurable)
--              - EAAS_CLIENT: eaas_client_duration_years (contract period)
--              - EAAS_INVESTOR: eaas_client_duration_years (contract period)
--
-- Run this migration on existing databases before deploying the updated code.
-- =============================================================================

-- Check if columns exist before renaming (idempotent migration)
DO $$
BEGIN
    -- Rename capex_client_npv25 -> capex_client_npv
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'project_economics_snapshot'
        AND column_name = 'capex_client_npv25'
    ) THEN
        ALTER TABLE project_economics_snapshot
        RENAME COLUMN capex_client_npv25 TO capex_client_npv;
        RAISE NOTICE 'Renamed capex_client_npv25 -> capex_client_npv';
    ELSE
        RAISE NOTICE 'Column capex_client_npv25 does not exist (already migrated or new DB)';
    END IF;

    -- Rename eaas_client_npv25 -> eaas_client_npv
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'project_economics_snapshot'
        AND column_name = 'eaas_client_npv25'
    ) THEN
        ALTER TABLE project_economics_snapshot
        RENAME COLUMN eaas_client_npv25 TO eaas_client_npv;
        RAISE NOTICE 'Renamed eaas_client_npv25 -> eaas_client_npv';
    ELSE
        RAISE NOTICE 'Column eaas_client_npv25 does not exist (already migrated or new DB)';
    END IF;

    -- Rename eaas_investor_npv25 -> eaas_investor_npv
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'project_economics_snapshot'
        AND column_name = 'eaas_investor_npv25'
    ) THEN
        ALTER TABLE project_economics_snapshot
        RENAME COLUMN eaas_investor_npv25 TO eaas_investor_npv;
        RAISE NOTICE 'Renamed eaas_investor_npv25 -> eaas_investor_npv';
    ELSE
        RAISE NOTICE 'Column eaas_investor_npv25 does not exist (already migrated or new DB)';
    END IF;
END $$;

-- Add comments to clarify what each NPV column represents
COMMENT ON COLUMN project_economics_snapshot.capex_client_npv IS
    'NPV for CAPEX Client over analysis_period_years (configurable, typically 25-30 years)';

COMMENT ON COLUMN project_economics_snapshot.eaas_client_npv IS
    'NPV for EaaS Client over eaas_client_duration_years (contract period)';

COMMENT ON COLUMN project_economics_snapshot.eaas_investor_npv IS
    'NPV for EaaS Investor over eaas_client_duration_years (contract period only)';

-- Verification query
SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'project_economics_snapshot'
AND column_name IN ('capex_client_npv', 'eaas_client_npv', 'eaas_investor_npv')
ORDER BY column_name;
