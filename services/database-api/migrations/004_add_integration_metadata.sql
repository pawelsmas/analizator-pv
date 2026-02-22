-- =============================================================================
-- MIGRATION 004: Add Integration Metadata for HubSpot/Portfolio/Customer Portal
-- =============================================================================
-- Date: 2026-01-11
-- Description: Adds metadata fields to enable integration between:
--   - Energy Studio (source of truth for economics)
--   - Portfolio Management (CRM, billing, credit risk)
--   - Customer Portal (customer-facing offer presentation)
--   - HubSpot (external CRM sync)
--
-- New fields on projects table:
--   - hubspot_company_id: HubSpot Company ID
--   - hubspot_deal_id: HubSpot Deal ID (anti-duplicate key)
--   - portfolio_company_id: Portfolio Management internal Company ID
--   - selected_option_key: Which variant (A/B/C/D) is selected for offer
--   - selected_snapshot_id: Which snapshot is published to Customer Portal
--   - offer_id: Offer identifier (e.g., OFFER-2026-001)
--   - offer_version: Offer version (v1, v2, etc.)
--   - offer_published_at: When offer was published to Customer Portal
--
-- New fields on project_economics_snapshot table:
--   - credit_score_snapshot_id: Reference to credit decision used for this offer
--   - credit_risk_class: Risk class at time of snapshot (A/B/C/D/E)
--   - is_customer_visible: Whether this snapshot is safe for Customer Portal
--   - customer_portal_published_at: When published to Customer Portal
-- =============================================================================

-- =============================================================================
-- PART 1: Projects table - Integration metadata
-- =============================================================================

-- HubSpot integration
ALTER TABLE projects
ADD COLUMN IF NOT EXISTS hubspot_company_id VARCHAR(50);

ALTER TABLE projects
ADD COLUMN IF NOT EXISTS hubspot_deal_id VARCHAR(50);

COMMENT ON COLUMN projects.hubspot_company_id IS 'HubSpot Company ID for CRM sync';
COMMENT ON COLUMN projects.hubspot_deal_id IS 'HubSpot Deal ID - anti-duplicate key (1 deal = 1 project)';

-- Portfolio Management integration
ALTER TABLE projects
ADD COLUMN IF NOT EXISTS portfolio_company_id INTEGER;

COMMENT ON COLUMN projects.portfolio_company_id IS 'Portfolio Management internal Company ID';

-- Offer management
ALTER TABLE projects
ADD COLUMN IF NOT EXISTS selected_option_key VARCHAR(10);

ALTER TABLE projects
ADD COLUMN IF NOT EXISTS selected_snapshot_id INTEGER;

ALTER TABLE projects
ADD COLUMN IF NOT EXISTS offer_id VARCHAR(50);

ALTER TABLE projects
ADD COLUMN IF NOT EXISTS offer_version VARCHAR(20);

ALTER TABLE projects
ADD COLUMN IF NOT EXISTS offer_published_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN projects.selected_option_key IS 'Selected variant for offer (A/B/C/D)';
COMMENT ON COLUMN projects.selected_snapshot_id IS 'Snapshot ID published to Customer Portal';
COMMENT ON COLUMN projects.offer_id IS 'Offer identifier (e.g., OFFER-2026-001)';
COMMENT ON COLUMN projects.offer_version IS 'Offer version (v1, v2, etc.)';
COMMENT ON COLUMN projects.offer_published_at IS 'When offer was published to Customer Portal';

-- Create index for HubSpot lookups
CREATE INDEX IF NOT EXISTS idx_projects_hubspot_deal ON projects(hubspot_deal_id) WHERE hubspot_deal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_projects_portfolio_company ON projects(portfolio_company_id) WHERE portfolio_company_id IS NOT NULL;

-- =============================================================================
-- PART 2: Snapshot table - Credit and publishing metadata
-- =============================================================================

-- Credit decision reference (read-only from Portfolio)
ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS credit_score_snapshot_id INTEGER;

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS credit_risk_class VARCHAR(5);

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS max_eaas_duration_allowed INTEGER;

COMMENT ON COLUMN project_economics_snapshot.credit_score_snapshot_id IS 'Reference to Portfolio credit decision used for this offer';
COMMENT ON COLUMN project_economics_snapshot.credit_risk_class IS 'Risk class at time of snapshot (A/B/C/D/E)';
COMMENT ON COLUMN project_economics_snapshot.max_eaas_duration_allowed IS 'Max EaaS duration allowed by credit policy';

-- Customer Portal visibility
ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS is_customer_visible BOOLEAN DEFAULT FALSE;

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS customer_portal_published_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS customer_portal_published_by VARCHAR(255);

COMMENT ON COLUMN project_economics_snapshot.is_customer_visible IS 'Whether this snapshot can be shown in Customer Portal';
COMMENT ON COLUMN project_economics_snapshot.customer_portal_published_at IS 'When published to Customer Portal';
COMMENT ON COLUMN project_economics_snapshot.customer_portal_published_by IS 'Who published to Customer Portal';

-- =============================================================================
-- PART 3: Companies table - External integrations
-- =============================================================================

ALTER TABLE companies
ADD COLUMN IF NOT EXISTS hubspot_company_id VARCHAR(50);

ALTER TABLE companies
ADD COLUMN IF NOT EXISTS portfolio_company_id INTEGER;

ALTER TABLE companies
ADD COLUMN IF NOT EXISTS credit_risk_class VARCHAR(5);

ALTER TABLE companies
ADD COLUMN IF NOT EXISTS credit_limit_pln NUMERIC(15, 2);

ALTER TABLE companies
ADD COLUMN IF NOT EXISTS credit_score_updated_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN companies.hubspot_company_id IS 'HubSpot Company ID';
COMMENT ON COLUMN companies.portfolio_company_id IS 'Portfolio Management internal ID';
COMMENT ON COLUMN companies.credit_risk_class IS 'Current credit risk class from Portfolio (A/B/C/D/E)';
COMMENT ON COLUMN companies.credit_limit_pln IS 'Credit limit from Portfolio';
COMMENT ON COLUMN companies.credit_score_updated_at IS 'When credit score was last synced';

CREATE INDEX IF NOT EXISTS idx_companies_hubspot ON companies(hubspot_company_id) WHERE hubspot_company_id IS NOT NULL;

-- =============================================================================
-- VERIFICATION
-- =============================================================================

SELECT 'Projects integration fields:' AS check_type;
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'projects'
AND column_name IN ('hubspot_company_id', 'hubspot_deal_id', 'portfolio_company_id',
                    'selected_option_key', 'selected_snapshot_id', 'offer_id',
                    'offer_version', 'offer_published_at')
ORDER BY column_name;

SELECT 'Snapshot integration fields:' AS check_type;
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'project_economics_snapshot'
AND column_name IN ('credit_score_snapshot_id', 'credit_risk_class', 'max_eaas_duration_allowed',
                    'is_customer_visible', 'customer_portal_published_at', 'customer_portal_published_by')
ORDER BY column_name;

SELECT 'Companies integration fields:' AS check_type;
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'companies'
AND column_name IN ('hubspot_company_id', 'portfolio_company_id', 'credit_risk_class',
                    'credit_limit_pln', 'credit_score_updated_at')
ORDER BY column_name;
