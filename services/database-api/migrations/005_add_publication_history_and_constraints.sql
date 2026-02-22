-- =============================================================================
-- MIGRATION 005: Add Publication History Table and Anti-Duplicate Constraints
-- =============================================================================
-- Date: 2026-01-11
-- Description:
--   1. Creates offer_publication_history table for audit trail
--   2. Adds unique constraint on hubspot_deal_id (anti-duplicate)
--   3. Adds index for faster lookups
-- =============================================================================

-- =============================================================================
-- STEP 1: Create offer_publication_history table
-- =============================================================================

CREATE TABLE IF NOT EXISTS offer_publication_history (
    id BIGSERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    snapshot_id INTEGER REFERENCES project_economics_snapshot(id) ON DELETE SET NULL,

    -- Offer identification
    offer_id VARCHAR(50) NOT NULL,
    offer_version VARCHAR(20) NOT NULL,
    option_key VARCHAR(10),

    -- Publication details
    published_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    published_by VARCHAR(255),
    valid_until TIMESTAMP WITH TIME ZONE,

    -- Snapshot of key values at time of publication (immutable)
    pv_capacity_kwp NUMERIC(12, 3),
    capex_sell_price_pln NUMERIC(15, 2),
    eaas_subscription_annual_pln NUMERIC(15, 2),
    eaas_duration_years INTEGER,

    -- Credit terms at publication
    credit_risk_class VARCHAR(5),
    max_eaas_duration_allowed INTEGER,

    -- Action type: publish, republish, revoke
    action VARCHAR(20) DEFAULT 'publish'
);

-- Index for fast project lookups
CREATE INDEX IF NOT EXISTS idx_publication_history_project
    ON offer_publication_history(project_id);

-- Index for offer_id lookups
CREATE INDEX IF NOT EXISTS idx_publication_history_offer
    ON offer_publication_history(offer_id);

COMMENT ON TABLE offer_publication_history IS
    'Immutable audit trail of all offer publications to Customer Portal';

-- =============================================================================
-- STEP 2: Add unique constraint for hubspot_deal_id (anti-duplicate)
-- =============================================================================
-- Rule: One HubSpot deal = One project (prevents duplicate projects for same deal)

-- First, check for any existing duplicates
DO $$
DECLARE
    duplicate_count INT;
BEGIN
    SELECT COUNT(*) INTO duplicate_count
    FROM (
        SELECT hubspot_deal_id
        FROM projects
        WHERE hubspot_deal_id IS NOT NULL
        GROUP BY hubspot_deal_id
        HAVING COUNT(*) > 1
    ) dups;

    IF duplicate_count > 0 THEN
        RAISE WARNING 'Found % duplicate hubspot_deal_id values. Fix these before adding constraint.', duplicate_count;
        -- Show the duplicates
        RAISE NOTICE 'Duplicate hubspot_deal_ids:';
        FOR r IN (
            SELECT hubspot_deal_id, COUNT(*) as cnt
            FROM projects
            WHERE hubspot_deal_id IS NOT NULL
            GROUP BY hubspot_deal_id
            HAVING COUNT(*) > 1
        )
        LOOP
            RAISE NOTICE '  hubspot_deal_id=% has % projects', r.hubspot_deal_id, r.cnt;
        END LOOP;
    ELSE
        -- Safe to add constraint
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_projects_hubspot_deal_id'
        ) THEN
            ALTER TABLE projects
                ADD CONSTRAINT uq_projects_hubspot_deal_id
                UNIQUE (hubspot_deal_id);
            RAISE NOTICE 'Added unique constraint uq_projects_hubspot_deal_id';
        ELSE
            RAISE NOTICE 'Constraint uq_projects_hubspot_deal_id already exists';
        END IF;
    END IF;
END $$;

-- =============================================================================
-- STEP 3: Add credit decision fields to companies (populated BY Portfolio)
-- =============================================================================
-- IMPORTANT: These fields are READ-ONLY from Energy Studio perspective.
-- They are populated BY Portfolio Management via sync/API.

ALTER TABLE companies ADD COLUMN IF NOT EXISTS max_eaas_duration_years INTEGER;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS approval_required BOOLEAN DEFAULT FALSE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS required_deposit_pct NUMERIC(6, 2);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS required_security VARCHAR(255);

COMMENT ON COLUMN companies.max_eaas_duration_years IS 'Max EaaS duration allowed - FROM Portfolio';
COMMENT ON COLUMN companies.approval_required IS 'Manual approval needed - FROM Portfolio';
COMMENT ON COLUMN companies.required_deposit_pct IS 'Required deposit % - FROM Portfolio';
COMMENT ON COLUMN companies.required_security IS 'Required security type - FROM Portfolio';

-- =============================================================================
-- STEP 4: Add index for company credit lookups
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_companies_portfolio_id
    ON companies(portfolio_company_id)
    WHERE portfolio_company_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_companies_hubspot_id
    ON companies(hubspot_company_id)
    WHERE hubspot_company_id IS NOT NULL;

-- =============================================================================
-- STEP 5: Add index for snapshot customer visibility
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_snapshot_customer_visible
    ON project_economics_snapshot(is_customer_visible)
    WHERE is_customer_visible = TRUE;

-- =============================================================================
-- VERIFICATION
-- =============================================================================

-- Check publication_history table exists
SELECT
    'offer_publication_history' as table_name,
    CASE WHEN EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'offer_publication_history'
    ) THEN 'PASS' ELSE 'FAIL' END as verification;

-- Check unique constraint on hubspot_deal_id
SELECT
    constraint_name,
    CASE WHEN constraint_name = 'uq_projects_hubspot_deal_id'
         THEN 'PASS - Anti-duplicate constraint active'
         ELSE 'CHECK - Constraint may need attention'
    END as verification
FROM information_schema.table_constraints
WHERE table_name = 'projects'
  AND constraint_type = 'UNIQUE'
  AND constraint_name LIKE '%hubspot%';
